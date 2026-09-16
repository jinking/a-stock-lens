"""Candidate model.

A Candidate is a research object, never a recommendation. It bundles what the
strategy layer found with what the market layer will later add, and it carries
the lineage needed to reproduce the decision context.
"""

from datetime import datetime

from astock_lens.domain.enums import (
    MarketValidation,
    NextAction,
    Signal,
)
from astock_lens.domain.models import DomainRecord, SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult


class Candidate(DomainRecord):
    """One stock, as surfaced by one scan.

    `market_validation` and `signal` are `None` until those layers exist. They
    are not filled with a neutral placeholder, because a placeholder would be
    indistinguishable from a real verdict downstream.
    """

    symbol: str
    as_of: datetime
    next_action: NextAction
    lineage: SnapshotLineage
    strategy_results: tuple[StrategyResult, ...] = ()
    market_validation: MarketValidation | None = None
    signal: Signal | None = None
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
