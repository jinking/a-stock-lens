"""Snapshot persistence implementations.

`DuckDBSnapshotStore` imports DuckDB lazily, so importing this package stays
safe in an environment that never installed the `data` extra.
"""

from astock_lens.data.snapshots.duckdb_store import DuckDBSnapshotStore
from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.data.snapshots.store import (
    JsonSnapshotStore,
    SnapshotConflictError,
    SnapshotStore,
)

__all__ = [
    "DuckDBSnapshotStore",
    "JsonSnapshotStore",
    "SnapshotConflictError",
    "SnapshotStore",
    "resolve_snapshot_store",
]
