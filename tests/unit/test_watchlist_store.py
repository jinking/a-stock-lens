"""Watchlist store tests.

Two rules are pinned down here. First, one symbol is one entry: writing again
replaces rather than appends, so the file never accumulates duplicates of the
same thesis. Second, reading a symbol that was never written is an empty
answer, not an error — the CLI must be able to ask "is this being watched?"
without failing.

Both backends run the same round trip, for the same reason the snapshot stores
do: "interchangeable behind the protocol" has to mean something testable.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from astock_lens.domain.enums import WatchlistState
from astock_lens.watchlist.models import WatchlistEntry
from astock_lens.watchlist.state_machine import open_entry, transition
from astock_lens.watchlist.store import (
    JsonWatchlistStore,
    WatchlistStore,
    resolve_watchlist_store,
)

CREATED_AT = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LATER = CREATED_AT + timedelta(days=1)


@pytest.fixture(params=["json", "duckdb"])
def store(request: pytest.FixtureRequest, local_tmp: Path) -> Iterator[WatchlistStore]:
    """Both implementations, exercised through the protocol they share."""
    if request.param == "json":
        yield JsonWatchlistStore(local_tmp / "json")
    else:
        pytest.importorskip("duckdb")
        from astock_lens.watchlist.duckdb_store import DuckDBWatchlistStore

        yield DuckDBWatchlistStore(local_tmp / "watchlist.duckdb")


def test_write_then_read_round_trips_a_full_entry(store: WatchlistStore) -> None:
    entry = open_entry(
        "600519.SH",
        at=CREATED_AT,
        thesis="brand moat",
        key_questions=("is volume still falling?",),
        risk_conditions=("channel inventory rebuild",),
        waiting_for=("Q3 report",),
    )
    store.write(entry)

    read = store.read("600519.SH")

    assert read is not None
    assert read.symbol == entry.symbol
    assert read.state is WatchlistState.DISCOVERED
    assert read.thesis == "brand moat"
    assert read.key_questions == ("is volume still falling?",)
    assert read.risk_conditions == ("channel inventory rebuild",)
    assert read.waiting_for == ("Q3 report",)
    assert read.created_at == CREATED_AT


def test_the_timeline_survives_the_round_trip(store: WatchlistStore) -> None:
    entry = transition(
        open_entry("600519.SH", at=CREATED_AT), WatchlistState.WATCH, at=LATER
    )
    store.write(entry)

    read = store.read("600519.SH")

    assert read is not None
    assert [event.to_state for event in read.timeline] == [
        WatchlistState.DISCOVERED,
        WatchlistState.WATCH,
    ]
    assert read.timeline[-1].at == LATER


def test_an_unwritten_symbol_reads_as_absent(store: WatchlistStore) -> None:
    assert store.read("000001.SZ") is None


def test_writing_the_same_symbol_twice_replaces_it(store: WatchlistStore) -> None:
    store.write(open_entry("600519.SH", at=CREATED_AT, thesis="first"))
    store.write(open_entry("600519.SH", at=CREATED_AT, thesis="second"))

    read = store.read("600519.SH")

    assert read is not None
    assert read.thesis == "second"
    assert store.symbols() == ("600519.SH",)


def test_symbols_lists_every_entry_in_order(store: WatchlistStore) -> None:
    store.write(open_entry("600519.SH", at=CREATED_AT))
    store.write(open_entry("000001.SZ", at=CREATED_AT))

    assert store.symbols() == ("000001.SZ", "600519.SH")


def test_the_json_store_names_one_file_per_symbol(local_tmp: Path) -> None:
    store = JsonWatchlistStore(local_tmp)

    path = store.write(open_entry("600519.SH", at=CREATED_AT))

    assert path == local_tmp / "600519.SH.json"
    assert path.is_file()


def test_resolve_defaults_to_json_and_honours_the_backend(local_tmp: Path) -> None:
    assert isinstance(resolve_watchlist_store(local_tmp), JsonWatchlistStore)

    pytest.importorskip("duckdb")
    from astock_lens.watchlist.duckdb_store import DuckDBWatchlistStore

    backend = resolve_watchlist_store(local_tmp, backend="duckdb")
    assert isinstance(backend, DuckDBWatchlistStore)

    with pytest.raises(ValueError, match="unknown watchlist backend"):
        resolve_watchlist_store(local_tmp, backend="postgres")


def test_a_stored_entry_can_be_moved_to_the_next_state(local_tmp: Path) -> None:
    """The store hands back a record the state machine can act on again."""
    store = JsonWatchlistStore(local_tmp)
    store.write(open_entry("600519.SH", at=CREATED_AT))

    stored = store.read("600519.SH")
    assert stored is not None
    moved = transition(stored, WatchlistState.WATCH, at=LATER, note="reviewed")
    store.write(moved)

    read = store.read("600519.SH")
    assert read is not None
    assert isinstance(read, WatchlistEntry)
    assert read.state is WatchlistState.WATCH
    assert read.timeline[-1].note == "reviewed"
