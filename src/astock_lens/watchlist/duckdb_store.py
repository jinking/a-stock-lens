"""DuckDB watchlist store.

`docs/ARCHITECTURE.md` §14 names DuckDB for the watchlist. This implementation
sits behind the same `WatchlistStore` protocol as the JSON one, so a caller
cannot tell which backend it is talking to.

DuckDB is an optional extra, so it is imported inside the methods that need it:
importing this module must stay safe in the default environment. Reads never
write — asking about an untracked symbol must not create a database file.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from astock_lens.watchlist.models import WatchlistEntry

if TYPE_CHECKING:
    import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol VARCHAR NOT NULL,
    payload JSON NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol)
)
"""

_MISSING_EXTRA = (
    "DuckDB is not installed; run `uv sync --extra data` to use DuckDBWatchlistStore"
)


class DuckDBWatchlistStore:
    """Persist watchlist entries as one row per symbol."""

    def __init__(self, database: Path) -> None:
        self._database = database

    def write(self, entry: WatchlistEntry) -> Path:
        """Store one entry, replacing any earlier record for its symbol."""
        self._database.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.execute(SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO watchlist (symbol, payload, updated_at) "
                "VALUES (?, ?, ?)",
                [
                    entry.symbol,
                    json.dumps(entry.model_dump(mode="json"), ensure_ascii=False),
                    datetime.now(UTC),
                ],
            )

        return self._database

    def read(self, symbol: str) -> WatchlistEntry | None:
        """Return the stored entry, or `None` when nothing is stored."""
        if not self._database.is_file():
            return None

        with self._connect() as connection:
            connection.execute(SCHEMA)
            row = connection.execute(
                "SELECT payload FROM watchlist WHERE symbol = ?", [symbol]
            ).fetchone()

        if row is None:
            return None
        payload: object = json.loads(str(row[0]))
        if not isinstance(payload, dict):
            raise ValueError(  # noqa: TRY004 - the row's shape, not a caller's type
                f"watchlist record is not a mapping: {symbol}"
            )
        return WatchlistEntry.model_validate(payload)

    def symbols(self) -> tuple[str, ...]:
        """Return every tracked symbol, in a stable order."""
        if not self._database.is_file():
            return ()

        with self._connect() as connection:
            connection.execute(SCHEMA)
            rows = connection.execute(
                "SELECT symbol FROM watchlist ORDER BY symbol"
            ).fetchall()

        return tuple(str(row[0]) for row in rows)

    def _connect(self) -> "duckdb.DuckDBPyConnection":
        try:
            import duckdb
        except ImportError as error:
            raise RuntimeError(_MISSING_EXTRA) from error
        return duckdb.connect(str(self._database))
