from datetime import UTC, datetime

from astock_lens.domain.enums import (
    MarketValidation,
    TradeDecision,
    TradeProfile,
)
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.trade_gate.engine import TradeGateEngine
from astock_lens.trade_gate.models import (
    DimensionJudgement,
    IndependentAssessment,
    ThesisAuditResult,
    TradeContext,
    TradeIntent,
    TradeRiskProposal,
)
from astock_lens.trade_gate.profiles import load_trade_gate_profiles

NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _intent(profile: TradeProfile) -> TradeIntent:
    return TradeIntent(
        id="intent-1",
        symbol="000001.SZ",
        action="ENTRY",
        profile=profile,
        thesis="a thesis",
        expected_holding_days=5,
        created_at=NOW,
        risk=TradeRiskProposal(
            account_nav=100000,
            planned_entry_price=10,
            stop_loss_price=9,
            target_price=12,
            quantity=100,
            invalidation_rule="跌破9",
        ),
    )


def test_event_without_intraday_evidence_waits() -> None:
    engine = TradeGateEngine(load_trade_gate_profiles())
    judgement = tuple(
        DimensionJudgement(
            name=name,
            score_ratio=0.95,
            confidence=0.95,
            evidence=("evidence",),
            summary="summary",
        )
        for name in ("catalyst_quality", "expectation_gap", "directness")
    )
    audit = ThesisAuditResult(dimensions=judgement)
    independent = IndependentAssessment(summary="assessment", dimensions=())
    context = TradeContext(symbol="000001.SZ", as_of=NOW, candidate_status="published")
    result = engine.evaluate(
        intent=_intent(TradeProfile.EVENT),
        context=context,
        independent=independent,
        audit=audit,
        fomo_score=1,
    )
    assert result.decision is TradeDecision.WAIT
    assert "stock_return_1d" in result.missing_data
    assert result.reentry_triggers


def test_hard_veto_overrides_high_weighted_score() -> None:
    engine = TradeGateEngine(load_trade_gate_profiles())
    names = ("industry_trend", "competitiveness", "risk_resilience")
    judgement = tuple(
        DimensionJudgement(
            name=name,
            score_ratio=1,
            confidence=1,
            evidence=("evidence",),
            summary="summary",
        )
        for name in names
    )
    audit = ThesisAuditResult(dimensions=judgement)
    independent = IndependentAssessment(summary="assessment", dimensions=())
    context = TradeContext(
        symbol="000001.SZ",
        as_of=NOW,
        candidate_status="published",
        market_validation=MarketValidation.CONTRADICTED,
        ret_60d=0.2,
        strategy_results=tuple(
            StrategyResult(
                symbol="000001.SZ",
                strategy_id=name,
                strategy_version="v1",
                as_of=NOW,
                eligible=True,
                rank_percentile=1.0,
                lineage=SnapshotLineage(),
            )
            for name in ("quality", "growth", "value")
        ),
    )
    result = engine.evaluate(
        intent=_intent(TradeProfile.POSITION),
        context=context,
        independent=independent,
        audit=audit,
        fomo_score=1,
    )
    assert result.weighted_score >= 80
    assert result.decision is TradeDecision.NO_TRADE
    assert "UPSTREAM_MARKET_CONTRADICTED" in {v.code for v in result.vetoes}
