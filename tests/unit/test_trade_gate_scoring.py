from datetime import UTC, datetime

import pytest

from astock_lens.domain.enums import TradeProfile
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.trade_gate.models import (
    DimensionJudgement,
    IndependentAssessment,
    ThesisAuditResult,
    TradeContext,
    TradeIntent,
    TradeRiskProposal,
)
from astock_lens.trade_gate.profiles import load_trade_gate_profiles
from astock_lens.trade_gate.scoring import score_event, score_position, score_swing

NOW = datetime(2026, 9, 22, 9, tzinfo=UTC)


def _intent(profile: TradeProfile, target: float | None = 115) -> TradeIntent:
    return TradeIntent(
        id="i",
        symbol="000001.SZ",
        action="ENTRY",
        profile=profile,
        thesis="thesis",
        expected_holding_days=5,
        created_at=NOW,
        risk=TradeRiskProposal(
            account_nav=100000,
            planned_entry_price=100,
            stop_loss_price=90,
            target_price=target,
            quantity=100,
            invalidation_rule="跌破90",
        ),
    )


def _judgement(name: str, ratio: float) -> DimensionJudgement:
    return DimensionJudgement(
        name=name,
        score_ratio=ratio,
        confidence=1,
        evidence=("source",),
        summary="audited",
    )


def test_event_sector_and_relative_strength_mapping() -> None:
    profiles = load_trade_gate_profiles()
    audit = ThesisAuditResult(
        dimensions=tuple(
            _judgement(n, 1)
            for n in ("catalyst_quality", "expectation_gap", "directness")
        )
    )
    context = TradeContext(
        symbol="000001.SZ",
        as_of=NOW,
        candidate_status="published",
        stock_return_1d=0.015,
        sector_return_1d=0.03,
        benchmark_return_1d=0.005,
        confirmation_met=True,
    )
    scores = score_event(
        intent=_intent(TradeProfile.EVENT),
        context=context,
        audit=audit,
        independent=IndependentAssessment(summary="ok", dimensions=()),
        profile=profiles[TradeProfile.EVENT],
    )
    values = {s.dimension: s.score for s in scores}
    assert values["sector_strength"] == 15
    assert values["relative_strength"] == pytest.approx(7.5)
    assert values["price_confirmation"] == 10


def test_swing_rr_is_reward_risk_transform() -> None:
    profiles = load_trade_gate_profiles()
    context = TradeContext(
        symbol="000001.SZ",
        as_of=NOW,
        candidate_status="published",
        ret_20d=0.1,
        ret_60d=0.2,
        confirmation_met=True,
        volume_ratio_5_20=0.8,
        relative_strength_60d=0.1,
    )
    values = {
        s.dimension: s.score
        for s in score_swing(
            intent=_intent(TradeProfile.SWING),
            context=context,
            profile=profiles[TradeProfile.SWING],
        )
    }
    assert values["risk_reward"] == pytest.approx(10 * (1.5 / 2.5))
    assert values["volume_confirmation"] == 8


def test_position_reuses_strategy_percentiles() -> None:
    profiles = load_trade_gate_profiles()
    strategies = tuple(
        StrategyResult(
            symbol="000001.SZ",
            strategy_id=name,
            strategy_version="v1",
            as_of=NOW,
            eligible=True,
            rank_percentile=value,
            lineage=SnapshotLineage(),
        )
        for name, value in (
            ("quality", 0.88),
            ("growth", 0.90),
            ("garp", 0.85),
            ("value", 0.75),
        )
    )
    context = TradeContext(
        symbol="000001.SZ",
        as_of=NOW,
        candidate_status="published",
        strategy_results=strategies,
        ret_60d=0.12,
    )
    audit = ThesisAuditResult(
        dimensions=tuple(
            _judgement(n, 0.8)
            for n in ("industry_trend", "competitiveness", "risk_resilience")
        )
    )
    values = {
        s.dimension: s.score
        for s in score_position(
            intent=_intent(TradeProfile.POSITION),
            context=context,
            audit=audit,
            profile=profiles[TradeProfile.POSITION],
        )
    }
    assert values["financial_quality"] == pytest.approx(13.2)
    assert values["earnings_growth"] == pytest.approx(13.5)
    assert values["valuation"] == pytest.approx(12.75)
    assert values["long_term_trend"] == 5
