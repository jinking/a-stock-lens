"""候选横截面代表性选择策略单元测试。"""

from datetime import UTC, datetime

import pytest

from astock_lens.candidates.policy import (
    CandidateEvidence,
    CandidateEvidenceIncomplete,
    CandidatePolicy,
    CandidateSelection,
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
    ev1 = _make_evidence("600001.SH", rank_percentile=0.99, market_validation=MarketValidation.CONTRADICTED)
    ev2 = _make_evidence("600002.SH", rank_percentile=0.91, market_validation=MarketValidation.CONFIRMED)
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
