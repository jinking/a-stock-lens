from datetime import UTC, datetime

import pytest

from astock_lens.domain.enums import TradeDecision, TradeProfile
from astock_lens.trade_gate.models import (
    DimensionScore,
    IndependentAssessment,
    ThesisAuditResult,
    TradeContext,
    TradeGateEvaluation,
)
from astock_lens.trade_gate.service import TradeGateService
from astock_lens.trade_gate.store import JsonTradeLedgerStore

NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _seed_evaluation(store: JsonTradeLedgerStore) -> TradeGateEvaluation:
    evaluation = TradeGateEvaluation(
        id="eval-1",
        intent_id="intent-1",
        profile=TradeProfile.EVENT,
        profile_version="v1",
        dimension_scores=(
            DimensionScore(
                dimension="seed", weight=60, ratio=1, score=60, source="RULE"
            ),
        ),
        weighted_score=60,
        decision=TradeDecision.NO_TRADE,
        context=TradeContext(
            symbol="000001.SZ", as_of=NOW, candidate_status="published"
        ),
        independent_assessment=IndependentAssessment(summary="x", dimensions=()),
        thesis_audit=ThesisAuditResult(dimensions=()),
        evaluated_at=NOW,
        proposed_position_pct=0.1,
    )
    store.write_evaluation(evaluation)
    return evaluation


def _service(store: JsonTradeLedgerStore) -> TradeGateService:
    return TradeGateService(
        store=store, context_builder=None, audit_adapter=None, engine=None
    )  # type: ignore[arg-type]


def test_override_requires_smaller_size_evidence_ack_and_stop(tmp_path) -> None:
    store = JsonTradeLedgerStore(tmp_path)
    _seed_evaluation(store)
    service = _service(store)
    with pytest.raises(ValueError, match="smaller"):
        service.override(
            "eval-1",
            reason="new evidence",
            evidence=("e",),
            fomo_score=2,
            manual_position_limit_pct=0.1,
            manual_stop_rule="跌破9",
            ack_risk=True,
        )
    with pytest.raises(ValueError, match="acknowledgement"):
        service.override(
            "eval-1",
            reason="new evidence",
            evidence=("e",),
            fomo_score=2,
            manual_position_limit_pct=0.05,
            manual_stop_rule="跌破9",
            ack_risk=False,
        )
    with pytest.raises(ValueError, match="stop rule"):
        service.override(
            "eval-1",
            reason="new evidence",
            evidence=("e",),
            fomo_score=2,
            manual_position_limit_pct=0.05,
            manual_stop_rule="",
            ack_risk=True,
        )
    record = service.override(
        "eval-1",
        reason="new evidence",
        evidence=("e",),
        fomo_score=2,
        manual_position_limit_pct=0.05,
        manual_stop_rule="跌破9",
        ack_risk=True,
    )
    with pytest.raises(ValueError, match="override"):
        service.record_execution(
            evaluation_id="eval-1",
            fill_price=10,
            quantity=100,
            filled_at=NOW,
            override_id="unknown",
        )
    execution = service.record_execution(
        evaluation_id="eval-1",
        fill_price=10,
        quantity=100,
        filled_at=NOW,
        override_id=record.id,
    )
    assert execution.discipline_status == "OVERRIDDEN"
