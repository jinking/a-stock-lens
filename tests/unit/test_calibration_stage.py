"""校准阶段（因子分布、资格影响）长尾用例。

本文件由 Task 12「文件合并」把以下 2 个同域小文件整体搬入：
    - tests/unit/test_calibration_factor_distribution.py（7 例）
    - tests/unit/test_qualification_impact.py（5 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

import json
from datetime import UTC, datetime

import pytest

from astock_lens.calibration.candidate_report import (
    IndustryCoverageUnavailable,
    generate_calibration_report,
)
from astock_lens.calibration.factor_distribution import (
    CalibrationPopulation,
    boundary_samples,
    factor_distributions,
)
from astock_lens.calibration.qualification_impact import (
    QualificationImpactUnsupportedQualifier,
    build_qualification_impact,
)
from astock_lens.calibration.render import render_json
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.growth import GrowthQualifier
from astock_lens.qualifications.models import (
    QualificationContext,
    StrategyQualification,
)
from astock_lens.qualifications.rules import FactorThreshold, FactorThresholdRule
from astock_lens.strategies.contracts import FactorContribution, StrategyResult

# ===========================================================================
# 来源：tests/unit/test_calibration_factor_distribution.py（7 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 决策级校准证据。
#
# 所有者要批的是六个绝对门槛；能支撑这个决定的东西只有两类：因子在全池的真实分布，
# 以及 0.90 线上下具体是谁、他们的因子值是多少。这些测试钉住三件事——分布只由有值
# 观测算出、样本自带可核对的证据、以及缺行业覆盖时报告必须失败而不是装作完整。
#


AS_OF = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)


def _factor(symbol: str, value: float | None, status: DataStatus) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor="roe_ttm",
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(),
        raw_value=value,
    )


def test_quantiles_come_from_value_observations_only() -> None:
    """NULL/STALE/SOURCE_ERROR 只计数，不进分布——它们不是 0。"""
    results = [
        _factor("a.SZ", 10.0, DataStatus.VALUE),
        _factor("b.SZ", 20.0, DataStatus.VALUE),
        _factor("c.SZ", 30.0, DataStatus.VALUE),
        _factor("d.SZ", 40.0, DataStatus.VALUE),
        _factor("e.SZ", None, DataStatus.NULL),
        _factor("f.SZ", None, DataStatus.STALE),
        _factor("g.SZ", None, DataStatus.SOURCE_ERROR),
    ]

    (distribution,) = factor_distributions(results)

    assert distribution.factor == "roe_ttm"
    assert distribution.value_count == 4
    assert distribution.null_count == 1
    assert distribution.stale_count == 1
    assert distribution.source_error_count == 1
    assert distribution.min_value == 10.0
    assert distribution.max_value == 40.0
    labels = [label for label, _ in distribution.quantiles]
    assert labels == ["p10", "p25", "p50", "p75", "p90", "p95"]
    assert all(10.0 <= value <= 40.0 for _, value in distribution.quantiles), (
        "quantiles must be real observations, not interpolated points"
    )


def test_a_factor_with_no_values_reports_no_quantiles() -> None:
    (distribution,) = factor_distributions([_factor("a.SZ", None, DataStatus.NULL)])

    assert distribution.quantiles == ()
    assert distribution.min_value is None
    assert distribution.value_count == 0
    assert distribution.null_count == 1


def _result(symbol: str, *, percentile: float, score: float) -> StrategyResult:
    snapshot = FactorResult(
        symbol=symbol,
        factor="ret_20d",
        as_of=AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(),
        raw_value=0.11,
    )
    return StrategyResult(
        symbol=symbol,
        strategy_id="momentum",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(),
        score=score,
        rank_percentile=percentile,
        factor_snapshot=(snapshot,),
        contributions=(
            FactorContribution(
                factor="ret_20d", percentile=1.0, weight=1.0, weighted=0.11
            ),
        ),
    )


def test_samples_carry_score_percentile_and_factor_evidence() -> None:
    results = [
        _result(f"{index:06d}.SZ", percentile=index / 10, score=index * 1.0)
        for index in range(1, 11)
    ]

    samples = boundary_samples(results, strategy_id="momentum", top=2, above=2, below=2)

    assert samples, "a ranked population must produce samples"
    assert samples[0].symbol == "000010.SZ", "head of the ranking comes first"
    head = samples[0]
    assert head.score == 10.0
    assert head.rank_percentile == 1.0
    assert head.factor_values == (("ret_20d", 0.11, "VALUE"),)
    assert all(sample.strategy_id == "momentum" for sample in samples)


def _population() -> CalibrationPopulation:
    return CalibrationPopulation(
        broad_listing_count=5565,
        prefilter_count=4800,
        research_count=2500,
        research_ratio=round(2500 / 5565, 4),
        universe_config_digest="372591c1e388",
        min_average_turnover_20d=20_000_000.0,
        min_listing_days=120,
        factor_versions=(("roe_ttm", "v1"),),
        strategy_versions=(("momentum", "v1"),),
    )


def _report():
    results = [
        _result(f"{index:06d}.SZ", percentile=index / 10, score=index * 1.0)
        for index in range(1, 11)
    ]
    return generate_calibration_report(
        as_of=AS_OF,
        strategy_results=results,
        factor_results=[row for r in results for row in r.factor_snapshot],
        industry_map={f"{index:06d}.SZ": "股份制银行Ⅱ" for index in range(1, 11)},
        population=_population(),
    )


def test_the_report_records_the_population_it_was_computed_on() -> None:
    report = _report()

    assert report.population is not None
    assert report.population.research_count == 2500
    assert report.population.min_average_turnover_20d == 20_000_000.0
    assert report.population.min_listing_days == 120
    assert dict(report.population.strategy_versions) == {"momentum": "v1"}
    assert report.factor_distributions, "distributions must be part of the report"


def test_the_boundary_reports_rank_and_score_as_two_separate_numbers() -> None:
    report = _report()
    (strategy,) = report.strategies

    # The boundary is the weakest member of the Top 10%, not the strongest: it is
    # the symbol whose exclusion a tightened rule would move first.
    assert strategy.boundary_rank_percentile == 0.9
    assert strategy.boundary_strategy_score == 9.0


def test_a_decision_grade_report_refuses_incomplete_industry_coverage() -> None:
    results = [_result("000001.SZ", percentile=0.95, score=9.0)]

    with pytest.raises(IndustryCoverageUnavailable, match="industry coverage"):
        generate_calibration_report(
            as_of=AS_OF,
            strategy_results=results,
            factor_results=[row for r in results for row in r.factor_snapshot],
            industry_map={"600519.SH": "白酒Ⅱ"},
            require_full_industry_coverage=True,
        )


def test_rendering_is_byte_stable_under_shuffled_input() -> None:
    """同一份证据无论输入顺序如何，渲染结果必须逐字节相同。"""
    results = [
        _result(f"{index:06d}.SZ", percentile=index / 10, score=index * 1.0)
        for index in range(1, 11)
    ]
    industry_map = {f"{index:06d}.SZ": "股份制银行Ⅱ" for index in range(1, 11)}
    factors = [row for r in results for row in r.factor_snapshot]

    first = render_json(
        generate_calibration_report(
            as_of=AS_OF,
            strategy_results=results,
            factor_results=factors,
            industry_map=industry_map,
        )
    )
    second = render_json(
        generate_calibration_report(
            as_of=AS_OF,
            strategy_results=list(reversed(results)),
            factor_results=list(reversed(factors)),
            industry_map=dict(reversed(list(industry_map.items()))),
        )
    )

    assert json.loads(first) == json.loads(second)
    assert first == second


# ===========================================================================
# 来源：tests/unit/test_qualification_impact.py（5 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


QUALIFICATION_IMPACT_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


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


def _qi_factor(symbol: str, name: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=QUALIFICATION_IMPACT_AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _qi_result(symbol: str, *, rank_percentile: float = 0.95) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id="growth",
        strategy_version="v1",
        as_of=QUALIFICATION_IMPACT_AS_OF,
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
        _qi_result("000001.SZ"),  # 双通过
        _qi_result("000002.SZ", rank_percentile=0.50),  # 绝对通过 + 低于 top10
        _qi_result("000003.SZ"),  # 绝对失败（净利 10 < 15）+ top10
        _qi_result("000004.SZ"),  # 缺 roe_ttm → 绝对失败 + top10
    )
    factor_results = (
        _qi_factor("000001.SZ", "net_profit_parent_yoy", 20.0),
        _qi_factor("000001.SZ", "revenue_yoy", 8.0),
        _qi_factor("000001.SZ", "roe_ttm", 9.0),
        _qi_factor("000002.SZ", "net_profit_parent_yoy", 20.0),
        _qi_factor("000002.SZ", "revenue_yoy", 8.0),
        _qi_factor("000002.SZ", "roe_ttm", 9.0),
        _qi_factor("000003.SZ", "net_profit_parent_yoy", 10.0),
        _qi_factor("000003.SZ", "revenue_yoy", 8.0),
        _qi_factor("000003.SZ", "roe_ttm", 9.0),
        _qi_factor("000004.SZ", "net_profit_parent_yoy", 20.0),
        _qi_factor("000004.SZ", "revenue_yoy", 8.0),
        # 000004.SZ 刻意缺 roe_ttm
    )
    return strategy_results, factor_results


def test_counts_are_computed_independently() -> None:
    strategy_results, factor_results = _four_shapes_fixture()
    report = build_qualification_impact(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers=QUALIFIERS,
        as_of=QUALIFICATION_IMPACT_AS_OF,
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
        _qi_result("000001.SZ"),
        _qi_result("000002.SZ"),
    )
    factor_results = (
        # 两个 symbol 都栽在同一因子（净利同比 < 15）
        _qi_factor("000001.SZ", "net_profit_parent_yoy", 10.0),
        _qi_factor("000001.SZ", "revenue_yoy", 8.0),
        _qi_factor("000001.SZ", "roe_ttm", 9.0),
        _qi_factor("000002.SZ", "net_profit_parent_yoy", 12.0),
        _qi_factor("000002.SZ", "revenue_yoy", 8.0),
        _qi_factor("000002.SZ", "roe_ttm", 9.0),
    )
    report = build_qualification_impact(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers=QUALIFIERS,
        as_of=QUALIFICATION_IMPACT_AS_OF,
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
        as_of=QUALIFICATION_IMPACT_AS_OF,
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
    strategy_results = (_qi_result("000001.SZ"),)
    factor_results = (
        _qi_factor("000001.SZ", "net_profit_parent_yoy", 20.0),
        _qi_factor("000001.SZ", "revenue_yoy", 8.0),
        _qi_factor("000001.SZ", "roe_ttm", 9.0),
    )
    with pytest.raises(QualificationImpactUnsupportedQualifier) as excinfo:
        build_qualification_impact(
            factor_results=factor_results,
            strategy_results=strategy_results,
            qualifiers={"growth": _ProtocolOnlyQualifier()},
            as_of=QUALIFICATION_IMPACT_AS_OF,
        )
    message = str(excinfo.value)
    # 不是 AttributeError（pytest.raises 已限定类型）；消息点名 strategy_id 与类型。
    assert "growth" in message
    assert "_ProtocolOnlyQualifier" in message


def test_unrecognized_risk_text_is_not_dropped() -> None:
    """M2：抠不出因子名的 risk 必须以原文出现在 failure_reasons（不得静默丢弃）。"""
    strategy_results = (_qi_result("000001.SZ"),)
    factor_results = (_qi_factor("000001.SZ", "net_profit_parent_yoy", 20.0),)
    report = build_qualification_impact(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers={"growth": _RawRiskQualifier()},
        as_of=QUALIFICATION_IMPACT_AS_OF,
    )
    impact = report.strategies[0]
    assert ("absolute quality not met", 1) in impact.failure_reasons
    assert impact.dual_pass_count == 0
