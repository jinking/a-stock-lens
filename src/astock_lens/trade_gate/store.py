"""按 ID 追加、不可覆盖的 JSON Trade Ledger。"""

import json
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

from astock_lens.trade_gate.models import (
    ExecutionRecord,
    OverrideRecord,
    TradeGateEvaluation,
    TradeIntent,
    TradePlan,
    TradeReview,
)

Record = TypeVar("Record", bound=BaseModel)


class TradeLedgerConflictError(RuntimeError):
    """同一记录 ID 已存在但内容不同。"""


class TradeLedgerStore(Protocol):
    def write_intent(self, record: TradeIntent) -> Path: ...
    def read_intent(self, record_id: str) -> TradeIntent | None: ...
    def write_evaluation(self, record: TradeGateEvaluation) -> Path: ...
    def read_evaluation(self, record_id: str) -> TradeGateEvaluation | None: ...
    def evaluations_for_intent(
        self, intent_id: str
    ) -> tuple[TradeGateEvaluation, ...]: ...
    def write_plan(self, record: TradePlan) -> Path: ...
    def write_override(self, record: OverrideRecord) -> Path: ...
    def write_execution(self, record: ExecutionRecord) -> Path: ...
    def write_review(self, record: TradeReview) -> Path: ...


class JsonTradeLedgerStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _write(self, kind: str, record: BaseModel, record_id: str) -> Path:
        if (
            not record_id
            or Path(record_id).name != record_id
            or record_id in {".", ".."}
        ):
            raise ValueError("record id must be a simple non-empty filename")
        path = self._root / kind / f"{record_id}.json"
        document = record.model_dump(mode="json")
        serialized = (
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) == document:
                return path
            raise TradeLedgerConflictError(
                f"{kind}/{record_id} already exists with different content"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        except FileExistsError:
            if json.loads(path.read_text(encoding="utf-8")) == document:
                return path
            raise TradeLedgerConflictError(
                f"{kind}/{record_id} already exists with different content"
            )
        return path

    def _read(self, kind: str, record_id: str, model: type[Record]) -> Record | None:
        if not record_id or Path(record_id).name != record_id:
            raise ValueError("record id must be a simple non-empty filename")
        path = self._root / kind / f"{record_id}.json"
        return (
            model.model_validate_json(path.read_text(encoding="utf-8"))
            if path.is_file()
            else None
        )

    def write_intent(self, record: TradeIntent) -> Path:
        return self._write("intents", record, record.id)

    def read_intent(self, record_id: str) -> TradeIntent | None:
        return self._read("intents", record_id, TradeIntent)

    def write_evaluation(self, record: TradeGateEvaluation) -> Path:
        return self._write("evaluations", record, record.id)

    def read_evaluation(self, record_id: str) -> TradeGateEvaluation | None:
        return self._read("evaluations", record_id, TradeGateEvaluation)

    def evaluations_for_intent(self, intent_id: str) -> tuple[TradeGateEvaluation, ...]:
        folder = self._root / "evaluations"
        if not folder.exists():
            return ()
        records = (
            TradeGateEvaluation.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(folder.glob("*.json"))
        )
        return tuple(record for record in records if record.intent_id == intent_id)

    def write_plan(self, record: TradePlan) -> Path:
        return self._write("plans", record, record.id)

    def write_override(self, record: OverrideRecord) -> Path:
        return self._write("overrides", record, record.id)

    def write_execution(self, record: ExecutionRecord) -> Path:
        return self._write("executions", record, record.id)

    def write_review(self, record: TradeReview) -> Path:
        return self._write("reviews", record, record.id)
