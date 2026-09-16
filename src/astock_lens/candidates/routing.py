"""Next-action routing.

The rule follows from the score by ordering alone, with no percentile cut and
no threshold: a symbol that cleared eligibility and carries a measured score is
worth watching, and anything else is left alone. A made-up threshold would read
downstream as a product judgement that nobody made.

`DEEP_RESEARCH` and `TRACK_SIGNAL` are not reachable: both need the signal
layer, which does not exist yet. Leaving them unreachable is honest; guessing
what would trigger them is not.
"""

from collections.abc import Sequence

from astock_lens.domain.enums import NextAction
from astock_lens.strategies.contracts import StrategyResult


def route_next_action(result: StrategyResult) -> NextAction:
    """Choose what to do with one strategy result.

    A score of `0.0` routes to `WATCH`, because zero is a measured position at
    the bottom of the ranking rather than a missing value.
    """
    if result.eligible and result.score is not None:
        return NextAction.WATCH
    return NextAction.IGNORE


def route_candidate_actions(results: Sequence[StrategyResult]) -> NextAction:
    """Choose what to do with everything one symbol's scanners found.

    The rule is the same one used for a single result, applied to however many
    scanners fired: a symbol with at least one measured score is worth
    watching, and a symbol whose evidence carries no score is left alone. No
    threshold enters, so no scanner's weight can change the verdict.

    `DEEP_RESEARCH` and `TRACK_SIGNAL` stay unreachable: both need the signal
    and market layers, which this slice does not have.
    """
    if any(result.eligible and result.score is not None for result in results):
        return NextAction.WATCH
    return NextAction.IGNORE
