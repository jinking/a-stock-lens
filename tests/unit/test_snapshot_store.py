"""Snapshot store tests.

These tests pin down two rules. Reading a snapshot that was never written is an
empty result, not an error — the API needs to answer "no scan for that date"
rather than fail. Writing one is decided by content: the same content is
idempotent, different content is refused instead of silently replacing the day's
formal result.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.data.snapshots.store import JsonSnapshotStore, SnapshotConflictError
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


# --- conflict protection -----------------------------------------------------


def test_same_snapshot_payload_is_idempotent(local_tmp: Path) -> None:
    """重跑同一天、同一份数据是同一份内容，应当原样成功。"""
    store = JsonSnapshotStore(local_tmp)
    first = store.write(SnapshotKind.FACTOR, AS_OF, [_factor_result()])
    stored = first.read_text(encoding="utf-8")

    second = store.write(SnapshotKind.FACTOR, AS_OF, [_factor_result()])

    assert second == first
    assert first.read_text(encoding="utf-8") == stored


def test_different_payload_for_the_same_kind_and_date_is_rejected(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp)
    store.write(SnapshotKind.FACTOR, AS_OF, [_factor_result()])

    with pytest.raises(SnapshotConflictError):
        store.write(SnapshotKind.FACTOR, AS_OF, [_factor_result("600519.SH")])

    # 被拒绝的写入没有留下痕迹：原来的那份还在。
    assert [record["symbol"] for record in store.read(SnapshotKind.FACTOR, AS_OF)] == [
        "600000.SH"
    ]


def test_a_conflict_names_the_kind_and_the_date(local_tmp: Path) -> None:
    """消息必须点名冲突对象，否则 Job Manifest 里只留下一句无用的报错。"""
    store = JsonSnapshotStore(local_tmp)
    store.write(SnapshotKind.CANDIDATE, AS_OF, [_factor_result()])

    with pytest.raises(SnapshotConflictError) as raised:
        store.write(SnapshotKind.CANDIDATE, AS_OF, [_factor_result("000001.SZ")])

    assert "CANDIDATE" in str(raised.value)
    assert "2026-09-04" in str(raised.value)


def test_the_comparison_is_by_content_not_by_file_layout(local_tmp: Path) -> None:
    """缩进、键顺序、空白都不是内容差异。"""
    store = JsonSnapshotStore(local_tmp)
    path = store.path_for(SnapshotKind.FACTOR, AS_OF)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = _factor_result().model_dump(mode="json")
    reordered = {key: record[key] for key in reversed(list(record))}
    path.write_text(
        json.dumps({"records": [reordered]}, separators=(",", ":")),
        encoding="utf-8",
    )

    written = store.write(SnapshotKind.FACTOR, AS_OF, [_factor_result()])

    assert written == path


def test_an_empty_snapshot_conflicts_with_a_measured_one(local_tmp: Path) -> None:
    """空结果也是一种结果：它不能被后来的一份真实数据悄悄替换。"""
    store = JsonSnapshotStore(local_tmp)
    store.write(SnapshotKind.FACTOR, AS_OF, ())

    with pytest.raises(SnapshotConflictError):
        store.write(SnapshotKind.FACTOR, AS_OF, [_factor_result()])
