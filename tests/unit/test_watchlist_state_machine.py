"""Watchlist state machine tests.

The rule these tests pin down: the design confirms exactly one active path,
`DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL` (`spec §13`,
`DATA_MODEL.md §5`). Anything the design does not confirm — going backwards,
skipping a state, or touching a reserved state — is refused by name rather
than accepted by guessing.
"""

from datetime import UTC, datetime, timedelta

import pytest

from astock_lens.domain.enums import WatchlistState
from astock_lens.watchlist.state_machine import (
    WatchlistTransitionError,
    allowed_transitions,
    open_entry,
    transition,
)

CREATED_AT = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LATER = CREATED_AT + timedelta(days=1)

RESERVED_STATES = (
    WatchlistState.READY,
    WatchlistState.HOLDING,
    WatchlistState.EXITED,
    WatchlistState.ARCHIVED,
)


def test_a_new_entry_is_discovered_and_records_its_creation() -> None:
    entry = open_entry("600519.SH", at=CREATED_AT, thesis="brand moat")

    assert entry.symbol == "600519.SH"
    assert entry.state is WatchlistState.DISCOVERED
    assert entry.thesis == "brand moat"
    assert entry.created_at == CREATED_AT
    assert entry.updated_at == CREATED_AT
    assert len(entry.timeline) == 1
    event = entry.timeline[0]
    assert event.from_state is None
    assert event.to_state is WatchlistState.DISCOVERED
    assert event.at == CREATED_AT


def test_the_confirmed_path_moves_one_state_at_a_time() -> None:
    entry = open_entry("600519.SH", at=CREATED_AT)

    for step, target in enumerate(
        (
            WatchlistState.WATCH,
            WatchlistState.DEEP_RESEARCH,
            WatchlistState.TRACK_SIGNAL,
        ),
        start=1,
    ):
        entry = transition(entry, target, at=CREATED_AT + timedelta(days=step))
        assert entry.state is target

    assert [event.to_state for event in entry.timeline] == [
        WatchlistState.DISCOVERED,
        WatchlistState.WATCH,
        WatchlistState.DEEP_RESEARCH,
        WatchlistState.TRACK_SIGNAL,
    ]


def test_a_transition_updates_updated_at_but_never_created_at() -> None:
    entry = open_entry("600519.SH", at=CREATED_AT)

    moved = transition(entry, WatchlistState.WATCH, at=LATER, note="worth watching")

    assert moved.created_at == CREATED_AT
    assert moved.updated_at == LATER
    assert moved.timeline[-1].note == "worth watching"
    # The original record is untouched: entries are immutable values.
    assert entry.state is WatchlistState.DISCOVERED
    assert entry.updated_at == CREATED_AT


@pytest.mark.parametrize("target", RESERVED_STATES)
def test_reserved_states_are_unreachable_in_v1(target: WatchlistState) -> None:
    entry = open_entry("600519.SH", at=CREATED_AT)

    with pytest.raises(WatchlistTransitionError) as raised:
        transition(entry, target, at=LATER)

    assert target.value in str(raised.value)


def test_skipping_a_state_is_refused() -> None:
    entry = open_entry("600519.SH", at=CREATED_AT)

    with pytest.raises(WatchlistTransitionError) as raised:
        transition(entry, WatchlistState.DEEP_RESEARCH, at=LATER)

    assert "DISCOVERED" in str(raised.value)
    assert "WATCH" in str(raised.value)


def test_going_backwards_is_refused() -> None:
    entry = transition(
        open_entry("600519.SH", at=CREATED_AT), WatchlistState.WATCH, at=LATER
    )

    with pytest.raises(WatchlistTransitionError):
        transition(entry, WatchlistState.DISCOVERED, at=LATER + timedelta(days=1))


def test_the_end_of_the_path_has_nowhere_left_to_go() -> None:
    entry = open_entry("600519.SH", at=CREATED_AT)
    for step, target in enumerate(
        (
            WatchlistState.WATCH,
            WatchlistState.DEEP_RESEARCH,
            WatchlistState.TRACK_SIGNAL,
        ),
        start=1,
    ):
        entry = transition(entry, target, at=CREATED_AT + timedelta(days=step))

    assert allowed_transitions(WatchlistState.TRACK_SIGNAL) == ()
    with pytest.raises(WatchlistTransitionError):
        transition(entry, WatchlistState.TRACK_SIGNAL, at=LATER + timedelta(days=5))


def test_a_transition_cannot_move_backwards_in_time() -> None:
    entry = transition(
        open_entry("600519.SH", at=LATER), WatchlistState.WATCH, at=LATER
    )

    with pytest.raises(WatchlistTransitionError):
        transition(entry, WatchlistState.DEEP_RESEARCH, at=CREATED_AT)


def test_naive_timestamps_are_refused() -> None:
    """A timestamp without an offset cannot say when the state changed."""
    naive = datetime(2026, 9, 4, 15, 0)  # noqa: DTZ001 - the point of the test

    with pytest.raises(ValueError, match="timezone"):
        open_entry("600519.SH", at=naive)

    entry = open_entry("600519.SH", at=CREATED_AT)
    with pytest.raises(ValueError, match="timezone"):
        transition(entry, WatchlistState.WATCH, at=naive)


def test_editing_the_thesis_keeps_the_state_and_the_timeline_intact() -> None:
    entry = open_entry("600519.SH", at=CREATED_AT)

    edited = entry.model_copy(
        update={
            "thesis": "brand moat plus pricing power",
            "key_questions": ("can price rises outrun volume decline?",),
            "risk_conditions": ("channel inventory rebuild",),
            "waiting_for": ("Q3 report",),
            "updated_at": LATER,
        }
    )

    assert edited.state is WatchlistState.DISCOVERED
    assert edited.timeline == entry.timeline
    assert edited.key_questions == ("can price rises outrun volume decline?",)
