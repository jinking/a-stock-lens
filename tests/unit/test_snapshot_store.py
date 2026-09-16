"""Snapshot store tests.

The rule these tests pin down: reading a snapshot that was never written is an
empty result, not an error. The API needs to answer "no scan for that date"
rather than fail.
"""

from datetime import UTC, datetime
from pathlib import Path

from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import DataStatus, SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _factor_result(symbol: str = "600000.SH") -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor="avg_amount_20d",
        as_of=AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=1_014_500.0,
    )


def test_write_then_read_round_trips(local_tmp: Path) -> None:
    store = JsonSnapshotStore(local_tmp)
    store.write(SnapshotKind.FACTOR, AS_OF, [_factor_result()])

    records = store.read(SnapshotKind.FACTOR, AS_OF)

    assert len(records) == 1
    assert records[0]["symbol"] == "600000.SH"
    assert records[0]["status"] == "VALUE"
    assert records[0]["raw_value"] == 1_014_500.0


def test_unwritten_date_reads_empty(local_tmp: Path) -> None:
    assert JsonSnapshotStore(local_tmp).read(SnapshotKind.CANDIDATE, AS_OF) == ()


def test_snapshot_path_is_kind_and_date_named(local_tmp: Path) -> None:
    path = JsonSnapshotStore(local_tmp).write(SnapshotKind.FACTOR, AS_OF, [])

    assert path == local_tmp / "FACTOR" / "2026-09-04.json"
    assert path.is_file()


def test_kinds_do_not_collide(local_tmp: Path) -> None:
    store = JsonSnapshotStore(local_tmp)
    store.write(SnapshotKind.FACTOR, AS_OF, [_factor_result()])
    store.write(SnapshotKind.CANDIDATE, AS_OF, [_factor_result("000001.SZ")])

    factor_records = store.read(SnapshotKind.FACTOR, AS_OF)
    candidate_records = store.read(SnapshotKind.CANDIDATE, AS_OF)

    assert [record["symbol"] for record in factor_records] == ["600000.SH"]
    assert [record["symbol"] for record in candidate_records] == ["000001.SZ"]


def test_snapshot_records_the_as_of_it_was_written_for(local_tmp: Path) -> None:
    store = JsonSnapshotStore(local_tmp)
    path = store.write(SnapshotKind.STRATEGY, AS_OF, [])

    assert "2026-09-04T15:00:00+00:00" in path.read_text(encoding="utf-8")
