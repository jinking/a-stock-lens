"""CandidateEvidence 与 CandidateSelection 领域模型测试。"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from astock_lens.candidates.policy import CandidateEvidence, CandidateSelection
from astock_lens.domain.enums import MarketValidation, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _qualification(
    symbol: str,
    strategy_id: str = "value",
    *,
    qualified: bool = True,
    percentile: float = 0.95,
) -> StrategyQualification:
    return StrategyQualification(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version="v1",
        qualified=qualified,
        percentile_pass=percentile >= 0.90,
        absolute_pass=qualified,
        rank_percentile=percentile,
    )


def _result(
    symbol: str,
    strategy_id: str = "value",
    score: float = 80.0,
    percentile: float = 0.95,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
        rank_percentile=percentile,
    )


def test_candidate_evidence_valid_construction() -> None:
    ev = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(_result("600000.SH"),),
        strategy_qualifications=(_qualification("600000.SH"),),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    assert ev.symbol == "600000.SH"
    assert len(ev.strategy_results) == 1
    assert len(ev.strategy_qualifications) == 1
    assert ev.market_validation == MarketValidation.CONFIRMED
    assert ev.signal == Signal.NO_SIGNAL


def test_candidate_evidence_rejects_mismatched_result_symbol() -> None:
    with pytest.raises(ValueError, match="symbol"):
        CandidateEvidence(
            symbol="600000.SH",
            strategy_results=(_result("600001.SH"),),
            strategy_qualifications=(_qualification("600000.SH"),),
            market_validation=MarketValidation.CONFIRMED,
            signal=Signal.NO_SIGNAL,
        )


def test_candidate_evidence_rejects_mismatched_qualification_symbol() -> None:
    with pytest.raises(ValueError, match="symbol"):
        CandidateEvidence(
            symbol="600000.SH",
            strategy_results=(_result("600000.SH"),),
            strategy_qualifications=(_qualification("600001.SH"),),
            market_validation=MarketValidation.CONFIRMED,
            signal=Signal.NO_SIGNAL,
        )


def test_candidate_evidence_requires_at_least_one_qualified_qualification() -> None:
    with pytest.raises(ValueError, match="qualified"):
        CandidateEvidence(
            symbol="600000.SH",
            strategy_results=(_result("600000.SH"),),
            strategy_qualifications=(_qualification("600000.SH", qualified=False),),
            market_validation=MarketValidation.CONFIRMED,
            signal=Signal.NO_SIGNAL,
        )


def test_candidate_evidence_allows_none_for_market_and_signal_representation() -> None:
    ev = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(_result("600000.SH"),),
        strategy_qualifications=(_qualification("600000.SH"),),
        market_validation=None,
        signal=None,
    )
    assert ev.market_validation is None
    assert ev.signal is None


def test_candidate_selection_immutability_and_fields() -> None:
    sel = CandidateSelection(
        symbol="600000.SH",
        policy_version="v1",
        reasons=("value top 5%",),
    )
    assert sel.symbol == "600000.SH"
    assert sel.policy_version == "v1"
    assert sel.reasons == ("value top 5%",)
    with pytest.raises(ValidationError):
        sel.symbol = "600001.SH"  # type: ignore[misc]
