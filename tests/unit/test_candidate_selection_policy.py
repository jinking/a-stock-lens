"""候选横截面代表性选择策略单元测试。"""

from datetime import UTC, datetime

import pytest

from astock_lens.candidates.policy import (
    CandidateEvidence,
    CandidateEvidenceIncomplete,
    CandidatePolicy,
    RepresentativeCandidatePolicy,
)
from astock_lens.domain.enums import MarketValidation, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _make_evidence(
    symbol: str,
    *,
    strategy_id: str = "value",
    rank_percentile: float = 0.95,
    qualified: bool = True,
    market_validation: MarketValidation | None = MarketValidation.CONFIRMED,
    signal: Signal | None = Signal.NO_SIGNAL,
    qualifications: tuple[StrategyQualification, ...] | None = None,
    results: tuple[StrategyResult, ...] | None = None,
) -> CandidateEvidence:
    if qualifications is None:
        qualifications = (
            StrategyQualification(
                symbol=symbol,
                strategy_id=strategy_id,
                strategy_version="v1",
                qualification_version="v1",
                qualified=qualified,
                percentile_pass=rank_percentile >= 0.90,
                absolute_pass=qualified,
                rank_percentile=rank_percentile,
                reasons=("passed",) if qualified else (),
                risks=() if qualified else ("failed",),
            ),
        )
    if results is None:
        results = (
            StrategyResult(
                symbol=symbol,
                strategy_id=strategy_id,
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=80.0,
                rank_percentile=rank_percentile,
            ),
        )
    return CandidateEvidence(
        symbol=symbol,
        strategy_results=results,
        strategy_qualifications=qualifications,
        market_validation=market_validation,
        signal=signal,
    )


def _make_evidence_batch(count: int, prefix: str = "600") -> list[CandidateEvidence]:
    items: list[CandidateEvidence] = []
    for i in range(count):
        sym = f"{prefix}{i:03d}.SH"
        pct = 0.90 + (0.09 * (count - i) / max(count, 1))
        items.append(_make_evidence(sym, rank_percentile=pct))
    return items


def test_selection_never_exceeds_fifty_symbols() -> None:
    policy: CandidatePolicy = RepresentativeCandidatePolicy()
    evidence_pool = _make_evidence_batch(80)
    selected = policy.select(evidence_pool)
    assert len(selected) == 50


def test_selection_does_not_fill_to_twenty() -> None:
    policy: CandidatePolicy = RepresentativeCandidatePolicy()
    evidence_pool = _make_evidence_batch(12)
    selected = policy.select(evidence_pool)
    assert len(selected) == 12


def test_contradicted_market_validation_is_vetoed() -> None:
    policy: CandidatePolicy = RepresentativeCandidatePolicy()
    ev1 = _make_evidence(
        "600001.SH",
        rank_percentile=0.99,
        market_validation=MarketValidation.CONTRADICTED,
    )
    ev2 = _make_evidence(
        "600002.SH", rank_percentile=0.91, market_validation=MarketValidation.CONFIRMED
    )
    selected = policy.select([ev1, ev2])
    symbols = [s.symbol for s in selected]
    assert "600001.SH" not in symbols
    assert "600002.SH" in symbols


def test_symbol_uniqueness_for_multi_strategy_qualification() -> None:
    policy: CandidatePolicy = RepresentativeCandidatePolicy()
    sym = "600001.SH"
    q_val = StrategyQualification(
        symbol=sym,
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.98,
    )
    q_gro = StrategyQualification(
        symbol=sym,
        strategy_id="growth",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.97,
    )
    res_val = StrategyResult(
        symbol=sym,
        strategy_id="value",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=90.0,
        rank_percentile=0.98,
    )
    res_gro = StrategyResult(
        symbol=sym,
        strategy_id="growth",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=89.0,
        rank_percentile=0.97,
    )
    multi_ev = CandidateEvidence(
        symbol=sym,
        strategy_results=(res_val, res_gro),
        strategy_qualifications=(q_val, q_gro),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    selected = policy.select([multi_ev])
    assert len(selected) == 1
    assert selected[0].symbol == sym


def test_missing_market_validation_or_signal_raises_incomplete() -> None:
    policy: CandidatePolicy = RepresentativeCandidatePolicy()
    ev_no_mv = _make_evidence("600001.SH", market_validation=None)
    with pytest.raises(CandidateEvidenceIncomplete):
        policy.select([ev_no_mv])

    ev_no_sig = _make_evidence("600002.SH", signal=None)
    with pytest.raises(CandidateEvidenceIncomplete):
        policy.select([ev_no_sig])


def test_strategy_with_fewer_than_three_qualified_contributes_available_only() -> None:
    policy = RepresentativeCandidatePolicy(soft_reserve_per_strategy=3)
    ev_single = _make_evidence(
        "600001.SH", strategy_id="momentum", rank_percentile=0.91
    )
    selected = policy.select([ev_single])
    assert len(selected) == 1
    assert selected[0].symbol == "600001.SH"


def test_best_single_strategy_percentile_beats_multi_strategy_match() -> None:
    policy = RepresentativeCandidatePolicy()
    # ev_high has 0.99 in single strategy
    ev_high = _make_evidence("600001.SH", strategy_id="value", rank_percentile=0.99)
    # ev_multi has 0.95 across two strategies
    q1 = StrategyQualification(
        symbol="600002.SH",
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    q2 = StrategyQualification(
        symbol="600002.SH",
        strategy_id="growth",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    r1 = StrategyResult(
        symbol="600002.SH",
        strategy_id="value",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=85.0,
        rank_percentile=0.95,
    )
    r2 = StrategyResult(
        symbol="600002.SH",
        strategy_id="growth",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=85.0,
        rank_percentile=0.95,
    )
    ev_multi = CandidateEvidence(
        symbol="600002.SH",
        strategy_results=(r1, r2),
        strategy_qualifications=(q1, q2),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    selected = policy.select([ev_multi, ev_high])
    assert [s.symbol for s in selected] == ["600001.SH", "600002.SH"]


def test_equal_percentile_uses_qualified_strategy_count_as_second_key() -> None:
    policy = RepresentativeCandidatePolicy()
    ev_single = _make_evidence("600001.SH", strategy_id="value", rank_percentile=0.95)
    q1 = StrategyQualification(
        symbol="600002.SH",
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    q2 = StrategyQualification(
        symbol="600002.SH",
        strategy_id="growth",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    r1 = StrategyResult(
        symbol="600002.SH",
        strategy_id="value",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=85.0,
        rank_percentile=0.95,
    )
    r2 = StrategyResult(
        symbol="600002.SH",
        strategy_id="growth",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=85.0,
        rank_percentile=0.95,
    )
    ev_multi = CandidateEvidence(
        symbol="600002.SH",
        strategy_results=(r1, r2),
        strategy_qualifications=(q1, q2),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    selected = policy.select([ev_single, ev_multi])
    # ev_multi has 2 qualified strategies vs 1 for ev_single
    assert [s.symbol for s in selected] == ["600002.SH", "600001.SH"]


def test_equal_percentile_and_strategy_count_uses_confirmed_before_neutral() -> None:
    policy = RepresentativeCandidatePolicy()
    ev_neutral = _make_evidence(
        "600001.SH", rank_percentile=0.95, market_validation=MarketValidation.NEUTRAL
    )
    ev_confirmed = _make_evidence(
        "600002.SH", rank_percentile=0.95, market_validation=MarketValidation.CONFIRMED
    )
    selected = policy.select([ev_neutral, ev_confirmed])
    assert [s.symbol for s in selected] == ["600002.SH", "600001.SH"]


def test_final_ties_are_symbol_deterministic() -> None:
    policy = RepresentativeCandidatePolicy()
    ev_b = _make_evidence("600002.SH", rank_percentile=0.95)
    ev_a = _make_evidence("600001.SH", rank_percentile=0.95)
    selected = policy.select([ev_b, ev_a])
    assert [s.symbol for s in selected] == ["600001.SH", "600002.SH"]


def test_breakdown_signal_is_vetoed_under_approved_decision_d1() -> None:
    """根据所有者批准决策 D1：BREAKDOWN 严重破位信号触发一票否决，直接拦截不发布。"""
    policy = RepresentativeCandidatePolicy()
    ev_breakdown = _make_evidence(
        "600001.SH",
        rank_percentile=0.99,
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.BREAKDOWN,
    )
    ev_normal = _make_evidence(
        "600002.SH",
        rank_percentile=0.91,
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.BREAKOUT,
    )
    selected = policy.select([ev_breakdown, ev_normal])
    symbols = [s.symbol for s in selected]
    assert "600001.SH" not in symbols
    assert "600002.SH" in symbols


def test_trend_weaken_signal_is_eligible_under_approved_decision_e1() -> None:
    """根据所有者批准决策 E1：TREND_WEAKEN 走弱信号允许入选候选池（由 Builder 标为 WATCH 并预警）。"""
    policy = RepresentativeCandidatePolicy()
    ev_weaken = _make_evidence(
        "600001.SH",
        rank_percentile=0.95,
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.TREND_WEAKEN,
    )
    selected = policy.select([ev_weaken])
    assert len(selected) == 1
    assert selected[0].symbol == "600001.SH"


def test_no_signal_is_eligible_under_approved_decision_f1() -> None:
    """根据所有者批准决策 F1：NO_SIGNAL 无特定形态信号允许作为常规候选入选。"""
    policy = RepresentativeCandidatePolicy()
    ev_no_sig = _make_evidence(
        "600001.SH",
        rank_percentile=0.95,
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    selected = policy.select([ev_no_sig])
    assert len(selected) == 1
    assert selected[0].symbol == "600001.SH"
