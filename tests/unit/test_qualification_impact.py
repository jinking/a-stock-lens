"""资格影响审计单元测试：计数独立性与失败原因聚合。"""

from datetime import UTC, datetime

import pytest

from astock_lens.calibration.qualification_impact import (
    QualificationImpactUnsupportedQualifier,
    build_qualification_impact,
)
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.growth import GrowthQualifier
from astock_lens.qualifications.models import (
    QualificationContext,
    StrategyQualification,
)
from astock_lens.qualifications.rules import FactorThreshold, FactorThresholdRule
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)

QUALIFIERS = {
    "growth": GrowthQualifier(
        absolute_rule=FactorThresholdRule(
            strategy_id="growth",
            version="v1",
            thresholds={
                "net_profit_parent_yoy": FactorThreshold(min=15.0),
                "revenue_yoy": FactorThreshold(min=5.0),
                "roe_ttm": FactorThreshold(min=8.0),
            },
        ),
        qualification_version="v1",
    )
}


def _factor(symbol: str, name: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _result(symbol: str, *, rank_percentile: float = 0.95) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id="growth",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=90.0,
        rank_percentile=rank_percentile,
    )


def _four_shapes_fixture() -> tuple[
    tuple[StrategyResult, ...], tuple[FactorResult, ...]
]:
    """双通过 / 绝对通过但低于 top10 / 绝对失败但 top10 / 缺因子。"""
    strategy_results = (
        _result("000001.SZ"),  # 双通过
        _result("000002.SZ", rank_percentile=0.50),  # 绝对通过 + 低于 top10
        _result("000003.SZ"),  # 绝对失败（净利 10 < 15）+ top10
        _result("000004.SZ"),  # 缺 roe_ttm → 绝对失败 + top10
    )
    factor_results = (
        _factor("000001.SZ", "net_profit_parent_yoy", 20.0),
        _factor("000001.SZ", "revenue_yoy", 8.0),
        _factor("000001.SZ", "roe_ttm", 9.0),
        _factor("000002.SZ", "net_profit_parent_yoy", 20.0),
        _factor("000002.SZ", "revenue_yoy", 8.0),
        _factor("000002.SZ", "roe_ttm", 9.0),
        _factor("000003.SZ", "net_profit_parent_yoy", 10.0),
        _factor("000003.SZ", "revenue_yoy", 8.0),
        _factor("000003.SZ", "roe_ttm", 9.0),
        _factor("000004.SZ", "net_profit_parent_yoy", 20.0),
        _factor("000004.SZ", "revenue_yoy", 8.0),
        # 000004.SZ 刻意缺 roe_ttm
    )
    return strategy_results, factor_results


def test_counts_are_computed_independently() -> None:
    strategy_results, factor_results = _four_shapes_fixture()
    report = build_qualification_impact(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers=QUALIFIERS,
        as_of=AS_OF,
    )

    assert len(report.strategies) == 1
    impact = report.strategies[0]
    assert impact.strategy_id == "growth"
    assert impact.strategy_eligible_count == 4
    assert impact.ranked_count == 4
    assert impact.top_ten_count == 3
    assert impact.absolute_pass_count == 2
    assert impact.dual_pass_count == 1
    assert impact.qualified_symbols == ("000001.SZ",)


def test_failure_reasons_aggregate_by_factor() -> None:
    strategy_results = (
        _result("000001.SZ"),
        _result("000002.SZ"),
    )
    factor_results = (
        # 两个 symbol 都栽在同一因子（净利同比 < 15）
        _factor("000001.SZ", "net_profit_parent_yoy", 10.0),
        _factor("000001.SZ", "revenue_yoy", 8.0),
        _factor("000001.SZ", "roe_ttm", 9.0),
        _factor("000002.SZ", "net_profit_parent_yoy", 12.0),
        _factor("000002.SZ", "revenue_yoy", 8.0),
        _factor("000002.SZ", "roe_ttm", 9.0),
    )
    report = build_qualification_impact(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers=QUALIFIERS,
        as_of=AS_OF,
    )
    impact = report.strategies[0]
    assert impact.failure_reasons == (("net_profit_parent_yoy", 2),)
    assert impact.dual_pass_count == 0
    assert impact.qualified_symbols == ()


def test_boundary_samples_are_deterministic() -> None:
    strategy_results, factor_results = _four_shapes_fixture()
    report = build_qualification_impact(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers=QUALIFIERS,
        as_of=AS_OF,
    )
    impact = report.strategies[0]
    # 唯一双通过样本。
    assert impact.closest_dual_pass_symbols == ("000001.SZ",)
    # 两个绝对失败样本：000003.SZ 的 margin 更小（roe 9 贴近 8），故排在前；
    # 000004.SZ 缺 roe 时该边界不产生 margin，仍由其可用因子得出 margin，故入列。
    assert impact.closest_absolute_fail_symbols == ("000003.SZ", "000004.SZ")


class _ProtocolOnlyQualifier:
    """只满足公开 ``StrategyQualifier`` 协议，不暴露 ``absolute_rule``。"""

    strategy_id = "growth"
    qualification_version = "v1"

    def qualify(self, context: QualificationContext) -> StrategyQualification:
        return StrategyQualification(
            symbol=context.strategy_result.symbol,
            strategy_id=self.strategy_id,
            strategy_version=context.strategy_result.strategy_version,
            qualification_version=self.qualification_version,
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=context.strategy_result.rank_percentile,
        )


class _RawRiskQualifier:
    """qualify 产出一条不含 ``factor '<name>'`` 的 risk（模拟文案变形）。"""

    strategy_id = "growth"
    qualification_version = "v1"

    def __init__(self) -> None:
        self.absolute_rule = FactorThresholdRule(
            strategy_id="growth",
            version="v1",
            thresholds={"net_profit_parent_yoy": FactorThreshold(min=15.0)},
        )

    def qualify(self, context: QualificationContext) -> StrategyQualification:
        return StrategyQualification(
            symbol=context.strategy_result.symbol,
            strategy_id=self.strategy_id,
            strategy_version=context.strategy_result.strategy_version,
            qualification_version=self.qualification_version,
            qualified=False,
            percentile_pass=True,
            absolute_pass=False,
            rank_percentile=context.strategy_result.rank_percentile,
            risks=("absolute quality not met",),
        )


def test_qualifier_without_absolute_rule_fails_loudly() -> None:
    """M1：只满足公开协议的 qualifier 必须抛具名异常，而不是裸 AttributeError。"""
    strategy_results = (_result("000001.SZ"),)
    factor_results = (
        _factor("000001.SZ", "net_profit_parent_yoy", 20.0),
        _factor("000001.SZ", "revenue_yoy", 8.0),
        _factor("000001.SZ", "roe_ttm", 9.0),
    )
    with pytest.raises(QualificationImpactUnsupportedQualifier) as excinfo:
        build_qualification_impact(
            factor_results=factor_results,
            strategy_results=strategy_results,
            qualifiers={"growth": _ProtocolOnlyQualifier()},
            as_of=AS_OF,
        )
    message = str(excinfo.value)
    # 不是 AttributeError（pytest.raises 已限定类型）；消息点名 strategy_id 与类型。
    assert "growth" in message
    assert "_ProtocolOnlyQualifier" in message


def test_unrecognized_risk_text_is_not_dropped() -> None:
    """M2：抠不出因子名的 risk 必须以原文出现在 failure_reasons（不得静默丢弃）。"""
    strategy_results = (_result("000001.SZ"),)
    factor_results = (_factor("000001.SZ", "net_profit_parent_yoy", 20.0),)
    report = build_qualification_impact(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers={"growth": _RawRiskQualifier()},
        as_of=AS_OF,
    )
    impact = report.strategies[0]
    assert ("absolute quality not met", 1) in impact.failure_reasons
    assert impact.dual_pass_count == 0
