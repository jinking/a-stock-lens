from datetime import UTC, datetime

import pytest

from astock_lens.domain.enums import TradeProfile
from astock_lens.trade_gate.duckdb_store import DuckDBTradeLedgerStore
from astock_lens.trade_gate.models import TradeIntent, TradeRiskProposal


def test_duckdb_store_round_trips_intent_and_read_does_not_create(tmp_path) -> None:
    pytest.importorskip("duckdb")
    database = tmp_path / "ledger.duckdb"
    store = DuckDBTradeLedgerStore(database)
    assert store.read_intent("missing") is None
    assert not database.exists()
    intent = TradeIntent(
        id="intent",
        symbol="000001.SZ",
        action="ENTRY",
        profile=TradeProfile.EVENT,
        thesis="thesis",
        expected_holding_days=2,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
        risk=TradeRiskProposal(
            account_nav=1000,
            planned_entry_price=10,
            stop_loss_price=9,
            quantity=1,
            invalidation_rule="跌破9",
        ),
    )
    store.write_intent(intent)
    assert store.read_intent("intent") == intent
