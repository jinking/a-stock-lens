"""Trade Gate 应用服务：计划、Override、人工执行记录与复盘。"""

from datetime import UTC, datetime
from uuid import uuid4

from astock_lens.domain.enums import TradeDecision
from astock_lens.trade_gate.audit.contracts import ThesisAuditAdapter
from astock_lens.trade_gate.context import TradeContextBuilder
from astock_lens.trade_gate.engine import TradeGateEngine
from astock_lens.trade_gate.models import (
    ExecutionRecord,
    OverrideRecord,
    TradeGateEvaluation,
    TradeIntent,
    TradeMarketOverlay,
    TradePlan,
    TradeReview,
)
from astock_lens.trade_gate.store import TradeLedgerStore


class TradeGateService:
    def __init__(
        self,
        *,
        store: TradeLedgerStore,
        context_builder: TradeContextBuilder,
        audit_adapter: ThesisAuditAdapter,
        engine: TradeGateEngine,
    ) -> None:
        self.store = store
        self.context_builder = context_builder
        self.audit_adapter = audit_adapter
        self.engine = engine

    def create_and_evaluate(
        self,
        *,
        intent: TradeIntent,
        fomo_score: int,
        as_of: datetime | None = None,
        overlay: TradeMarketOverlay | None = None,
    ) -> TradeGateEvaluation:
        self.store.write_intent(intent)
        context = self.context_builder.build(
            symbol=intent.symbol, as_of=as_of or intent.created_at, overlay=overlay
        )
        facts = {
            "symbol": context.symbol,
            "candidate_status": context.candidate_status,
            "market_validation": context.market_validation.value
            if context.market_validation
            else None,
            "signal": context.signal.value if context.signal else None,
            "ret_20d": context.ret_20d,
            "ret_60d": context.ret_60d,
            "stock_return_1d": context.stock_return_1d,
            "sector_return_1d": context.sector_return_1d,
            "confirmation_met": context.confirmation_met,
        }
        independent = self.audit_adapter.independent_assessment(
            profile=intent.profile, facts=facts
        )
        audit = self.audit_adapter.audit_thesis(
            profile=intent.profile,
            facts=facts,
            independent=independent,
            user_thesis=intent.thesis,
        )
        evaluation = self.engine.evaluate(
            intent=intent,
            context=context,
            independent=independent,
            audit=audit,
            fomo_score=fomo_score,
        )
        self.store.write_evaluation(evaluation)
        return evaluation

    def create_plan(self, evaluation_id: str) -> TradePlan:
        evaluation = self._evaluation(evaluation_id)
        if evaluation.decision is not TradeDecision.PASS:
            raise ValueError("normal plan requires PASS evaluation")
        intent = self.store.read_intent(evaluation.intent_id)
        if intent is None:
            raise ValueError("evaluation intent is missing")
        plan = TradePlan(
            id=f"plan-{uuid4().hex}",
            evaluation_id=evaluation_id,
            approval_path="PASS",
            created_at=datetime.now(UTC),
            entry_price=intent.risk.planned_entry_price,
            stop_price=intent.risk.stop_loss_price,
            target_price=intent.risk.target_price,
        )
        self.store.write_plan(plan)
        return plan

    def override(
        self,
        evaluation_id: str,
        *,
        reason: str,
        evidence: tuple[str, ...],
        fomo_score: int,
        manual_position_limit_pct: float,
        manual_stop_rule: str,
        ack_risk: bool,
    ) -> OverrideRecord:
        evaluation = self._evaluation(evaluation_id)
        if not reason.strip() or not evidence or not manual_stop_rule.strip():
            raise ValueError(
                "override requires reason, evidence and explicit stop rule"
            )
        if not ack_risk:
            raise ValueError("override requires explicit risk acknowledgement")
        if not 0 <= fomo_score <= 10:
            raise ValueError("fomo_score must be within 0..10")
        if (
            manual_position_limit_pct < 0
            or manual_position_limit_pct >= evaluation.proposed_position_pct
        ):
            raise ValueError(
                "override position cap must be smaller than proposed position"
            )
        record = OverrideRecord(
            id=f"override-{uuid4().hex}",
            evaluation_id=evaluation_id,
            reason=reason,
            evidence=evidence,
            fomo_score=fomo_score,
            proposed_position_pct=evaluation.proposed_position_pct,
            manual_position_limit_pct=manual_position_limit_pct,
            manual_stop_rule=manual_stop_rule,
            ack_risk=True,
            created_at=datetime.now(UTC),
        )
        self.store.write_override(record)
        return record

    def record_execution(
        self,
        *,
        evaluation_id: str,
        fill_price: float,
        quantity: int,
        filled_at: datetime,
        plan_id: str | None = None,
        override_id: str | None = None,
    ) -> ExecutionRecord:
        evaluation = self._evaluation(evaluation_id)
        if fill_price <= 0 or quantity <= 0:
            raise ValueError("fill price and quantity must be positive")
        if (plan_id is None) == (override_id is None):
            raise ValueError("execution requires exactly one plan or override")
        if plan_id is not None:
            if evaluation.decision is not TradeDecision.PASS:
                raise ValueError("execution requires PASS or override")
            plan = self.store.read_plan(plan_id)
            if plan is None or plan.evaluation_id != evaluation_id:
                raise ValueError(
                    "execution requires a persisted plan for this evaluation"
                )
            discipline = "PASS"
        else:
            override = self.store.read_override(override_id or "")
            if override is None or override.evaluation_id != evaluation_id:
                raise ValueError(
                    "execution requires a persisted override for this evaluation"
                )
            discipline = "OVERRIDDEN"
        record = ExecutionRecord(
            id=f"execution-{uuid4().hex}",
            evaluation_id=evaluation_id,
            plan_id=plan_id,
            override_id=override_id,
            avg_fill_price=fill_price,
            filled_quantity=quantity,
            filled_at=filled_at,
            discipline_status=discipline,
        )
        self.store.write_execution(record)
        return record

    def record_review(self, review: TradeReview) -> TradeReview:
        self.store.write_review(review)
        return review

    def _evaluation(self, evaluation_id: str) -> TradeGateEvaluation:
        evaluation = self.store.read_evaluation(evaluation_id)
        if evaluation is None:
            raise ValueError(f"unknown evaluation: {evaluation_id}")
        return evaluation
