"""策略内资格判定单元测试：双门槛（Top 10% + 绝对质量门槛）。"""

from datetime import UTC, datetime

import pytest

from astock_lens.domain.models import SnapshotLineage
from astock_lens.qualifications.contracts import (
    AbsoluteQualificationRule,
    QualificationRuleNotConfigured,
    StrategyQualifier,
)
from astock_lens.qualifications.models import (
    AbsoluteQualificationVerdict,
    StrategyQualification,
)
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


class _AlwaysPassAbsoluteRule:
    version = "rule-v1"

    def evaluate(self, result: StrategyResult) -> AbsoluteQualificationVerdict:
        return AbsoluteQualificationVerdict(passed=True, reasons=("absolute pass",))


class _AlwaysFailAbsoluteRule:
    version = "rule-v1"

    def evaluate(self, result: StrategyResult) -> AbsoluteQualificationVerdict:
        return AbsoluteQualificationVerdict(passed=False, risks=("absolute fail",))


class _DummyQualifier:
    strategy_id = "value"
    qualification_version = "qual-v1"

    def __init__(self, rule: AbsoluteQualificationRule) -> None:
        self.rule = rule

    def qualify(self, result: StrategyResult) -> StrategyQualification:
        from astock_lens.qualifications.common import build_qualification

        return build_qualification(
            result=result,
            expected_strategy_id=self.strategy_id,
            qualification_version=self.qualification_version,
            absolute_rule=self.rule,
        )


def test_percentile_below_top_ten_percent_cannot_qualify() -> None:
    result = _strategy_result(rank_percentile=0.899999)
    qualifier = _DummyQualifier(_AlwaysPassAbsoluteRule())
    qualification = qualifier.qualify(result)
    assert qualification.percentile_pass is False
    assert qualification.absolute_pass is True
    assert qualification.qualified is False


def test_percentile_and_absolute_gate_must_both_pass() -> None:
    result = _strategy_result(rank_percentile=0.90)
    qualifier = _DummyQualifier(_AlwaysPassAbsoluteRule())
    qualification = qualifier.qualify(result)
    assert qualification.percentile_pass is True
    assert qualification.absolute_pass is True
    assert qualification.qualified is True


def test_qualification_version_is_pinned_and_non_empty() -> None:
    result = _strategy_result(rank_percentile=0.92)
    qualifier = _DummyQualifier(_AlwaysPassAbsoluteRule())
    qualification = qualifier.qualify(result)
    assert qualification.qualification_version
    assert len(qualification.qualification_version.strip()) > 0


def test_absolute_failure_blocks_qualification_even_with_high_percentile() -> None:
    result = _strategy_result(rank_percentile=0.99)
    qualifier = _DummyQualifier(_AlwaysFailAbsoluteRule())
    qualification = qualifier.qualify(result)
    assert qualification.percentile_pass is True
    assert qualification.absolute_pass is False
    assert qualification.qualified is False


def test_missing_rank_percentile_raises_value_error() -> None:
    result = _strategy_result(rank_percentile=None)
    qualifier = _DummyQualifier(_AlwaysPassAbsoluteRule())
    with pytest.raises(ValueError, match="rank_percentile"):
        qualifier.qualify(result)
