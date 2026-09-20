"""策略内资格判定单元测试：双门槛（Top 10% + 绝对质量门槛）。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.domain.models import SnapshotLineage
from astock_lens.qualifications.contracts import (
    QualificationRuleNotConfigured,
)
from astock_lens.qualifications.dividend import DividendQualifier
from astock_lens.qualifications.garp import GARPQualifier
from astock_lens.qualifications.growth import GrowthQualifier
from astock_lens.qualifications.models import (
    AbsoluteQualificationVerdict,
    QualificationContext,
)
from astock_lens.qualifications.momentum import MomentumQualifier
from astock_lens.qualifications.quality import QualityQualifier
from astock_lens.qualifications.registry import (
    CANONICAL_STRATEGY_IDS,
    build_qualifiers,
)
from astock_lens.qualifications.value import ValueQualifier
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _strategy_result(
    *,
    symbol: str = "600000.SH",
    strategy_id: str = "value",
    rank_percentile: float | None = 0.95,
    score: float | None = 85.0,
    eligible: bool = True,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
        rank_percentile=rank_percentile,
    )


def _context(result: StrategyResult) -> QualificationContext:
    """把策略结果包装为资格上下文，默认沿用其评分快照作为证据。"""
    return QualificationContext(
        strategy_result=result,
        factors=result.factor_snapshot,
    )


class _AlwaysPassAbsoluteRule:
    version = "rule-v1"

    def evaluate(self, context: QualificationContext) -> AbsoluteQualificationVerdict:
        return AbsoluteQualificationVerdict(passed=True, reasons=("absolute pass",))


class _AlwaysFailAbsoluteRule:
    version = "rule-v1"

    def evaluate(self, context: QualificationContext) -> AbsoluteQualificationVerdict:
        return AbsoluteQualificationVerdict(passed=False, risks=("absolute fail",))


def test_percentile_below_top_ten_percent_cannot_qualify() -> None:
    result = _strategy_result(rank_percentile=0.899999)
    qualifier = ValueQualifier(
        absolute_rule=_AlwaysPassAbsoluteRule(),
        qualification_version="v1",
    )
    qualification = qualifier.qualify(_context(result))
    assert qualification.percentile_pass is False
    assert qualification.absolute_pass is True
    assert qualification.qualified is False


def test_percentile_and_absolute_gate_must_both_pass() -> None:
    result = _strategy_result(rank_percentile=0.90)
    qualifier = ValueQualifier(
        absolute_rule=_AlwaysPassAbsoluteRule(),
        qualification_version="v1",
    )
    qualification = qualifier.qualify(_context(result))
    assert qualification.percentile_pass is True
    assert qualification.absolute_pass is True
    assert qualification.qualified is True


def test_qualification_version_is_pinned_and_non_empty() -> None:
    result = _strategy_result(rank_percentile=0.92)
    qualifier = ValueQualifier(
        absolute_rule=_AlwaysPassAbsoluteRule(),
        qualification_version="val-qual-v2",
    )
    qualification = qualifier.qualify(_context(result))
    assert qualification.qualification_version == "val-qual-v2"


def test_absolute_failure_blocks_qualification_even_with_high_percentile() -> None:
    result = _strategy_result(rank_percentile=0.99)
    qualifier = ValueQualifier(
        absolute_rule=_AlwaysFailAbsoluteRule(),
        qualification_version="v1",
    )
    qualification = qualifier.qualify(_context(result))
    assert qualification.percentile_pass is True
    assert qualification.absolute_pass is False
    assert qualification.qualified is False
    assert "absolute fail" in qualification.risks


def test_missing_rank_percentile_raises_value_error() -> None:
    result = _strategy_result(rank_percentile=None)
    qualifier = ValueQualifier(
        absolute_rule=_AlwaysPassAbsoluteRule(),
        qualification_version="v1",
    )
    with pytest.raises(ValueError, match="rank_percentile"):
        qualifier.qualify(_context(result))


def test_qualifier_rejects_mismatched_strategy_id() -> None:
    result = _strategy_result(strategy_id="momentum")
    qualifier = ValueQualifier(
        absolute_rule=_AlwaysPassAbsoluteRule(),
        qualification_version="v1",
    )
    with pytest.raises(ValueError, match="Strategy ID mismatch"):
        qualifier.qualify(_context(result))


def test_six_independent_qualifiers_instantiate_correctly() -> None:
    rule = _AlwaysPassAbsoluteRule()
    qualifiers = [
        ValueQualifier(absolute_rule=rule, qualification_version="v1"),
        GrowthQualifier(absolute_rule=rule, qualification_version="v1"),
        GARPQualifier(absolute_rule=rule, qualification_version="v1"),
        QualityQualifier(absolute_rule=rule, qualification_version="v1"),
        DividendQualifier(absolute_rule=rule, qualification_version="v1"),
        MomentumQualifier(absolute_rule=rule, qualification_version="v1"),
    ]
    assert [q.strategy_id for q in qualifiers] == [
        "value",
        "growth",
        "garp",
        "quality",
        "dividend",
        "momentum",
    ]
    for q in qualifiers:
        res = _strategy_result(strategy_id=q.strategy_id, rank_percentile=0.95)
        qual = q.qualify(_context(res))
        assert qual.qualified is True
        assert qual.strategy_id == q.strategy_id


def test_build_qualifiers_with_missing_rule_raises_not_configured() -> None:
    rules = {
        "value": _AlwaysPassAbsoluteRule(),
        "growth": _AlwaysPassAbsoluteRule(),
        # garp missing
    }
    with pytest.raises(QualificationRuleNotConfigured, match="garp"):
        build_qualifiers(rules)


def test_build_qualifiers_succeeds_when_all_configured() -> None:
    rules = {s: _AlwaysPassAbsoluteRule() for s in CANONICAL_STRATEGY_IDS}
    qualifiers = build_qualifiers(rules)
    assert len(qualifiers) == 6
    assert set(qualifiers.keys()) == set(CANONICAL_STRATEGY_IDS)


def test_factor_threshold_rule_evaluation() -> None:
    from astock_lens.domain.enums import DataStatus
    from astock_lens.factors.contracts import FactorResult
    from astock_lens.qualifications.rules import FactorThreshold, FactorThresholdRule

    rule = FactorThresholdRule(
        strategy_id="growth",
        version="v1",
        thresholds={
            "net_profit_parent_yoy": FactorThreshold(min=15.0),
            "revenue_yoy": FactorThreshold(min=5.0),
        },
    )

    res_pass = _strategy_result(
        strategy_id="growth",
        rank_percentile=0.95,
    )
    factors_pass = (
        FactorResult(
            symbol="600000.SH",
            factor="net_profit_parent_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(strategy_version="v1"),
            raw_value=20.0,
        ),
        FactorResult(
            symbol="600000.SH",
            factor="revenue_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(strategy_version="v1"),
            raw_value=8.0,
        ),
    )
    res_pass = res_pass.model_copy(update={"factor_snapshot": factors_pass})
    verdict_pass = rule.evaluate(_context(res_pass))
    assert verdict_pass.passed is True
    assert len(verdict_pass.risks) == 0

    factors_fail = (
        FactorResult(
            symbol="600000.SH",
            factor="net_profit_parent_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(strategy_version="v1"),
            raw_value=12.0,  # < 15.0
        ),
        FactorResult(
            symbol="600000.SH",
            factor="revenue_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(strategy_version="v1"),
            raw_value=8.0,
        ),
    )
    res_fail = res_pass.model_copy(update={"factor_snapshot": factors_fail})
    verdict_fail = rule.evaluate(_context(res_fail))
    assert verdict_fail.passed is False
    assert any("net_profit_parent_yoy" in r for r in verdict_fail.risks)


def test_load_qualification_rule_from_yaml(tmp_path: Path) -> None:
    from astock_lens.qualifications.rules import load_qualification_rule

    yaml_file = tmp_path / "growth.yaml"
    yaml_file.write_text(
        "strategy_id: growth\n"
        "version: v1\n"
        "thresholds:\n"
        "  net_profit_parent_yoy:\n"
        "    min: 15.0\n"
        "  revenue_yoy:\n"
        "    min: 5.0\n",
        encoding="utf-8",
    )
    rule = load_qualification_rule(yaml_file)
    assert rule.strategy_id == "growth"
    assert rule.version == "v1"
    assert "net_profit_parent_yoy" in rule.thresholds
    assert rule.thresholds["net_profit_parent_yoy"].min == 15.0
    assert rule.thresholds["revenue_yoy"].min == 5.0


def test_load_canonical_qualifiers_missing_rule_raises(tmp_path: Path) -> None:
    from astock_lens.qualifications.registry import load_canonical_qualifiers

    # 临时目录为空，没有任何策略资格配置
    with pytest.raises(
        QualificationRuleNotConfigured,
        match="Missing approved absolute qualification rule",
    ):
        load_canonical_qualifiers(config_dir=tmp_path)


def test_load_canonical_qualifiers_succeeds_when_all_present(tmp_path: Path) -> None:
    from astock_lens.qualifications.registry import load_canonical_qualifiers

    for strat_id in CANONICAL_STRATEGY_IDS:
        yaml_file = tmp_path / f"{strat_id}.yaml"
        yaml_file.write_text(
            f"strategy_id: {strat_id}\nversion: v1\nthresholds: {{}}\n",
            encoding="utf-8",
        )

    qualifiers = load_canonical_qualifiers(config_dir=tmp_path)
    assert len(qualifiers) == 6
    assert set(qualifiers.keys()) == set(CANONICAL_STRATEGY_IDS)


def test_load_canonical_qualifiers_from_default_directory() -> None:
    from astock_lens.qualifications.registry import load_canonical_qualifiers

    qualifiers = load_canonical_qualifiers()
    assert len(qualifiers) == 6
    assert set(qualifiers.keys()) == set(CANONICAL_STRATEGY_IDS)
