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

    One row per (kind, as_of). Writing the same key again replaces the row
    rather than appending, so re-running a scan for a date leaves exactly one
    snapshot behind — the JSON store gets the same behaviour by overwriting its
    file, and a caller must not be able to tell the difference.
    """

    def __init__(self, database: Path) -> None:
        self._database = database

    def write(
        self,
        kind: SnapshotKind,
        as_of: datetime,
        records: Sequence[BaseModel],
    ) -> Path:
        """Persist the records for one snapshot, replacing any earlier write."""
        self._database.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [record.model_dump(mode="json") for record in records],
            ensure_ascii=False,
        )

        with self._connect() as connection:
            connection.execute(SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO snapshots "
                "(kind, as_of, payload, written_at) VALUES (?, ?, ?, ?)",
                [kind.value, as_of.date(), payload, datetime.now(UTC)],
            )

        return self._database

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
