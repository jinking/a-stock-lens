"""Watchlist records.

A watchlist entry is not a bookmark. It carries the reasoning that put a symbol
there — thesis, open questions, risk conditions, what the author is waiting for
— and the timeline of how its state changed, so a later reader can tell what
was believed and when (`docs/DATA_MODEL.md` §5).
"""

from datetime import datetime

from astock_lens.domain.enums import WatchlistState
from astock_lens.domain.models import DomainRecord


class WatchlistTimelineEvent(DomainRecord):
    """One recorded state change.

    `from_state` is `None` for the event that created the entry: "there was no
    state before this one" is a different fact from "the state was X", and the
    timeline is worth keeping readable.
    """

    at: datetime
    to_state: WatchlistState
    from_state: WatchlistState | None = None
    note: str | None = None


class WatchlistEntry(DomainRecord):
    """One symbol under research attention."""

    symbol: str
    state: WatchlistState
    created_at: datetime
    updated_at: datetime
    thesis: str | None = None
    key_questions: tuple[str, ...] = ()
    risk_conditions: tuple[str, ...] = ()
    waiting_for: tuple[str, ...] = ()
    timeline: tuple[WatchlistTimelineEvent, ...] = ()
