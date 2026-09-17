"""Candidate qualification & selection pipeline integration tests."""

from datetime import UTC, datetime
from pathlib import Path

from astock_lens.candidates.policy import (
    RepresentativeCandidatePolicy,
)
from astock_lens.domain.enums import JobStage, MarketValidation, NextAction, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.pipelines import stages
from astock_lens.pipelines.daily import _blocked_reasons, _Context
from astock_lens.qualifications.models import (
    AbsoluteQualificationVerdict,
    StrategyQualification,
)
from astock_lens.qualifications.registry import build_qualifiers
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.universe.config import UniverseConfig

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LINEAGE = SnapshotLineage(
    universe_snapshot="2026-09-04:fixture",
    factor_version="v1",
    strategy_version="v1",
)


class _DummyPassRule:
    version = "v1"

    def evaluate(self, result: StrategyResult) -> AbsoluteQualificationVerdict:
        return AbsoluteQualificationVerdict(passed=True, reasons=("passed absolute",))


class _DummyFailRule:
    version = "v1"

    def evaluate(self, result: StrategyResult) -> AbsoluteQualificationVerdict:
        return AbsoluteQualificationVerdict(passed=False, risks=("failed absolute",))


def _make_strategy_result(
    symbol: str,
    strategy_id: str = "value",
    percentile: float = 0.95,
    score: float = 85.0,
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
        rank_percentile=percentile,
    )


def test_no_approved_absolute_rules_blocks_build_candidates() -> None:
    context = _Context(
        csv_root=Path("/fake"),
        as_of=AS_OF,
        dataset="bars",
        securities_dataset="securities",
        universe_config=UniverseConfig(
            exchanges=("SSE", "SZSE"),
            min_listing_days=180,
            min_average_turnover_20d=10_000_000.0,
        ),
        factor_configs=(),
        scanners=(),
        strategy_directory=Path("/fake"),
        store=None,  # type: ignore[arg-type]
        sync=None,
        candidate_policy=RepresentativeCandidatePolicy(),
        qualifiers=None,  # No qualifiers configured!
    )
    reasons = _blocked_reasons(JobStage.BUILD_CANDIDATES, context)
    assert any("strategy qualification rules are not configured" in r for r in reasons)


def test_missing_upstream_layers_blocks_build_candidates() -> None:
    context = _Context(
        csv_root=Path("/fake"),
        as_of=AS_OF,
        dataset="bars",
        securities_dataset="securities",
        universe_config=UniverseConfig(
            exchanges=("SSE", "SZSE"),
            min_listing_days=180,
            min_average_turnover_20d=10_000_000.0,
        ),
        factor_configs=(),
        scanners=(),
        strategy_directory=Path("/fake"),
        store=None,  # type: ignore[arg-type]
        sync=None,
        candidate_policy=RepresentativeCandidatePolicy(),
        qualifiers=build_qualifiers(
            {
                s: _DummyPassRule()
                for s in ("value", "growth", "garp", "quality", "dividend", "momentum")
            }
        ),
    )
    reasons = _blocked_reasons(JobStage.BUILD_CANDIDATES, context)
    assert any("its inputs do not exist yet" in r for r in reasons)
    assert any(JobStage.MARKET_VALIDATE.value in r for r in reasons)
    assert any(JobStage.RUN_SIGNALS.value in r for r in reasons)


def test_candidate_stage_direct_call_with_complete_evidence_produces_candidates() -> (
    None
):
    policy = RepresentativeCandidatePolicy()
    sym = "600000.SH"
    strat_res = _make_strategy_result(sym, strategy_id="value", percentile=0.95)
    qual = StrategyQualification(
        symbol=sym,
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    candidates = stages.candidate_stage(
        strategy_results=(strat_res,),
        qualifications=(qual,),
        market_validation_by_symbol={sym: MarketValidation.CONFIRMED},
        signal_by_symbol={sym: Signal.BREAKOUT},
        lineage=LINEAGE,
        as_of=AS_OF,
        policy=policy,
    )
    assert len(candidates) == 1
    c = candidates[0]
    assert c.symbol == sym
    assert c.next_action is NextAction.WATCH
    assert c.market_validation is MarketValidation.CONFIRMED
    assert c.signal is Signal.BREAKOUT


def test_signal_no_signal_does_not_disqualify_candidate() -> None:
    policy = RepresentativeCandidatePolicy()
    sym = "600000.SH"
    strat_res = _make_strategy_result(sym, strategy_id="value", percentile=0.95)
    qual = StrategyQualification(
        symbol=sym,
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    candidates = stages.candidate_stage(
        strategy_results=(strat_res,),
        qualifications=(qual,),
        market_validation_by_symbol={sym: MarketValidation.CONFIRMED},
        signal_by_symbol={sym: Signal.NO_SIGNAL},
        lineage=LINEAGE,
        as_of=AS_OF,
        policy=policy,
    )
    assert len(candidates) == 1
    assert candidates[0].symbol == sym
    assert candidates[0].signal is Signal.NO_SIGNAL


def test_market_validation_contradicted_disqualifies_candidate() -> None:
    policy = RepresentativeCandidatePolicy()
    sym = "600000.SH"
    strat_res = _make_strategy_result(sym, strategy_id="value", percentile=0.95)
    qual = StrategyQualification(
        symbol=sym,
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    candidates = stages.candidate_stage(
        strategy_results=(strat_res,),
        qualifications=(qual,),
        market_validation_by_symbol={sym: MarketValidation.CONTRADICTED},
        signal_by_symbol={sym: Signal.BREAKOUT},
        lineage=LINEAGE,
        as_of=AS_OF,
        policy=policy,
    )
    assert candidates == ()
