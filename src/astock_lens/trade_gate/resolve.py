"""解析 Trade Ledger 后端；默认 JSON，DuckDB 使用统一数据库。"""

import os
from pathlib import Path

from astock_lens.data.storage.paths import resolve_storage_paths
from astock_lens.trade_gate.store import JsonTradeLedgerStore, TradeLedgerStore

BACKEND_ENV = "ASTOCK_TRADE_BACKEND"


def resolve_trade_ledger(
    *,
    root: Path | None = None,
    backend: str | None = None,
    database: Path | None = None,
) -> TradeLedgerStore:
    chosen = (
        (backend if backend is not None else os.getenv(BACKEND_ENV, "json"))
        .strip()
        .lower()
    )
    if chosen == "json":
        if root is None:
            root = resolve_storage_paths().trade_root
        return JsonTradeLedgerStore(root)
    if chosen == "duckdb":
        from astock_lens.trade_gate.duckdb_store import DuckDBTradeLedgerStore

        return DuckDBTradeLedgerStore(database or resolve_storage_paths().database)
    raise ValueError(
        f"unknown trade ledger backend {chosen!r}; expected 'json' or 'duckdb'"
    )
