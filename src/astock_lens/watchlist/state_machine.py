"""Watchlist state machine.

`spec §13` confirms one active path and nothing else:

    DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL

`READY`, `HOLDING`, `EXITED` and `ARCHIVED` are reserved for later phases and
must not be reachable in V1. The design does not define backward moves
(`WATCH → DISCOVERED`), skipped moves (`DISCOVERED → DEEP_RESEARCH`), or any
trigger that changes state on its own — so this module refuses all of them with
a message naming what it refused. Accepting a transition nobody specified
would put a product decision in the code, which `AGENTS.md` forbids.

Every accepted transition appends a timeline event, because `DATA_MODEL.md` §5
requires state changes to be recorded rather than overwritten.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from astock_lens.domain.enums import (
    ACTIVE_WATCHLIST_STATES,
    RESERVED_WATCHLIST_STATES,
    WatchlistState,
)
from astock_lens.watchlist.models import WatchlistEntry, WatchlistTimelineEvent

CONFIRMED_PATH: tuple[WatchlistState, ...] = (
    WatchlistState.DISCOVERED,
    WatchlistState.WATCH,
    WatchlistState.DEEP_RESEARCH,
    WatchlistState.TRACK_SIGNAL,
)

# Each state reaches only its successor in the confirmed path; the last state
# reaches nothing, because the design names no step after TRACK_SIGNAL.
CONFIRMED_TRANSITIONS: Mapping[WatchlistState, tuple[WatchlistState, ...]] = {
    state: (CONFIRMED_PATH[index + 1],) if index + 1 < len(CONFIRMED_PATH) else ()
    for index, state in enumerate(CONFIRMED_PATH)
}


class WatchlistTransitionError(ValueError):
    """A state change the design does not confirm."""


def allowed_transitions(state: WatchlistState) -> tuple[WatchlistState, ...]:
    """Return the states `state` may move to in V1."""
    return CONFIRMED_TRANSITIONS.get(state, ())


def open_entry(
    symbol: str,
    *,
    at: datetime,
    thesis: str | None = None,
    key_questions: Sequence[str] = (),
    risk_conditions: Sequence[str] = (),
    waiting_for: Sequence[str] = (),
) -> WatchlistEntry:
    """Start tracking a symbol at `DISCOVERED`.

    `DISCOVERED` is the first active state, so a new entry needs no transition
    to reach it — but the creation is still a state change and is recorded as
    one.
    """
    _require_aware(at, field="at")
    return WatchlistEntry(
        symbol=symbol,
        state=WatchlistState.DISCOVERED,
        created_at=at,
        updated_at=at,
        thesis=thesis,
        key_questions=tuple(key_questions),
        risk_conditions=tuple(risk_conditions),
        waiting_for=tuple(waiting_for),
        timeline=(
            WatchlistTimelineEvent(
                at=at,
                from_state=None,
                to_state=WatchlistState.DISCOVERED,
                note="discovered",
            ),
        ),
    )


def transition(
    entry: WatchlistEntry,
    to_state: WatchlistState,
    *,
    at: datetime,
    note: str | None = None,
) -> WatchlistEntry:
    """Return a new entry moved to `to_state`, or refuse the move.

    The entry passed in is left untouched: entries are immutable values, and a
    caller that decides not to persist the move has changed nothing.
    """
    _require_aware(at, field="at")

    if at < entry.updated_at:
        raise WatchlistTransitionError(
            f"{entry.symbol} cannot move to {to_state} at {at.isoformat()}: "
            f"its last recorded change was at {entry.updated_at.isoformat()}"
        )

    if to_state in RESERVED_WATCHLIST_STATES:
        raise WatchlistTransitionError(
            f"{entry.symbol} cannot move to {to_state}: it is a reserved state "
            "that V1 must not reach (spec §13)"
        )

    allowed = allowed_transitions(entry.state)
    if to_state not in allowed:
        raise WatchlistTransitionError(_refusal(entry, to_state, allowed))

    return entry.model_copy(
        update={
            "state": to_state,
            "updated_at": at,
            "timeline": (
                *entry.timeline,
                WatchlistTimelineEvent(
                    at=at, from_state=entry.state, to_state=to_state, note=note
                ),
            ),
        }
    )


def _refusal(
    entry: WatchlistEntry,
    to_state: WatchlistState,
    allowed: tuple[WatchlistState, ...],
) -> str:
    """Explain a refused move by naming what the design does confirm."""
    if not allowed:
        return (
            f"{entry.symbol} is already at {entry.state}, the end of the "
            "confirmed path; the design names no state after it (spec §13)"
        )
    moves = ", ".join(state.value for state in allowed)
    known = ", ".join(sorted(state.value for state in ACTIVE_WATCHLIST_STATES))
    return (
        f"{entry.symbol} cannot move from {entry.state} to {to_state}: the "
        f"design confirms only {moves} from {entry.state} (active states are "
        f"{known})"
    )


def _require_aware(moment: datetime, *, field: str) -> None:
    """Reject a timestamp that cannot say when something happened."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(
            f"{field} must be timezone-aware; a naive timestamp would make the "
            "recorded order of state changes unverifiable"
        )
