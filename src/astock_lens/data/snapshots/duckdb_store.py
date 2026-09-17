"""DuckDB snapshot store.

`docs/ARCHITECTURE.md` §14 specifies DuckDB for V1 metadata and snapshots. The
JSON store shipped earlier was explicitly interim, and this implementation
replaces it behind the same `SnapshotStore` protocol so no caller changes.

DuckDB lives in the optional `data` extra, so it is imported inside the methods
that need it: importing this module must stay safe in the default environment.
A missing extra raises a message naming the command that installs it, rather
than an `ImportError` from three frames down.

Reads never write. Asking for a snapshot that was never taken returns nothing
and does not create a database file — the same rule the JSON store follows.
"""

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel

from astock_lens.data.snapshots.store import (
    SnapshotConflictError,
    canonical_json,
    canonical_payload,
    conflict_message,
)
from astock_lens.domain.enums import SnapshotKind

if TYPE_CHECKING:
    import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    kind VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    payload JSON NOT NULL,
    written_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (kind, as_of)
)
"""

_MISSING_EXTRA = (
    "DuckDB is not installed; run `uv sync --extra data` to use DuckDBSnapshotStore"
)


class DuckDBSnapshotStore:
    """Persist snapshots as rows in a local DuckDB database.

    One row per (kind, as_of). Rewriting the same key with identical content is
    idempotent; rewriting it with different content raises
    `SnapshotConflictError`, exactly as the JSON store does. A caller must not
    be able to tell the two implementations apart.
    """

    def __init__(self, database: Path) -> None:
        self._database = database

    def write(
        self,
        kind: SnapshotKind,
        as_of: datetime,
        records: Sequence[BaseModel],
    ) -> Path:
        """Persist one snapshot, or accept an identical rewrite."""
        self._database.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_payload(records)

        existing = self._stored_payload(kind, as_of)
        if existing is not None:
            if existing == payload:
                return self._database
            raise SnapshotConflictError(conflict_message(kind, as_of))

        with self._connect() as connection:
            connection.execute(SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO snapshots "
                "(kind, as_of, payload, written_at) VALUES (?, ?, ?, ?)",
                [kind.value, as_of.date(), payload, datetime.now(UTC)],
            )

        return self._database

    def _stored_payload(self, kind: SnapshotKind, as_of: datetime) -> str | None:
        """这个键上已经存了什么，用规范形式表示；没有就是 `None`。"""
        if not self._database.is_file():
            return None

        with self._connect() as connection:
            connection.execute(SCHEMA)
            rows = connection.execute(
                "SELECT payload FROM snapshots WHERE kind = ? AND as_of = ?",
                [kind.value, as_of.date()],
            ).fetchall()

        if not rows:
            return None
        stored = rows[0][0]
        if not isinstance(stored, str):
            return None

        loaded: object = json.loads(stored)
        if not isinstance(loaded, list):
            return None
        return canonical_json(loaded)

    def read(
        self,
        kind: SnapshotKind,
        as_of: datetime,
    ) -> tuple[dict[str, object], ...]:
        """Return the stored records, or `()` when no snapshot exists."""
        if not self._database.is_file():
            return ()

        with self._connect() as connection:
            connection.execute(SCHEMA)
            rows = connection.execute(
                "SELECT payload FROM snapshots WHERE kind = ? AND as_of = ?",
                [kind.value, as_of.date()],
            ).fetchall()

        return _records(rows)

    def latest(self, kind: SnapshotKind) -> tuple[dict[str, object], ...]:
        """Return the records from the most recent date stored for this kind."""
        if not self._database.is_file():
            return ()

        with self._connect() as connection:
            connection.execute(SCHEMA)
            rows = connection.execute(
                "SELECT payload FROM snapshots WHERE kind = ? "
                "ORDER BY as_of DESC LIMIT 1",
                [kind.value],
            ).fetchall()

        return _records(rows)

    def dates(self, kind: SnapshotKind) -> tuple[str, ...]:
        """Return the dates that actually have a snapshot for this kind."""
        if not self._database.is_file():
            return ()

        with self._connect() as connection:
            connection.execute(SCHEMA)
            rows = connection.execute(
                "SELECT as_of FROM snapshots WHERE kind = ? ORDER BY as_of",
                [kind.value],
            ).fetchall()

        found: list[str] = []
        for row in rows:
            value = row[0]
            if isinstance(value, date):
                found.append(value.isoformat())
        return tuple(found)

    def _connect(self) -> "duckdb.DuckDBPyConnection":
        # Quoted above: under PEP 649 a bare annotation would be resolved
        # against this module's namespace, which deliberately has no DuckDB.
        try:
            import duckdb
        except ImportError as error:  # pragma: no cover - exercised by absence
            raise RuntimeError(_MISSING_EXTRA) from error
        return duckdb.connect(str(self._database))


def _records(rows: list[tuple[object, ...]]) -> tuple[dict[str, object], ...]:
    """Decode the JSON payload of a single row into record mappings."""
    if not rows:
        return ()

    payload = rows[0][0]
    if not isinstance(payload, str):
        return ()

    loaded: object = json.loads(payload)
    if not isinstance(loaded, list):
        return ()

    return tuple(
        cast("dict[str, object]", item) for item in loaded if isinstance(item, dict)
    )
