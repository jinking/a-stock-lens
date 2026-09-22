from datetime import UTC, datetime

from astock_lens.domain.enums import TradeDecision, TradeProfile
from astock_lens.trade_gate.models import (
    IndependentAssessment,
    ThesisAuditResult,
    TradeContext,
    TradeGateEvaluation,
)
from astock_lens.trade_gate.profiles import StrategyProfileConfig
from astock_lens.trade_gate.replay import replay_evaluation


def test_replay_uses_stored_context_and_assigns_new_versions() -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    original = TradeGateEvaluation(
        id="old",
        intent_id="intent",
        profile=TradeProfile.POSITION,
        profile_version="v1",
        dimension_scores=(),
        weighted_score=0,
        decision=TradeDecision.NO_TRADE,
        context=TradeContext(symbol="000001.SZ", as_of=now, candidate_status="stored"),
        independent_assessment=IndependentAssessment(summary="stored", dimensions=()),
        thesis_audit=ThesisAuditResult(dimensions=()),
        evaluated_at=now,
    )
    profile = StrategyProfileConfig(
        id=TradeProfile.POSITION,
        version="v2",
        pass_threshold=80,
        wait_threshold=70,
        weights={"x": 100},
        fomo_wait_threshold=8,
    )
    replay = replay_evaluation(original, profile=profile)
    assert replay.id != original.id
    assert replay.replayed_from_evaluation_id == "old"
    assert replay.profile_version == "v2"
