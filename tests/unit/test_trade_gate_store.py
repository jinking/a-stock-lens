from datetime import UTC, datetime

from astock_lens.domain.enums import TradeDecision, TradeProfile
from astock_lens.trade_gate.models import (
    IndependentAssessment,
    ThesisAuditResult,
    TradeContext,
    TradeGateEvaluation,
    TradeIntent,
    TradeRiskProposal,
)
from astock_lens.trade_gate.store import (
    JsonTradeLedgerStore,
    TradeLedgerConflictError,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _intent() -> TradeIntent:
    return TradeIntent(
        id="intent-1",
        symbol="000001.SZ",
        action="ENTRY",
        profile=TradeProfile.POSITION,
        thesis="test",
        expected_holding_days=5,
        created_at=NOW,
        risk=TradeRiskProposal(
            account_nav=10000,
            planned_entry_price=10,
            stop_loss_price=9,
            quantity=10,
            invalidation_rule="跌破9",
        ),
    )


def _evaluation(identifier: str) -> TradeGateEvaluation:
    return TradeGateEvaluation(
        id=identifier,
        intent_id="intent-1",
        profile=TradeProfile.POSITION,
        profile_version="v1",
        dimension_scores=(),
        weighted_score=0,
        decision=TradeDecision.NO_TRADE,
        context=TradeContext(
            symbol="000001.SZ", as_of=NOW, candidate_status="not_selected"
        ),
        independent_assessment=IndependentAssessment(summary="none", dimensions=()),
        thesis_audit=ThesisAuditResult(dimensions=()),
        evaluated_at=NOW,
    )


def test_same_day_multiple_evaluations_are_append_only(tmp_path) -> None:
    store = JsonTradeLedgerStore(tmp_path)
    store.write_intent(_intent())
    first, second = _evaluation("eval-1"), _evaluation("eval-2")
    store.write_evaluation(first)
    store.write_evaluation(second)
    assert [item.id for item in store.evaluations_for_intent("intent-1")] == [
        "eval-1",
        "eval-2",
    ]
    assert store.read_intent("intent-1") == _intent()


def test_same_id_is_idempotent_only_for_identical_content(tmp_path) -> None:
    store = JsonTradeLedgerStore(tmp_path)
    record = _intent()
    store.write_intent(record)
    store.write_intent(record)
    changed = record.model_copy(update={"thesis": "different"})
    try:
        store.write_intent(changed)
    except TradeLedgerConflictError:
        pass
    else:
        raise AssertionError(
            "different content must not overwrite an append-only record"
        )
