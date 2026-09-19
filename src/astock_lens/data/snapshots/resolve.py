"""Resolve which snapshot store a run should use.

The JSON store is the default because it keeps the default environment
dependency-free. Setting `ASTOCK_SNAPSHOT_BACKEND=duckdb` selects the DuckDB
implementation behind the same protocol; a typo must fail loudly rather than
silently fall back to JSON.
"""

import os
from pathlib import Path

from astock_lens.data.snapshots.duckdb_store import DuckDBSnapshotStore
from astock_lens.data.snapshots.store import JsonSnapshotStore, SnapshotStore

BACKEND_ENV = "ASTOCK_SNAPSHOT_BACKEND"
DEFAULT_BACKEND = "json"
DUCKDB_FILENAME = "snapshots.duckdb"

JSON = "json"
DUCKDB = "duckdb"


def resolve_snapshot_store(
    root: Path, *, backend: str | None = None, database: Path | None = None
) -> SnapshotStore:
    """Return the store the configured backend names.

    The DuckDB database lives inside the snapshot root, so both backends keep
    their files under one directory and switching backends never scatters
    state.

    `database` is the unified database resolved by
    `astock_lens.data.storage.paths` — the CLI and the API pass it so both
    ends of the same run point at one file. Omitting it keeps the original
    behaviour (the database sits under `root`), so callers that resolve their
    own root are unaffected.
    """
    configured = backend if backend is not None else os.getenv(BACKEND_ENV)
    chosen = (configured or DEFAULT_BACKEND).strip().lower()

    if chosen == JSON:
        return JsonSnapshotStore(root)
    if chosen == DUCKDB:
        return DuckDBSnapshotStore(
            database if database is not None else root / DUCKDB_FILENAME
        )
    raise ValueError(
        f"unknown snapshot backend {chosen!r}; expected {JSON!r} or {DUCKDB!r}"
    )
