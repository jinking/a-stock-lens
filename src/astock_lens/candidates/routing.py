"""Next-action routing.

The rule follows from the score by ordering alone, with no percentile cut and
no threshold: a symbol that cleared eligibility and carries a measured score is
worth watching, and anything else is left alone. A made-up threshold would read
downstream as a product judgement that nobody made.

`DEEP_RESEARCH` and `TRACK_SIGNAL` are not reachable: both need the signal
layer, which does not exist yet. Leaving them unreachable is honest; guessing
what would trigger them is not.
"""

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
