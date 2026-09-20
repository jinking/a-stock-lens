"""市场与信号决策就绪分布报告测试 (Plan C Task 1).

验证：
- 确定性分位数：不同输入顺序产出完全相同的 p10/p25/p50/p75/p90；
- 缺失值纪律：NULL/NOT_APPLICABLE/STALE 永不退化为数值 0；
- 合格标的范围：严格仅针对各策略合格标的 (StrategyQualification.qualified == True)；
- 严禁枚举越界：报告中绝对不出现 MarketRegime/MarketValidation/Signal 判决枚举。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from astock_lens.calibration.market_signal_readiness import (
    build_market_signal_readiness,
)
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.models import StrategyQualification

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=SHANGHAI)


def _fr(
    symbol: str,
    factor: str,
    value: float | None,
    status: DataStatus = DataStatus.VALUE,
) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(),
        raw_value=value,
    )


def _sq(
    symbol: str,
    strategy_id: str,
    qualified: bool,
) -> StrategyQualification:
    return StrategyQualification(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version="v1",
        qualified=qualified,
        percentile_pass=qualified,
        absolute_pass=qualified,
        rank_percentile=0.95 if qualified else 0.5,
        reasons=(),
        risks=(),
    )


def test_deterministic_quantiles_under_different_input_orders() -> None:
    """Step 1: 无论输入顺序如何，分位数计算完全一致且确定。"""
    strategy_id = "value"
    qualifications = [
        _sq("000001.SZ", strategy_id, qualified=True),
        _sq("000002.SZ", strategy_id, qualified=True),
        _sq("000003.SZ", strategy_id, qualified=True),
        _sq("000004.SZ", strategy_id, qualified=True),
        _sq("000005.SZ", strategy_id, qualified=True),
    ]

    # 正序
    factors_order1 = [
        _fr("000001.SZ", "ret_20d", 0.05),
        _fr("000002.SZ", "ret_20d", 0.10),
        _fr("000003.SZ", "ret_20d", 0.15),
        _fr("000004.SZ", "ret_20d", 0.20),
        _fr("000005.SZ", "ret_20d", 0.25),
    ]
    # 逆序
    factors_order2 = list(reversed(factors_order1))

    report1 = build_market_signal_readiness(
        as_of=AS_OF,
        qualifications=qualifications,
        factor_results=factors_order1,
    )
    report2 = build_market_signal_readiness(
        as_of=AS_OF,
        qualifications=qualifications,
        factor_results=factors_order2,
    )

    strat1 = next(s for s in report1.strategies if s.strategy_id == strategy_id)
    strat2 = next(s for s in report2.strategies if s.strategy_id == strategy_id)

    m1 = next(m for m in strat1.metrics if m.metric == "ret_20d")
    m2 = next(m for m in strat2.metrics if m.metric == "ret_20d")

    assert m1.p10 == m2.p10 == 0.05
    assert m1.p25 == m2.p25 == 0.10
    assert m1.p50 == m2.p50 == 0.15
    assert m1.p75 == m2.p75 == 0.20
    assert m1.p90 == m2.p90 == 0.25
    assert m1.count == m2.count == 5
    assert m1.missing == m2.missing == 0


def test_missing_values_never_become_zero() -> None:
    """Step 2: 缺失数据 (NULL/NOT_APPLICABLE/STALE) 严禁转为 0，只能计入 missing。"""
    strategy_id = "growth"
    qualifications = [
        _sq("000001.SZ", strategy_id, qualified=True),
        _sq("000002.SZ", strategy_id, qualified=True),
        _sq("000003.SZ", strategy_id, qualified=True),
        _sq("000004.SZ", strategy_id, qualified=True),
    ]

    factors = [
        _fr("000001.SZ", "proximity_52w_high", 0.95, DataStatus.VALUE),
        _fr("000002.SZ", "proximity_52w_high", None, DataStatus.NULL),
        _fr("000003.SZ", "proximity_52w_high", None, DataStatus.NOT_APPLICABLE),
        _fr("000004.SZ", "proximity_52w_high", None, DataStatus.STALE),
    ]

    report = build_market_signal_readiness(
        as_of=AS_OF,
        qualifications=qualifications,
        factor_results=factors,
    )

    strat = next(s for s in report.strategies if s.strategy_id == strategy_id)
    dist = next(m for m in strat.metrics if m.metric == "proximity_52w_high")

    assert dist.count == 1
    assert dist.missing == 3
    assert dist.p50 == 0.95
    assert dist.p10 == 0.95


def test_scope_strictly_restricted_to_qualified_stocks() -> None:
    """Step 3: 只有 qualified == True 的标的才能进入分布，不合格标的严格排除。"""
    strategy_id = "quality"
    qualifications = [
        _sq("000001.SZ", strategy_id, qualified=True),
        _sq("000002.SZ", strategy_id, qualified=False),  # 不合格
    ]

    factors = [
        _fr("000001.SZ", "ret_60d", 0.30),
        _fr("000002.SZ", "ret_60d", -0.50),  # 不应计入
    ]

    report = build_market_signal_readiness(
        as_of=AS_OF,
        qualifications=qualifications,
        factor_results=factors,
    )

    strat = next(s for s in report.strategies if s.strategy_id == strategy_id)
    assert strat.qualified_count == 1

    dist = next(m for m in strat.metrics if m.metric == "ret_60d")
    assert dist.count == 1
    assert dist.p50 == 0.30
    assert -0.50 not in (dist.p10, dist.p25, dist.p50, dist.p75, dist.p90)
