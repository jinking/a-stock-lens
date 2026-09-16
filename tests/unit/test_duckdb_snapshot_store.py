"""DuckDB snapshot store.

The DuckDB store satisfies the same protocol as the JSON one, so most of these
tests run the *same* round-trip against both implementations — that is what
"interchangeable behind the protocol" has to mean if it means anything.

DuckDB lives in the optional `data` extra, so this module skips when it is
absent. The default environment stays green without it, which is the point of
keeping it optional.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

# DuckDB is an optional extra. Skipping here — ahead of the imports below —
# keeps the default environment green without it.
pytest.importorskip("duckdb")

from astock_lens.data.snapshots.duckdb_store import DuckDBSnapshotStore
from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.data.snapshots.store import JsonSnapshotStore, SnapshotStore
from astock_lens.domain.enums import SnapshotKind
from astock_lens.domain.models import DailyBar

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
NEXT_DAY = datetime(2026, 9, 5, 15, 0, tzinfo=UTC)

DATABASE_NAME = "astock.duckdb"


@pytest.fixture(params=["json", "duckdb"])
def store(request: pytest.FixtureRequest, local_tmp: Path) -> Iterator[SnapshotStore]:
    """Both implementations, exercised through the protocol they share."""
    if request.param == "json":
        yield JsonSnapshotStore(local_tmp / "json")
    else:
        yield DuckDBSnapshotStore(local_tmp / DATABASE_NAME)


def _bar(symbol: str = "600000.SH", *, close: float = 10.0) -> DailyBar:
    return DailyBar(symbol=symbol, trade_date=AS_OF.date(), close=close)


# --- behaviour shared by both stores ----------------------------------------


def test_a_written_snapshot_reads_back(store: SnapshotStore) -> None:
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar(),))

    records = store.read(SnapshotKind.FACTOR, AS_OF)

    assert len(records) == 1
    assert records[0]["symbol"] == "600000.SH"


def test_an_absent_snapshot_reads_as_empty(store: SnapshotStore) -> None:
    """No snapshot for a date is a normal answer, not an error."""
    assert store.read(SnapshotKind.CANDIDATE, AS_OF) == ()


def test_rewriting_the_same_key_replaces_rather_than_accumulates(
    store: SnapshotStore,
) -> None:
    """Re-running one scan for one date must not leave two snapshots behind."""
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar("600000.SH"),))
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar("600519.SH"),))

    records = store.read(SnapshotKind.FACTOR, AS_OF)

    assert len(records) == 1
    assert records[0]["symbol"] == "600519.SH"


def test_dates_are_kept_apart(store: SnapshotStore) -> None:
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar("600000.SH"),))
    store.write(SnapshotKind.FACTOR, NEXT_DAY, (_bar("600519.SH"),))

    first = store.read(SnapshotKind.FACTOR, AS_OF)
    second = store.read(SnapshotKind.FACTOR, NEXT_DAY)

    assert first[0]["symbol"] == "600000.SH"
    assert second[0]["symbol"] == "600519.SH"


def test_kinds_are_kept_apart(store: SnapshotStore) -> None:
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar("600000.SH"),))
    store.write(SnapshotKind.CANDIDATE, AS_OF, (_bar("600519.SH"),))

    factors = store.read(SnapshotKind.FACTOR, AS_OF)
    candidates = store.read(SnapshotKind.CANDIDATE, AS_OF)

    assert factors[0]["symbol"] == "600000.SH"
    assert candidates[0]["symbol"] == "600519.SH"


def test_a_date_is_not_confused_with_an_empty_snapshot(store: SnapshotStore) -> None:
    """Writing nothing is different from never having written."""
    store.write(SnapshotKind.FACTOR, AS_OF, ())

    assert store.read(SnapshotKind.FACTOR, AS_OF) == ()
    assert store.read(SnapshotKind.FACTOR, NEXT_DAY) == ()


def test_serialised_values_survive_the_round_trip(store: SnapshotStore) -> None:
    """Enums and dates must not degrade into Python objects on the way back."""
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar(),))

    record = store.read(SnapshotKind.FACTOR, AS_OF)[0]

    assert record["trade_date"] == "2026-09-04"
    assert record["close"] == 10.0


def test_write_reports_where_the_snapshot_landed(store: SnapshotStore) -> None:
    path = store.write(SnapshotKind.FACTOR, AS_OF, (_bar(),))

    assert path.exists()


def test_several_records_survive_together(store: SnapshotStore) -> None:
    records = (_bar("600000.SH"), _bar("600519.SH"), _bar("300750.SZ"))

    store.write(SnapshotKind.FACTOR, AS_OF, records)

    assert len(store.read(SnapshotKind.FACTOR, AS_OF)) == 3


# --- DuckDB-only surface -----------------------------------------------------


def _duck(local_tmp: Path) -> DuckDBSnapshotStore:
    return DuckDBSnapshotStore(local_tmp / DATABASE_NAME)


def test_reading_does_not_create_the_database(local_tmp: Path) -> None:
    """A read must not write. An absent database stays absent."""
    _duck(local_tmp).read(SnapshotKind.FACTOR, AS_OF)

    assert not (local_tmp / DATABASE_NAME).exists()


def test_writing_creates_the_database_and_its_directory(local_tmp: Path) -> None:
    store = DuckDBSnapshotStore(local_tmp / "nested" / DATABASE_NAME)

    store.write(SnapshotKind.FACTOR, AS_OF, (_bar(),))

    assert (local_tmp / "nested" / DATABASE_NAME).is_file()


def test_latest_returns_the_most_recent_date(local_tmp: Path) -> None:
    store = _duck(local_tmp)
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar("600000.SH"),))
    store.write(SnapshotKind.FACTOR, NEXT_DAY, (_bar("600519.SH"),))

    latest = store.latest(SnapshotKind.FACTOR)

    assert len(latest) == 1
    assert latest[0]["symbol"] == "600519.SH"


def test_latest_on_an_absent_kind_is_empty(local_tmp: Path) -> None:
    assert _duck(local_tmp).latest(SnapshotKind.MARKET_REGIME) == ()


def test_dates_lists_what_was_actually_written(local_tmp: Path) -> None:
    store = _duck(local_tmp)
    store.write(SnapshotKind.FACTOR, NEXT_DAY, (_bar(),))
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar(),))

    assert store.dates(SnapshotKind.FACTOR) == ("2026-09-04", "2026-09-05")


def test_dates_on_an_absent_kind_is_empty(local_tmp: Path) -> None:
    assert _duck(local_tmp).dates(SnapshotKind.UNIVERSE) == ()


def test_the_snapshot_is_stored_as_a_queryable_row(local_tmp: Path) -> None:
    """The point of DuckDB over JSON: the snapshot is reachable with SQL."""
    import duckdb

    store = _duck(local_tmp)
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar(),))

    connection = duckdb.connect(str(local_tmp / DATABASE_NAME), read_only=True)
    try:
        rows = connection.execute(
            "SELECT kind, as_of FROM snapshots ORDER BY kind"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [("FACTOR", AS_OF.date())]


def test_satisfies_the_snapshot_store_protocol(local_tmp: Path) -> None:
    """The assignment is the assertion; mypy checks it where the tests cannot."""
    store: SnapshotStore = _duck(local_tmp)

    assert isinstance(store, DuckDBSnapshotStore)


def test_the_backend_resolver_defaults_to_json(local_tmp: Path) -> None:
    """No configuration means the JSON store: the default env must stay
    dependency-free."""
    store = resolve_snapshot_store(local_tmp)

    assert isinstance(store, JsonSnapshotStore)


def test_the_backend_resolver_selects_duckdb_by_configuration(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASTOCK_SNAPSHOT_BACKEND", "duckdb")

    store = resolve_snapshot_store(local_tmp)

    assert isinstance(store, DuckDBSnapshotStore)
    # Writes and reads go to the same file the resolver chose.
    store.write(SnapshotKind.FACTOR, AS_OF, (_bar(),))
    assert resolve_snapshot_store(local_tmp).read(SnapshotKind.FACTOR, AS_OF)


def test_the_backend_resolver_rejects_an_unknown_backend(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASTOCK_SNAPSHOT_BACKEND", "sqlite")

    with pytest.raises(ValueError, match="backend"):
        resolve_snapshot_store(local_tmp)
