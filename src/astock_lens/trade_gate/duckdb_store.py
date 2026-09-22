"""可选 DuckDB Trade Ledger 后端，读取不创建数据库。"""

import json
from pathlib import Path
from typing import Any, ClassVar

from astock_lens.trade_gate.models import (
    ExecutionRecord,
    OverrideRecord,
    TradeGateEvaluation,
    TradeIntent,
    TradePlan,
    TradeReview,
)
from astock_lens.trade_gate.store import TradeLedgerConflictError


class DuckDBTradeLedgerStore:
    _MODELS: ClassVar[dict[str, type[Any]]] = {
        "INTENT": TradeIntent,
        "EVALUATION": TradeGateEvaluation,
        "PLAN": TradePlan,
        "OVERRIDE": OverrideRecord,
        "EXECUTION": ExecutionRecord,
        "REVIEW": TradeReview,
    }

    def __init__(self, database: Path) -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB trade backend requires the optional data extra"
            ) from exc
        self._duckdb: Any = duckdb
        self._database = database

    def _connect(self, *, write: bool = False) -> Any:
        if not write and not self._database.is_file():
            return None
        return self._duckdb.connect(str(self._database), read_only=not write)

    @staticmethod
    def _has_table(connection: Any) -> bool:
        count = connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name='trade_ledger'"
        ).fetchone()[0]
        return bool(count > 0)

    def _write(self, kind: str, record: Any) -> Path:
        payload = record.model_dump(mode="json")
        parent_id = (
            payload.get("intent_id")
            or payload.get("evaluation_id")
            or payload.get("execution_id")
        )
        symbol = payload.get("symbol") or payload.get("context", {}).get("symbol")
        created = (
            payload.get("created_at")
            or payload.get("evaluated_at")
            or payload.get("filled_at")
            or payload.get("reviewed_at")
        )
        with self._connect(write=True) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS trade_ledger (kind VARCHAR NOT NULL, record_id VARCHAR NOT NULL, parent_id VARCHAR, symbol VARCHAR, created_at TIMESTAMPTZ NOT NULL, payload JSON NOT NULL, PRIMARY KEY(kind, record_id))"
            )
            existing = connection.execute(
                "SELECT payload FROM trade_ledger WHERE kind=? AND record_id=?",
                [kind, record.id],
            ).fetchone()
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if existing:
                old = (
                    json.loads(existing[0])
                    if isinstance(existing[0], str)
                    else existing[0]
                )
                if old != payload:
                    raise TradeLedgerConflictError(
                        f"{kind}/{record.id} already exists with different content"
                    )
                return self._database
            connection.execute(
                "INSERT INTO trade_ledger VALUES (?, ?, ?, ?, ?, ?)",
                [kind, record.id, parent_id, symbol, created, serialized],
            )
        return self._database

    def _read(self, kind: str, record_id: str) -> Any | None:
        connection = self._connect()
        if connection is None:
            return None
        try:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM trade_ledger WHERE kind=? AND record_id=?",
                [kind, record_id],
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return self._MODELS[kind].model_validate(payload)
        finally:
            connection.close()

    def write_intent(self, record: TradeIntent) -> Path:
        return self._write("INTENT", record)

    def read_intent(self, record_id: str) -> TradeIntent | None:
        return self._read("INTENT", record_id)

    def write_evaluation(self, record: TradeGateEvaluation) -> Path:
        return self._write("EVALUATION", record)

    def read_evaluation(self, record_id: str) -> TradeGateEvaluation | None:
        return self._read("EVALUATION", record_id)

    def evaluations_for_intent(self, intent_id: str) -> tuple[TradeGateEvaluation, ...]:
        connection = self._connect()
        if connection is None:
            return ()
        try:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM trade_ledger WHERE kind='EVALUATION' AND parent_id=? ORDER BY created_at, record_id",
                [intent_id],
            ).fetchall()
            return tuple(
                TradeGateEvaluation.model_validate(
                    json.loads(row[0]) if isinstance(row[0], str) else row[0]
                )
                for row in rows
            )
        finally:
            connection.close()

    def history_for_symbol(self, symbol: str) -> tuple[TradeGateEvaluation, ...]:
        connection = self._connect()
        if connection is None:
            return ()
        try:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM trade_ledger WHERE kind='EVALUATION' AND symbol=? ORDER BY created_at, record_id",
                [symbol],
            ).fetchall()
            return tuple(
                TradeGateEvaluation.model_validate(
                    json.loads(row[0]) if isinstance(row[0], str) else row[0]
                )
                for row in rows
            )
        finally:
            connection.close()

    def write_plan(self, record: TradePlan) -> Path:
        return self._write("PLAN", record)

    def read_plan(self, record_id: str) -> TradePlan | None:
        return self._read("PLAN", record_id)

    def write_override(self, record: OverrideRecord) -> Path:
        return self._write("OVERRIDE", record)

    def read_override(self, record_id: str) -> OverrideRecord | None:
        return self._read("OVERRIDE", record_id)

    def write_execution(self, record: ExecutionRecord) -> Path:
        return self._write("EXECUTION", record)

    def write_review(self, record: TradeReview) -> Path:
        return self._write("REVIEW", record)
