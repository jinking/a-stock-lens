"""资格长尾（上下文证据、资格扫描器）。

本文件由 Task 12「文件合并」把以下 2 个同域小文件整体搬入：
    - tests/unit/test_qualification_context.py（3 例）
    - tests/unit/test_eligibility_scanner.py（9 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from datetime import UTC, datetime

import pytest

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.growth import GrowthQualifier
from astock_lens.qualifications.models import QualificationContext
from astock_lens.qualifications.rules import FactorThreshold, FactorThresholdRule
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import StrategyContext, StrategyResult
from astock_lens.strategies.eligibility import EligibilityScanner

# ===========================================================================
# 来源：tests/unit/test_qualification_context.py（3 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# QualificationContext 单元测试：分离策略评分证据与绝对资格证据。
#
# 设计目标（见 2026-09-20 规格 §4）：资格判定必须读取该股票在正式 FACTOR
# Snapshot 中的**完整** FactorResult 集合，而不是仅能读取策略评分时保留的
# ``StrategyResult.factor_snapshot``。否则一个获批但非评分用途的因子（如
# Growth 的 ``roe_ttm``）将无法被资格规则取到，迫使实现者替换业务指标。
#
# 本测试用 Growth 复现该缺陷：``roe_ttm`` 在策略评分快照里不存在，只能通过
# ``QualificationContext.factors`` 提供。
#


QUALIFICATION_CONTEXT_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


# 测试专用获批 Growth 绝对规则：roe_ttm 是资格证据，但不是策略评分因子。
_GROWTH_ABSOLUTE_RULE = FactorThresholdRule(
    strategy_id="growth",
    version="v1",
    thresholds={
        "net_profit_parent_yoy": FactorThreshold(min=15.0),
        "revenue_yoy": FactorThreshold(min=5.0),
        "roe_ttm": FactorThreshold(min=8.0),
    },
)


qualifier = GrowthQualifier(
    absolute_rule=_GROWTH_ABSOLUTE_RULE,
    qualification_version="v1",
)


def factor(name: str, value: float) -> FactorResult:
    """构造一个 VALUE 状态的因子证据。"""
    return FactorResult(
        symbol="600000.SH",
        factor=name,
        as_of=QUALIFICATION_CONTEXT_AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def growth_result(
    *,
    rank_percentile: float,
    factor_snapshot: tuple[FactorResult, ...] = (),
) -> StrategyResult:
    """构造 Growth 策略结果；评分快照默认不含 roe_ttm。"""
    return StrategyResult(
        symbol="600000.SH",
        strategy_id="growth",
        strategy_version="v1",
        as_of=QUALIFICATION_CONTEXT_AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=88.0,
        rank_percentile=rank_percentile,
        factor_snapshot=factor_snapshot,
    )


def test_growth_qualification_can_read_non_scoring_roe_factor() -> None:
    """Growth 资格能读取不在评分快照里的 roe_ttm 因子。"""
    context = QualificationContext(
        strategy_result=growth_result(rank_percentile=0.95),
        factors=(
            factor("net_profit_parent_yoy", 20.0),
            factor("revenue_yoy", 8.0),
            factor("roe_ttm", 9.0),
        ),
    )
    qualification = qualifier.qualify(context)
    assert qualification.absolute_pass is True
    assert qualification.qualified is True


def test_strategy_scoring_snapshot_is_not_used_as_qualification_evidence() -> None:
    """评分快照不得被当作资格证据来源。

    ``roe_ttm`` 存在于此处的评分快照里，但不在 ``context.factors`` 中，资格层
    必须基于 ``context.factors`` 判定为缺证据失败，证明两者已分离。
    """
    scoring_snapshot = (
        factor("net_profit_parent_yoy", 20.0),
        factor("revenue_yoy", 8.0),
        factor("roe_ttm", 30.0),
    )
    context = QualificationContext(
        strategy_result=growth_result(
            rank_percentile=0.95,
            factor_snapshot=scoring_snapshot,
        ),
        factors=(
            factor("net_profit_parent_yoy", 20.0),
            factor("revenue_yoy", 8.0),
        ),
    )
    qualification = qualifier.qualify(context)
    assert qualification.absolute_pass is False
    assert any("roe_ttm" in risk for risk in qualification.risks)


def test_qualification_context_defaults_to_no_factors() -> None:
    """``factors`` 默认空集：缺证据即失败关闭。"""
    context = QualificationContext(
        strategy_result=growth_result(rank_percentile=0.95),
    )
    assert context.factors == ()
    qualification = qualifier.qualify(context)
    assert qualification.absolute_pass is False


# ===========================================================================
# 来源：tests/unit/test_eligibility_scanner.py（9 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Eligibility-only scanner tests.
#
# The rule these tests pin down: with weights deferred
# (`docs/STRATEGY_SYSTEM.md` §5), a scanner may say whether a symbol's evidence
# is complete enough to consider, and must not say anything else. No score, no
# percentile, no confidence — each of those would be a number nobody reviewed,
# and a number reads downstream as a judgement.
#


AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


SYMBOL = "600519.SH"


NON_VALUE_STATUSES = (
    DataStatus.NULL,
    DataStatus.STALE,
    DataStatus.INVALID,
    DataStatus.SOURCE_ERROR,
    DataStatus.NOT_APPLICABLE,
)


def _config(**overrides: object) -> StrategyConfig:
    payload: dict[str, object] = {
        "id": "quality",
        "version": "v1",
        "description": "quality",
        "required_factors": ["roe_ttm", "gross_margin"],
    }
    payload.update(overrides)
    return StrategyConfig.model_validate(payload)


def _factor(name: str, status: DataStatus, value: float | None = 1.0) -> FactorResult:
    return FactorResult(
        symbol=SYMBOL,
        factor=name,
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
        unit="%",
    )


def _context(*factors: FactorResult) -> StrategyContext:
    return StrategyContext(symbol=SYMBOL, as_of=AS_OF, factors=tuple(factors))


def test_a_symbol_with_every_required_factor_is_eligible() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE, 17.7),
        _factor("gross_margin", DataStatus.VALUE, 89.5),
    )

    verdict = scanner.eligibility(context)

    assert verdict.eligible is True
    assert verdict.reasons == ()
    assert scanner.required_factors() == {"roe_ttm", "gross_margin"}


def test_the_verdict_never_carries_a_score() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE),
        _factor("gross_margin", DataStatus.VALUE),
    )

    result = scanner.score(context)

    assert result.eligible is True
    assert result.score is None
    assert result.rank_percentile is None
    assert result.confidence is None
    assert result.factor_snapshot == context.factors
    assert result.lineage.strategy_version == "v1"


def test_a_missing_factor_makes_the_symbol_ineligible_and_says_which() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(_factor("roe_ttm", DataStatus.VALUE))

    result = scanner.score(context)

    assert result.eligible is False
    assert "gross_margin was not computed for this symbol" in result.risks


def test_any_status_other_than_value_is_not_eligible() -> None:
    """六个状态保持可区分；除 VALUE 外都不算证据。"""
    wrong = []
    for status in NON_VALUE_STATUSES:
        scanner = EligibilityScanner(_config())
        context = _context(
            _factor("roe_ttm", DataStatus.VALUE),
            _factor("gross_margin", status, value=None),
        )
        result = scanner.score(context)
        if (
            result.eligible is not False
            or f"gross_margin is {status}, not VALUE" not in result.risks
        ):
            wrong.append(
                f"{status}: eligible={result.eligible!r} risks={result.risks!r}"
            )
    assert not wrong, "非 VALUE 状态不应算证据:\n" + "\n".join(wrong)


def test_a_population_gets_one_verdict_each_and_no_ranking() -> None:
    scanner = EligibilityScanner(_config())
    contexts = (
        _context(
            _factor("roe_ttm", DataStatus.VALUE),
            _factor("gross_margin", DataStatus.VALUE),
        ),
        _context(_factor("roe_ttm", DataStatus.VALUE)),
    )

    results = scanner.score_cross_section(contexts)

    assert len(results) == 2
    assert [result.eligible for result in results] == [True, False]
    assert all(result.rank_percentile is None for result in results)


def test_the_explanation_states_that_scoring_is_deferred() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE),
        _factor("gross_margin", DataStatus.VALUE),
    )

    explanation = scanner.explain(scanner.score(context))

    assert "no score" in explanation.summary
    assert "not been reviewed" in explanation.summary
    assert {item.factor for item in explanation.factors} == {"roe_ttm", "gross_margin"}


def test_a_scanner_must_declare_what_it_requires() -> None:
    with pytest.raises(ValueError, match="must declare required_factors"):
        EligibilityScanner(_config(required_factors=[]))


def test_a_configured_scanner_with_weights_is_refused_here() -> None:
    """Weights mean a scoring implementation belongs, not this one."""
    with pytest.raises(ValueError, match="does not score"):
        EligibilityScanner(
            _config(required_factors=["roe_ttm"], weights={"roe_ttm": 1.0})
        )


def test_the_result_carries_the_configured_identity() -> None:
    """A verdict must name the scanner and version that produced it."""
    scanner = EligibilityScanner(_config(id="growth", version="v2"))
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE),
        _factor("gross_margin", DataStatus.VALUE),
    )

    result = scanner.score(context)

    assert result.strategy_id == "growth"
    assert result.strategy_version == "v2"
    assert result.as_of == AS_OF
    assert result.symbol == SYMBOL
