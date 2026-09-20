"""QualificationContext 单元测试：分离策略评分证据与绝对资格证据。

设计目标（见 2026-09-20 规格 §4）：资格判定必须读取该股票在正式 FACTOR
Snapshot 中的**完整** FactorResult 集合，而不是仅能读取策略评分时保留的
``StrategyResult.factor_snapshot``。否则一个获批但非评分用途的因子（如
Growth 的 ``roe_ttm``）将无法被资格规则取到，迫使实现者替换业务指标。

本测试用 Growth 复现该缺陷：``roe_ttm`` 在策略评分快照里不存在，只能通过
``QualificationContext.factors`` 提供。
"""

from datetime import UTC, datetime

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.growth import GrowthQualifier
from astock_lens.qualifications.models import QualificationContext
from astock_lens.qualifications.rules import FactorThreshold, FactorThresholdRule
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)

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
        as_of=AS_OF,
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
        as_of=AS_OF,
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


def test_missing_approved_qualification_factor_fails_closed() -> None:
    """缺少获批资格因子时必须失败关闭，而不是静默通过。"""
    context = QualificationContext(
        strategy_result=growth_result(rank_percentile=0.95),
        factors=(
            factor("net_profit_parent_yoy", 20.0),
            factor("revenue_yoy", 8.0),
        ),
    )
    qualification = qualifier.qualify(context)
    assert qualification.absolute_pass is False
    assert any("roe_ttm" in risk for risk in qualification.risks)


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
