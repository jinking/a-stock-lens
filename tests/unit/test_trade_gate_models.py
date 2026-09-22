from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from astock_lens.domain.enums import TradeAction, TradeDecision, TradeProfile
from astock_lens.trade_gate.models import TradeIntent, TradeRiskProposal

SH = ZoneInfo("Asia/Shanghai")


def test_trade_gate_vocab_is_exact() -> None:
    assert [x.value for x in TradeAction] == ["ENTRY", "ADD"]
    assert [x.value for x in TradeProfile] == ["EVENT", "SWING", "POSITION"]
    assert [x.value for x in TradeDecision] == ["PASS", "WAIT", "NO_TRADE"]


def test_trade_intent_rejects_naive_time() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        TradeIntent(
            id="intent-1",
            symbol="603991.SH",
            action=TradeAction.ENTRY,
            profile=TradeProfile.EVENT,
            thesis="隔夜芯片上涨可能传导 A 股",
            expected_holding_days=3,
            created_at=datetime(2026, 9, 22, 9, 20),  # noqa: DTZ001
            risk=TradeRiskProposal(
                account_nav=100_000,
                planned_entry_price=175.5,
                stop_loss_price=169.0,
                quantity=100,
                invalidation_rule="跌破 169 且个股继续弱于板块",
            ),
        )


def test_risk_proposal_computes_loss_without_inventing_account_limit() -> None:
    risk = TradeRiskProposal(
        account_nav=100_000,
        planned_entry_price=175.5,
        stop_loss_price=169.0,
        quantity=100,
        invalidation_rule="跌破 169",
    )
    assert risk.position_value == pytest.approx(17_550)
    assert risk.max_loss_amount == pytest.approx(650)
    assert risk.max_loss_pct_of_nav == pytest.approx(0.0065)
