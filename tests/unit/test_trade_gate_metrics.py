from datetime import UTC, datetime

from astock_lens.trade_gate.metrics import summarize_trade_discipline
from astock_lens.trade_gate.models import ExecutionRecord, TradeReview


def test_metrics_report_override_rate_and_group_results() -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    executions = tuple(
        ExecutionRecord(
            id=f"e{i}",
            evaluation_id=f"v{i}",
            avg_fill_price=10,
            filled_quantity=1,
            filled_at=now,
            discipline_status=state,
        )
        for i, state in enumerate(("PASS", "OVERRIDDEN"))
    )
    reviews = tuple(
        TradeReview(
            id=f"r{i}",
            execution_id=f"e{i}",
            pnl_amount=pnl,
            pnl_pct=pnl,
            max_drawdown=0,
            max_adverse_excursion=0,
            max_favorable_excursion=0,
            thesis_correct=True,
            gate_correct=True,
            discipline_followed=True,
            lessons_learned="review",
            reviewed_at=now,
        )
        for i, pnl in enumerate((0.1, -0.1))
    )
    result = summarize_trade_discipline(executions, reviews)
    assert result.override_rate == 0.5
    assert result.pass_group.win_rate == 1
    assert result.overridden_group.win_rate == 0
