"""Watchlist persistence.

`docs/ARCHITECTURE.md` §14 puts the watchlist in DuckDB. DuckDB lives in the
optional `data` extra, so — exactly as with snapshots — this module defines the
`WatchlistStore` boundary and ships a standard-library JSON implementation as
the default backend. `resolve_watchlist_store` switches to DuckDB without any
caller changing.

One symbol is one entry. Writing a symbol again replaces its record instead of
appending a second one, so the store can never report two theses for the same
stock.
"""

import json
import os
from pathlib import Path
from typing import Protocol

from astock_lens.watchlist.duckdb_store import DuckDBWatchlistStore
from astock_lens.watchlist.models import WatchlistEntry

BACKEND_ENV = "ASTOCK_WATCHLIST_BACKEND"
DEFAULT_BACKEND = "json"
DUCKDB_FILENAME = "watchlist.duckdb"

JSON = "json"
DUCKDB = "duckdb"


class WatchlistStore(Protocol):
    """Persistence boundary for watchlist entries."""

    def write(self, entry: WatchlistEntry) -> Path:
        """Store one entry, replacing any earlier record for its symbol."""
        ...

    def read(self, symbol: str) -> WatchlistEntry | None:
        """Return the stored entry, or `None` when the symbol is untracked."""
        ...

    def symbols(self) -> tuple[str, ...]:
        """Return every tracked symbol, in a stable order."""
        ...


class JsonWatchlistStore:
    """Write one JSON file per tracked symbol."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def write(self, entry: WatchlistEntry) -> Path:
        """Write one entry, creating the directory if needed."""
        path = self.path_for(entry.symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(entry.model_dump(mode="json"), indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        return path

    def read(self, symbol: str) -> WatchlistEntry | None:
        """Read one entry; an unreadable record raises instead of being hidden.

        A corrupt file is a fact about the store, not an absence of a thesis,
        so it must not read as "this symbol is not tracked".
        """
        path = self.path_for(symbol)
        if not path.is_file():
            return None
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(  # noqa: TRY004 - the file's shape, not a caller's type
                f"watchlist record is not a mapping: {path}"
            )
        return WatchlistEntry.model_validate(payload)

    def symbols(self) -> tuple[str, ...]:
        """Return every symbol that has a record, in a stable order."""
        if not self._root.is_dir():
            return ()
        return tuple(sorted(path.stem for path in self._root.glob("*.json")))

    def path_for(self, symbol: str) -> Path:
        """Return the file a symbol's record occupies."""
        return self._root / f"{symbol}.json"


def resolve_watchlist_store(
    root: Path, *, backend: str | None = None, database: Path | None = None
) -> WatchlistStore:
    """Return the store the configured backend names.

    A typo fails loudly rather than silently falling back to JSON: a run that
    wrote to a different store than the operator expects is worse than a run
    that did not start.

    `database` 是 `astock_lens.data.storage.paths` 解析出的统一库：显式传入时
    DuckDB 后端用它，CLI 与 API 因此读同一个文件。不传时保持原行为——库文件
    放在 `root` 下面，自己解析 root 的调用方不受影响。
    """
    configured = backend if backend is not None else os.getenv(BACKEND_ENV)
    chosen = (configured or DEFAULT_BACKEND).strip().lower()

    if chosen == JSON:
        return JsonWatchlistStore(root)
    if chosen == DUCKDB:
        return DuckDBWatchlistStore(
            database if database is not None else root / DUCKDB_FILENAME
        )
    raise ValueError(
        f"unknown watchlist backend {chosen!r}; expected {JSON!r} or {DUCKDB!r}"
    )
