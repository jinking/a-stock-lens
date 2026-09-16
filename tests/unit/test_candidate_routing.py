"""Next-action routing.

The rule follows from the score by ordering alone: a symbol that cleared
eligibility and carries a measured score is worth watching, and anything else
is left alone. No percentile cut is applied, because the design fixes no
threshold and a made-up one would read as a product judgement.

`DEEP_RESEARCH` and `TRACK_SIGNAL` require the signal layer, which does not
exist yet, so they are unreachable rather than approximated.
"""

from datetime import UTC, datetime

import pytest

from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.routing import route_next_action
from astock_lens.domain.enums import NextAction
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _result(*, eligible: bool, score: float | None) -> StrategyResult:
    return StrategyResult(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
    )


def test_an_eligible_scored_symbol_is_watched() -> None:
    assert route_next_action(_result(eligible=True, score=42.0)) is NextAction.WATCH


def test_an_eligible_symbol_without_a_score_is_ignored() -> None:
    """Eligibility alone is not a finding; the scored ranking is."""
    assert route_next_action(_result(eligible=True, score=None)) is NextAction.IGNORE


def test_an_ineligible_symbol_is_ignored() -> None:
    assert route_next_action(_result(eligible=False, score=99.0)) is NextAction.IGNORE


def test_a_score_of_zero_routes_to_watch() -> None:
    """Zero is a measured position, not a missing value."""
    assert route_next_action(_result(eligible=True, score=0.0)) is NextAction.WATCH


def test_only_two_of_the_four_actions_are_reachable() -> None:
    """The other two need a signal layer this slice does not build."""
    reached = {
        route_next_action(_result(eligible=True, score=1.0)),
        route_next_action(_result(eligible=True, score=None)),
        route_next_action(_result(eligible=False, score=None)),
    }

    assert reached == {NextAction.WATCH, NextAction.IGNORE}


def test_an_unknown_score_is_treated_as_missing() -> None:
    assert route_next_action(_result(eligible=True, score=None)) is NextAction.IGNORE


def test_the_routed_action_reaches_a_candidate() -> None:
    result = _result(eligible=True, score=87.5)

    candidate = CandidateBuilder().build(
        "600000.SH",
        as_of=AS_OF,
        strategy_results=(result,),
        lineage=SnapshotLineage(strategy_version="v1"),
        next_action=route_next_action(result),
    )

    assert candidate.next_action is NextAction.WATCH
    assert candidate.strategy_results == (result,)


def test_routing_is_pure() -> None:
    """The same result always routes the same way; nothing is accumulated."""
    result = _result(eligible=True, score=50.0)

    assert route_next_action(result) == route_next_action(result)


@pytest.mark.parametrize("score", [0.0, 0.001, 50.0, 99.999, 100.0])
def test_every_in_range_score_is_watched(score: float) -> None:
    assert route_next_action(_result(eligible=True, score=score)) is NextAction.WATCH
