"""End-to-end integration test for Market Regime, Market Validation, and Signal pipeline."""

from datetime import datetime
from zoneinfo import ZoneInfo

from astock_lens.candidates.policy import RepresentativeCandidatePolicy
from astock_lens.domain.enums import DataStatus, MarketRegime, MarketValidation, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines.stages import (
    candidate_stage,
    market_regime_stage,
    market_validation_stage,
    signal_stage,
)
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SHANGHAI)


def _fr(symbol: str, factor: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=AS_OF,
        status=DataStatus.VALUE,
        raw_value=value,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
    )


def test_market_signal_pipeline_end_to_end_assembly() -> None:
    """端到端验证：市场环境判定 -> 5维市场验证 (一票否决) -> 信号检测 -> Candidate 闭环生成。"""
    # 1. 构造标的因子
    # 标的 A (300741.SZ): 极端动量突破样本，流动性充沛，趋势优良 -> CONFIRMED + BREAKOUT -> 入选 Candidate
    # 标的 B (688525.SH): 成长策略，但严重破位大跌 (20日跌-20%, 60日跌-35%) -> CONTRADICTED + BREAKDOWN -> 一票否决
    # 标的 C (000526.SZ): 流动性不足 (0.8亿 < 1.0亿) -> CONTRADICTED -> 一票否决
    factors = (
        # 300741.SZ
        _fr("300741.SZ", "avg_amount_20d", 400_000_000.0),
        _fr("300741.SZ", "ret_20d", 0.35),
        _fr("300741.SZ", "ret_60d", 0.50),
        _fr("300741.SZ", "proximity_52w_high", 0.98),
        # 688525.SH
        _fr("688525.SH", "avg_amount_20d", 300_000_000.0),
        _fr("688525.SH", "ret_20d", -0.20),
        _fr("688525.SH", "ret_60d", -0.35),
        _fr("688525.SH", "proximity_52w_high", 0.50),
        # 000526.SZ
        _fr("000526.SZ", "avg_amount_20d", 80_000_000.0),
        _fr("000526.SZ", "ret_20d", 0.05),
        _fr("000526.SZ", "ret_60d", 0.10),
        _fr("000526.SZ", "proximity_52w_high", 0.88),
    )

    symbols = ["300741.SZ", "688525.SH", "000526.SZ"]

    strategy_results = (
        StrategyResult(
            symbol="300741.SZ",
            strategy_id="momentum",
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            score=0.95,
            rank_percentile=0.98,
            lineage=SnapshotLineage(strategy_version="v1"),
        ),
        StrategyResult(
            symbol="688525.SH",
            strategy_id="growth",
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            score=0.92,
            rank_percentile=0.95,
            lineage=SnapshotLineage(strategy_version="v1"),
        ),
        StrategyResult(
            symbol="000526.SZ",
            strategy_id="momentum",
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            score=0.88,
            rank_percentile=0.91,
            lineage=SnapshotLineage(strategy_version="v1"),
        ),
    )

    qualifications = (
        StrategyQualification(
            symbol="300741.SZ",
            strategy_id="momentum",
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=0.98,
        ),
        StrategyQualification(
            symbol="688525.SH",
            strategy_id="growth",
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=0.95,
        ),
        StrategyQualification(
            symbol="000526.SZ",
            strategy_id="momentum",
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=0.91,
        ),
    )

    # 1. 运行市场环境阶段
    regime_res = market_regime_stage(
        as_of=AS_OF,
        breadth_ratio=0.62,
        index_trend=0.03,
    )
    assert regime_res.regime == MarketRegime.BULL

    # 2. 运行市场验证阶段（提供完整的5维证据）
    validation_results = market_validation_stage(
        symbols=symbols,
        factor_results=factors,
        as_of=AS_OF,
        strategy_by_symbol={s: "momentum" for s in symbols},
        vol_ratio_by_symbol={
            "300741.SZ": 1.5,
            "688525.SH": 0.6,
            "000526.SZ": 1.0,
        },
        industry_excess_by_symbol={
            "300741.SZ": 0.15,
            "688525.SH": -0.15,
            "000526.SZ": 0.01,
        },
        relative_strength_by_symbol={
            "300741.SZ": 0.20,
            "688525.SH": -0.25,
            "000526.SZ": 0.05,
        },
    )
    assert len(validation_results) == 3
    mv_map = {r.symbol: r.status for r in validation_results}
    assert mv_map["300741.SZ"] == MarketValidation.CONFIRMED
    assert mv_map["688525.SH"] == MarketValidation.CONTRADICTED  # 破位负向 >= 2
    assert mv_map["000526.SZ"] == MarketValidation.CONTRADICTED  # 流动性警戒线一票否决

    # 3. 运行技术信号阶段
    signal_results = signal_stage(
        symbols=symbols,
        factor_results=factors,
        as_of=AS_OF,
        strategy_by_symbol={s: "momentum" for s in symbols},
        market_regime=regime_res.regime,
    )
    assert len(signal_results) == 3
    sig_map = {r.symbol: r.signal for r in signal_results}
    assert sig_map["300741.SZ"] == Signal.BREAKOUT
    assert sig_map["688525.SH"] == Signal.BREAKDOWN

    # 4. 运行 Candidate 装配阶段 (搭配真实 RepresentativeCandidatePolicy)
    policy = RepresentativeCandidatePolicy(
        version="v1", soft_reserve_per_strategy=1, max_candidates=10
    )
    lineage = SnapshotLineage(
        factor_version="v1",
        strategy_version="v1",
        qualification_version="v1",
        regime_version="v1",
        signal_version="v1",
        candidate_policy_version="v1",
    )

    candidates = candidate_stage(
        strategy_results=strategy_results,
        qualifications=qualifications,
        market_validation_by_symbol=mv_map,
        signal_by_symbol=sig_map,
        lineage=lineage,
        as_of=AS_OF,
        policy=policy,
    )

    # 验证候选结果：只有 300741.SZ 通过验证进入候选集，其余被 CONTRADICTED 一票否决
    assert len(candidates) == 1
    c = candidates[0]
    assert c.symbol == "300741.SZ"
    assert c.market_validation == MarketValidation.CONFIRMED
    assert c.signal == Signal.BREAKOUT
    assert c.lineage.regime_versions() == frozenset({"v1"})
    assert c.lineage.signal_versions() == frozenset({"v1"})
