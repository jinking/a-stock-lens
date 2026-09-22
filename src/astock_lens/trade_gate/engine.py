"""Trade Gate 最终确定性裁决引擎。"""

from datetime import UTC, datetime
from uuid import uuid4

from astock_lens.domain.enums import (
    TradeDecision,
    TradeProfile,
    VetoSeverity,
)
from astock_lens.trade_gate.models import (
    IndependentAssessment,
    ThesisAuditResult,
    TradeContext,
    TradeGateEvaluation,
    TradeIntent,
)
from astock_lens.trade_gate.profiles import StrategyProfileConfig
from astock_lens.trade_gate.scoring import score_event, score_position, score_swing
from astock_lens.trade_gate.veto import evaluate_vetoes


class TradeGateEngine:
    """将规则得分、必需输入与 veto 合成为可审计决定。"""

    def __init__(self, profiles: dict[TradeProfile, StrategyProfileConfig]) -> None:
        self._profiles = profiles

    def evaluate(
        self,
        *,
        intent: TradeIntent,
        context: TradeContext,
        independent: IndependentAssessment,
        audit: ThesisAuditResult,
        fomo_score: int,
    ) -> TradeGateEvaluation:
        profile = self._profiles[intent.profile]
        if intent.profile is TradeProfile.EVENT:
            scores = score_event(
                intent=intent,
                context=context,
                audit=audit,
                independent=independent,
                profile=profile,
            )
        elif intent.profile is TradeProfile.SWING:
            scores = score_swing(intent=intent, context=context, profile=profile)
        else:
            scores = score_position(
                intent=intent,
                context=context,
                audit=audit,
                independent=independent,
                profile=profile,
            )
        vetoes = evaluate_vetoes(
            intent=intent,
            context=context,
            profile=profile,
            audit=audit,
            independent=independent,
            fomo_score=fomo_score,
        )
        total = sum(item.score for item in scores)
        expected = set(profile.weights)
        present = {item.dimension for item in scores}
        missing = sorted(expected - present)
        if intent.profile is TradeProfile.EVENT:
            for name, value in (
                ("stock_return_1d", context.stock_return_1d),
                ("sector_return_1d", context.sector_return_1d),
                ("benchmark_return_1d", context.benchmark_return_1d),
                ("confirmation_met", context.confirmation_met),
            ):
                if value is None and name not in missing:
                    missing.append(name)
        if (
            intent.profile is TradeProfile.SWING
            and intent.risk.target_price is None
            and "target_price" not in missing
        ):
            missing.append("target_price")
        hard = any(v.severity is VetoSeverity.HARD for v in vetoes)
        conditional = bool(vetoes)
        if hard:
            decision = TradeDecision.NO_TRADE
        elif missing:
            decision = TradeDecision.WAIT
        elif conditional or total >= profile.wait_threshold:
            decision = (
                TradeDecision.WAIT
                if conditional or total < profile.pass_threshold
                else TradeDecision.PASS
            )
        else:
            decision = TradeDecision.NO_TRADE
        triggers: tuple[str, ...] = ()
        if decision is TradeDecision.WAIT:
            triggers = tuple(f"补齐或确认 {name}" for name in missing) + tuple(
                f"解除 {v.code}"
                for v in vetoes
                if v.severity is VetoSeverity.CONDITIONAL
            )
            if not triggers:
                triggers = ("市场条件发生变化后重新评估",)
        return TradeGateEvaluation(
            id=f"eval-{uuid4().hex}",
            intent_id=intent.id,
            profile=intent.profile,
            profile_version=profile.version,
            dimension_scores=scores,
            weighted_score=total,
            vetoes=vetoes,
            missing_data=tuple(missing),
            decision=decision,
            reasons=tuple(v.reason for v in vetoes),
            reentry_triggers=triggers,
            context=context,
            independent_assessment=independent,
            thesis_audit=audit,
            evaluated_at=datetime.now(UTC),
            proposed_position_pct=intent.risk.position_value / intent.risk.account_nav,
        )
