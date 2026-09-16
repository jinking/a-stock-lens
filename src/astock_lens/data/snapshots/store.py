"""Snapshot persistence.

`docs/ARCHITECTURE.md` §14 specifies DuckDB for V1 snapshots, but DuckDB lives
in the optional `data` extra and bootstrap keeps the default environment light.
So this module defines the `SnapshotStore` boundary and ships a standard-library
JSON implementation: the chain can be exercised end to end with no extra
dependency, and a DuckDB store can replace it later without touching a caller.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel

from astock_lens.domain.enums import SnapshotKind


class SnapshotStore(Protocol):
    """Persistence boundary for daily snapshots."""

    def write(
        self,
        kind: SnapshotKind,
        as_of: datetime,
        records: Sequence[BaseModel],
    ) -> Path:
        """Persist the records for one snapshot and return where they landed."""
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
        """Write one snapshot file, creating its directory if needed."""
        path = self.path_for(kind, as_of)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": kind.value,
            "as_of": as_of.isoformat(),
            "records": [record.model_dump(mode="json") for record in records],
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

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
