"""Snapshot persistence.

`docs/ARCHITECTURE.md` §14 specifies DuckDB for V1 snapshots, but DuckDB lives
in the optional `data` extra and bootstrap keeps the default environment light.
So this module defines the `SnapshotStore` boundary and ships a standard-library
JSON implementation: the chain can be exercised end to end with no extra
dependency, and a DuckDB store can replace it later without touching a caller.

## 写入权与冲突

同一个 `(kind, as_of)` 只有三种结果：

* 不存在 → 写入；
* 已存在且内容一致 → 幂等成功，不重写文件；
* 已存在且内容不同 → `SnapshotConflictError`，本阶段不提供隐式覆盖。

正式快照是同一天研究结论的唯一凭据，静默覆盖会让"今天的结论"取决于谁最后
跑了一次命令。重跑同一天、同一份数据仍然成功，因为那是同一份内容；换一份
内容想挤掉它，就必须先有人显式决定怎么处理，而不是由一次偶然的命令行完成。
"""

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel

from astock_lens.domain.enums import SnapshotKind


class SnapshotConflictError(RuntimeError):
    """同一天、同一类正式快照已经有不同内容，本次写入被拒绝。"""


def canonical_json(items: Sequence[object]) -> str:
    """把记录序列化成可以逐字节比较的形式。

    比较的是内容，不是文件的缩进风格，也不是 DuckDB 里那串 JSON 的文本格式：
    两个 Store 必须对"内容是否相同"给出同一个答案。
    """
    return json.dumps(
        list(items),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_payload(records: Sequence[BaseModel]) -> str:
    """The canonical form of a record sequence about to be written."""
    return canonical_json([record.model_dump(mode="json") for record in records])


def conflict_message(kind: SnapshotKind, as_of: datetime) -> str:
    """两个 Store 共用的冲突说明：必须点名 kind 与日期。"""
    return (
        f"{kind.value} snapshot for {as_of.date().isoformat()} already exists "
        f"with different content; refusing to overwrite it"
    )


class SnapshotStore(Protocol):
    """Persistence boundary for daily snapshots."""

    def write(
        self,
        kind: SnapshotKind,
        as_of: datetime,
        records: Sequence[BaseModel],
    ) -> Path:
        """Persist one snapshot, or refuse to replace different content.

        Returns where the snapshot lives. Raises `SnapshotConflictError` when
        the same `(kind, as_of)` already holds different records.
        """
        ...

    def read(
        self,
        kind: SnapshotKind,
        as_of: datetime,
    ) -> tuple[dict[str, object], ...]:
        """Return stored records, or an empty tuple when none were written.

        An absent snapshot is a normal answer, not an error: the API must be
        able to say "no scan exists for that date".
        """
        ...

    def dates(self, kind: SnapshotKind) -> tuple[str, ...]:
        """Return the dates that actually have a snapshot for this kind."""
        ...


class JsonSnapshotStore:
    """Write snapshots as JSON files named by kind and date.

    This is an interim format, and it is deliberately boring: one file per kind
    per day, records serialized by Pydantic's JSON mode so enum values and
    timestamps survive a round trip.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def write(
        self,
        kind: SnapshotKind,
        as_of: datetime,
        records: Sequence[BaseModel],
    ) -> Path:
        """Write one snapshot file, or accept an identical rewrite.

        An identical payload is idempotent — the file is left untouched. A
        different payload for the same `(kind, as_of)` is refused rather than
        overwritten.
        """
        path = self.path_for(kind, as_of)
        payload = canonical_payload(records)
        existing = self._stored_payload(path)
        if existing is not None:
            if existing == payload:
                return path
            raise SnapshotConflictError(conflict_message(kind, as_of))

        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "kind": kind.value,
            "as_of": as_of.isoformat(),
            "records": json.loads(payload),
        }
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def _stored_payload(self, path: Path) -> str | None:
        """Return the canonical form of what is stored, or `None` if nothing is."""
        if not path.is_file():
            return None

        document: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            return None
        records = document.get("records")
        if not isinstance(records, list):
            return None
        return canonical_json(records)

    def read(
        self,
        kind: SnapshotKind,
        as_of: datetime,
    ) -> tuple[dict[str, object], ...]:
        """Read one snapshot file; return `()` when it does not exist."""
        path = self.path_for(kind, as_of)
        if not path.is_file():
            return ()

        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return ()
        records = payload.get("records")
        if not isinstance(records, list):
            return ()
        return tuple(
            cast("dict[str, object]", record)
            for record in records
            if isinstance(record, dict)
        )

    def path_for(self, kind: SnapshotKind, as_of: datetime) -> Path:
        """Return the file a snapshot for this kind and date would occupy."""
        return self._root / kind.value / f"{as_of.date().isoformat()}.json"

    def dates(self, kind: SnapshotKind) -> tuple[str, ...]:
        """Return the dates that actually have a snapshot for this kind.

        ISO filenames sort chronologically, so the tuple is ordered. An absent
        kind is a normal answer, not an error — the same rule `read` follows.
        """
        directory = self._root / kind.value
        if not directory.is_dir():
            return ()
        return tuple(sorted(path.stem for path in directory.glob("*.json")))
