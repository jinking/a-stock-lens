"""FastAPI application factory.

The API exposes domain queries over stored snapshots. Web clients never reach
DuckDB directly, and no route recomputes a factor (`docs/ARCHITECTURE.md` §2) —
so this module imports the storage boundary and nothing else from the pipeline.
"""

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException

from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.domain.enums import SnapshotKind
from astock_lens.watchlist.store import resolve_watchlist_store

SERVICE_NAME = "A-Stock Lens"
SNAPSHOT_ROOT_ENV = "ASTOCK_SNAPSHOT_ROOT"
WATCHLIST_ROOT_ENV = "ASTOCK_WATCHLIST_ROOT"
DEFAULT_SNAPSHOT_ROOT = Path("data/snapshots")
DEFAULT_WATCHLIST_ROOT = Path("data/watchlist")

# A bare trade date means the A-share close on that day, so a query resolves to
# the same snapshot key the CLI writes for `--as-of <date>`.
SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE_HOUR = 15


def create_app(
    snapshot_root: Path | None = None,
    watchlist_root: Path | None = None,
) -> FastAPI:
    """Build the API application.

    Storage is resolved per request rather than opened here, so importing the
    app never touches the filesystem.
    """
    application = FastAPI(title=SERVICE_NAME)

    def root() -> Path:
        if snapshot_root is not None:
            return snapshot_root
        return Path(os.getenv(SNAPSHOT_ROOT_ENV, str(DEFAULT_SNAPSHOT_ROOT)))

    def watchlist() -> Path:
        if watchlist_root is not None:
            return watchlist_root
        return Path(os.getenv(WATCHLIST_ROOT_ENV, str(DEFAULT_WATCHLIST_ROOT)))

    @application.get("/health")
    def health() -> dict[str, str]:
        """Report process liveness only."""
        return {"status": "ok", "service": SERVICE_NAME}

    @application.get("/factors")
    def factors(symbol: str, as_of: str) -> dict[str, object]:
        """Read stored factor results for one symbol on one date."""
        records = _read(root(), SnapshotKind.FACTOR, as_of)
        return {
            "as_of": as_of,
            "symbol": symbol,
            "records": [record for record in records if record.get("symbol") == symbol],
        }

    @application.get("/universe")
    def universe(as_of: str) -> dict[str, object]:
        """Read the stored universe snapshot for one date."""
        records = _read(root(), SnapshotKind.UNIVERSE, as_of)
        return {"as_of": as_of, "snapshot": records[0] if records else None}

    @application.get("/candidates")
    def candidates(as_of: str) -> dict[str, object]:
        """Read the stored candidate snapshot for one date."""
        records = _read(root(), SnapshotKind.CANDIDATE, as_of)
        return {"as_of": as_of, "records": list(records)}

    @application.get("/watchlist")
    def watchlist_entries() -> dict[str, object]:
        """Read the tracked symbols and their research context.

        An empty watchlist is a normal answer, not an error: nothing has been
        discovered yet is different from the question being unanswerable.
        """
        store = resolve_watchlist_store(watchlist())
        entries = []
        for symbol in store.symbols():
            entry = store.read(symbol)
            if entry is not None:
                entries.append(entry.model_dump(mode="json"))
        return {"symbols": list(store.symbols()), "entries": entries}

    return application


def _read(root: Path, kind: SnapshotKind, as_of: str) -> tuple[dict[str, object], ...]:
    """Read one snapshot, or raise a 404 that names the missing date."""
    try:
        day = date.fromisoformat(as_of)
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail=f"as_of must be YYYY-MM-DD, got {as_of!r}"
        ) from error

    records = resolve_snapshot_store(root).read(
        kind,
        datetime(day.year, day.month, day.day, CLOSE_HOUR, tzinfo=SHANGHAI),
    )
    if not records:
        raise HTTPException(
            status_code=404, detail=f"no {kind.value} snapshot for {as_of}"
        )
    return records
