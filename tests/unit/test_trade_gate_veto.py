from datetime import UTC, datetime

from astock_lens.domain.enums import (
    MarketValidation,
    Signal,
    TradeProfile,
    VetoSeverity,
)
from astock_lens.trade_gate.models import (
    ThesisAuditResult,
    TradeContext,
    TradeIntent,
    TradeRiskProposal,
)
from astock_lens.trade_gate.profiles import load_trade_gate_profiles
from astock_lens.trade_gate.veto import evaluate_vetoes


def test_vetoes_include_upstream_hard_blocks_and_missing_confirmation() -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    intent = TradeIntent(
        id="i",
        symbol="000001.SZ",
        action="ENTRY",
        profile=TradeProfile.EVENT,
        thesis="thesis",
        expected_holding_days=2,
        created_at=now,
        risk=TradeRiskProposal(
            account_nav=10000,
            planned_entry_price=10,
            stop_loss_price=9,
            quantity=100,
            invalidation_rule="跌破9",
        ),
    )
    context = TradeContext(
        symbol=intent.symbol,
        as_of=now,
        candidate_status="published",
        market_validation=MarketValidation.CONTRADICTED,
        signal=Signal.BREAKDOWN,
        confirmation_met=False,
        stock_return_1d=-0.01,
        sector_return_1d=0.02,
    )
    vetoes = evaluate_vetoes(
        intent=intent,
        context=context,
        profile=load_trade_gate_profiles()[TradeProfile.EVENT],
        audit=ThesisAuditResult(dimensions=()),
        fomo_score=2,
    )
    by_code = {v.code: v for v in vetoes}
    assert by_code["UPSTREAM_MARKET_CONTRADICTED"].severity is VetoSeverity.HARD
    assert by_code["UPSTREAM_BREAKDOWN"].severity is VetoSeverity.HARD
    assert "NO_PRICE_CONFIRMATION" in by_code
    assert "RELATIVE_WEAKNESS" in by_code
