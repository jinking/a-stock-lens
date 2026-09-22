"""交易准入系统的不可变领域记录。"""

from datetime import datetime
from typing import Self

from pydantic import computed_field, model_validator

from astock_lens.domain.enums import (
    MarketValidation,
    Signal,
    TradeAction,
    TradeDecision,
    TradeIntentStatus,
    TradeProfile,
    VetoSeverity,
)
from astock_lens.domain.models import DomainRecord, SnapshotLineage


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class TradeRiskProposal(DomainRecord):
    account_nav: float
    planned_entry_price: float
    stop_loss_price: float
    quantity: int
    invalidation_rule: str
    target_price: float | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if (
            self.account_nav <= 0
            or self.planned_entry_price <= 0
            or self.stop_loss_price <= 0
        ):
            raise ValueError("account_nav and prices must be positive")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.stop_loss_price >= self.planned_entry_price:
            raise ValueError("V1 long trade stop must be below entry")
        if not self.invalidation_rule.strip():
            raise ValueError("invalidation_rule must not be empty")
        if self.target_price is not None and self.target_price <= 0:
            raise ValueError("target_price must be positive")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def position_value(self) -> float:
        return self.planned_entry_price * self.quantity

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_loss_amount(self) -> float:
        return (self.planned_entry_price - self.stop_loss_price) * self.quantity

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_loss_pct_of_nav(self) -> float:
        return self.max_loss_amount / self.account_nav


class ExistingPositionSnapshot(DomainRecord):
    quantity: int
    avg_cost: float
    current_price: float
    captured_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _aware("captured_at", self.captured_at)
        if self.quantity <= 0 or self.avg_cost <= 0 or self.current_price <= 0:
            raise ValueError("existing position values must be positive")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_losing(self) -> bool:
        return self.current_price < self.avg_cost


class TradeIntent(DomainRecord):
    id: str
    symbol: str
    action: TradeAction
    profile: TradeProfile
    thesis: str
    catalyst: str | None = None
    expected_holding_days: int
    created_at: datetime
    risk: TradeRiskProposal
    existing_position: ExistingPositionSnapshot | None = None
    new_independent_confirmation: str | None = None
    status: TradeIntentStatus = TradeIntentStatus.DRAFT

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _aware("created_at", self.created_at)
        if not self.id.strip() or not self.symbol.strip() or not self.thesis.strip():
            raise ValueError("id, symbol and thesis must not be empty")
        if self.expected_holding_days <= 0:
            raise ValueError("expected_holding_days must be positive")
        if self.action is TradeAction.ADD and self.existing_position is None:
            raise ValueError("ADD requires existing_position")
        return self


class TradeMarketOverlay(DomainRecord):
    captured_at: datetime
    current_price: float | None = None
    stock_return_1d: float | None = None
    sector_return_1d: float | None = None
    benchmark_return_1d: float | None = None
    volume_ratio_current: float | None = None
    confirmation_met: bool | None = None
    confirmation_note: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _aware("captured_at", self.captured_at)
        return self


class TradeContext(DomainRecord):
    symbol: str
    as_of: datetime
    candidate_status: str
    candidate: object | None = None
    factor_results: tuple[object, ...] = ()
    strategy_results: tuple[object, ...] = ()
    market_validation: MarketValidation | None = None
    signal: Signal | None = None
    lineage: SnapshotLineage = SnapshotLineage()
    overlay: TradeMarketOverlay | None = None
    ret_20d: float | None = None
    ret_60d: float | None = None
    volume_ratio_5_20: float | None = None
    relative_strength_60d: float | None = None
    stock_return_1d: float | None = None
    sector_return_1d: float | None = None
    benchmark_return_1d: float | None = None
    confirmation_met: bool | None = None
    current_price: float | None = None

    @model_validator(mode="after")
    def _validate_time(self) -> Self:
        _aware("as_of", self.as_of)
        return self


class DimensionJudgement(DomainRecord):
    name: str
    score_ratio: float
    confidence: float
    evidence: tuple[str, ...]
    summary: str
    source_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if not 0 <= self.score_ratio <= 1 or not 0 <= self.confidence <= 1:
            raise ValueError("score_ratio and confidence must be within 0..1")
        if not self.evidence or not self.summary.strip():
            raise ValueError("AI judgement requires evidence and summary")
        return self


class IndependentAssessment(DomainRecord):
    summary: str
    dimensions: tuple[DimensionJudgement, ...]
    risks: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


class ThesisAuditResult(DomainRecord):
    dimensions: tuple[DimensionJudgement, ...]
    priced_in: bool | None = None
    supporting_evidence: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    missing_assumptions: tuple[str, ...] = ()


class VetoResult(DomainRecord):
    code: str
    severity: VetoSeverity
    reason: str
    active: bool = True


class DimensionScore(DomainRecord):
    dimension: str
    weight: float
    ratio: float
    score: float
    source: str
    evidence: tuple[str, ...] = ()


class TradeGateEvaluation(DomainRecord):
    id: str
    intent_id: str
    profile: TradeProfile
    profile_version: str
    rule_set_version: str = "v1"
    prompt_version: str | None = None
    model_id: str | None = None
    dimension_scores: tuple[DimensionScore, ...]
    weighted_score: float
    vetoes: tuple[VetoResult, ...] = ()
    missing_data: tuple[str, ...] = ()
    decision: TradeDecision
    reasons: tuple[str, ...] = ()
    reentry_triggers: tuple[str, ...] = ()
    context: TradeContext
    independent_assessment: IndependentAssessment
    thesis_audit: ThesisAuditResult
    evaluated_at: datetime
    proposed_position_pct: float = 0.0
    replayed_from_evaluation_id: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _aware("evaluated_at", self.evaluated_at)
        if not 0 <= self.weighted_score <= 100:
            raise ValueError("weighted_score must be within 0..100")
        if self.decision is TradeDecision.WAIT and not self.reentry_triggers:
            raise ValueError("WAIT requires reentry_triggers")
        return self


class TradePlan(DomainRecord):
    id: str
    evaluation_id: str
    approval_path: str
    created_at: datetime
    entry_price: float
    stop_price: float
    target_price: float | None = None


class OverrideRecord(DomainRecord):
    id: str
    evaluation_id: str
    reason: str
    evidence: tuple[str, ...]
    fomo_score: int
    proposed_position_pct: float
    manual_position_limit_pct: float
    manual_stop_rule: str
    ack_risk: bool
    created_at: datetime


class ExecutionRecord(DomainRecord):
    id: str
    evaluation_id: str
    plan_id: str | None = None
    override_id: str | None = None
    avg_fill_price: float
    filled_quantity: int
    filled_at: datetime
    discipline_status: str


class TradeReview(DomainRecord):
    id: str
    execution_id: str
    pnl_amount: float
    pnl_pct: float
    max_drawdown: float
    max_adverse_excursion: float
    max_favorable_excursion: float
    thesis_correct: bool
    gate_correct: bool
    discipline_followed: bool
    lessons_learned: str
    reviewed_at: datetime
