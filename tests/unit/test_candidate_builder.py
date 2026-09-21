"""Candidate builder tests.

The rule these tests pin down: the builder assembles, it does not decide. The
`next_action` is a parameter whose default is the inert `IGNORE`, and a
candidate whose evidence disagrees with its declared lineage is refused rather
than published with a contradictory provenance.
"""

from datetime import UTC, datetime

import pytest

from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.policy import CandidateEvidence, CandidateSelection
from astock_lens.domain.enums import DataStatus, MarketValidation, NextAction, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LINEAGE = SnapshotLineage(factor_version="v1", strategy_version="v1")


def _strategy_result(
    *,
    strategy_version: str = "v1",
    reasons: tuple[str, ...] = (),
    risks: tuple[str, ...] = (),
) -> StrategyResult:
    return StrategyResult(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version=strategy_version,
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version=strategy_version),
        reasons=reasons,
        risks=risks,
        factor_snapshot=(
            FactorResult(
                symbol="600000.SH",
                factor="avg_amount_20d",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=1_000_000.0,
            ),
        ),
    )


def test_next_action_defaults_to_the_inert_choice() -> None:
    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(), lineage=LINEAGE
    )

    assert candidate.next_action is NextAction.IGNORE


def test_signal_and_market_validation_stay_unset() -> None:
    """Neither layer exists in this slice, so neither is fabricated."""
    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(), lineage=LINEAGE
    )

    assert candidate.market_validation is None
    assert candidate.signal is None


def test_lineage_mismatch_is_refused() -> None:
    result = _strategy_result(strategy_version="v2")

    with pytest.raises(ValueError, match="strategy_version"):
        CandidateBuilder().build(
            "600000.SH", as_of=AS_OF, strategy_results=(result,), lineage=LINEAGE
        )


def test_reasons_and_risks_are_aggregated_from_evidence() -> None:
    result = _strategy_result(reasons=("avg_amount_20d=1000000.0",), risks=("thin",))

    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(result,), lineage=LINEAGE
    )

    assert candidate.reasons == ("avg_amount_20d=1000000.0",)
    assert candidate.risks == ("thin",)
    assert candidate.strategy_results == (result,)


def test_candidate_is_a_research_object_not_a_recommendation() -> None:
    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(), lineage=LINEAGE
    )

    assert candidate.symbol == "600000.SH"
    assert candidate.as_of == AS_OF
    assert candidate.lineage == LINEAGE
    assert candidate.next_action in set(NextAction)


def test_candidate_lineage_carries_complete_stage_versions() -> None:
    """测试 Candidate 的 lineage 完整携带所有上游阶段版本（factor, strategy, qualification, policy, regime, market_validation, signal）。"""
    full_lineage = SnapshotLineage(
        universe_snapshot="2026-09-04:u1",
        factor_version="v1",
        strategy_version="v1",
        regime_version="v1",
        market_validation_version="v1",
        signal_version="v1",
    )
    strategy_res = _strategy_result(strategy_version="v1")
    strategy_qual = StrategyQualification(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    evidence = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(strategy_res,),
        strategy_qualifications=(strategy_qual,),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.BREAKOUT,
    )
    selection = CandidateSelection(
        symbol="600000.SH",
        policy_version="v1",
        reasons=("top candidate",),
    )
    candidate = CandidateBuilder().build(
        evidence=evidence,
        selection=selection,
        as_of=AS_OF,
        lineage=full_lineage,
    )
    assert candidate.lineage.factor_version == "v1"
    assert candidate.lineage.strategy_version == "v1"
    assert candidate.lineage.qualification_version == "v1"
    assert candidate.lineage.candidate_policy_version == "v1"
    assert candidate.lineage.regime_version == "v1"
    assert candidate.lineage.market_validation_version == "v1"
    assert candidate.lineage.signal_version == "v1"
    assert "v1" in candidate.lineage.market_validation_versions()
    assert "v1" in candidate.lineage.signal_versions()
    assert "v1" in candidate.lineage.regime_versions()


def test_candidate_builder_trend_weaken_under_approved_decision_e1() -> None:
    """根据决策 E1：TREND_WEAKEN 标的动作标记为 WATCH，并在 risks 中明确走弱风险警示。"""
    strategy_res = _strategy_result(strategy_version="v1")
    strategy_qual = StrategyQualification(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    evidence = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(strategy_res,),
        strategy_qualifications=(strategy_qual,),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.TREND_WEAKEN,
    )
    selection = CandidateSelection(
        symbol="600000.SH",
        policy_version="v1",
        reasons=("top candidate",),
    )
    candidate = CandidateBuilder().build(
        evidence=evidence,
        selection=selection,
        as_of=AS_OF,
        lineage=LINEAGE,
    )
    assert candidate.next_action == NextAction.WATCH
    assert any("TREND_WEAKEN" in r or "走弱" in r for r in candidate.risks)


def test_candidate_builder_no_signal_under_approved_decision_f1() -> None:
    """根据决策 F1：NO_SIGNAL 标的允许作为常规候选入选，默认动作标记为 WATCH。"""
    strategy_res = _strategy_result(strategy_version="v1")
    strategy_qual = StrategyQualification(
        symbol="600000.SH",
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.92,
    )
    evidence = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(strategy_res,),
        strategy_qualifications=(strategy_qual,),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    selection = CandidateSelection(
        symbol="600000.SH",
        policy_version="v1",
        reasons=("top candidate",),
    )
    candidate = CandidateBuilder().build(
        evidence=evidence,
        selection=selection,
        as_of=AS_OF,
        lineage=LINEAGE,
    )
    assert candidate.next_action == NextAction.WATCH
