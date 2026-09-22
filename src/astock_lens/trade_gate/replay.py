"""基于已保存上下文与 AI 判断的离线规则回放。"""

from uuid import uuid4

from astock_lens.domain.enums import TradeDecision, VetoSeverity
from astock_lens.trade_gate.models import TradeGateEvaluation
from astock_lens.trade_gate.profiles import StrategyProfileConfig


def replay_evaluation(
    original: TradeGateEvaluation, *, profile: StrategyProfileConfig
) -> TradeGateEvaluation:
    weights = profile.weights
    dimensions = tuple(
        item.model_copy(
            update={
                "weight": weights.get(item.dimension, item.weight),
                "score": weights.get(item.dimension, item.weight) * item.ratio,
            }
        )
        for item in original.dimension_scores
    )
    score = sum(item.score for item in dimensions)
    hard = any(v.active and v.severity is VetoSeverity.HARD for v in original.vetoes)
    conditional = any(
        v.active and v.severity is VetoSeverity.CONDITIONAL for v in original.vetoes
    )
    if hard or score < profile.wait_threshold:
        decision = TradeDecision.NO_TRADE
    elif conditional or score < profile.pass_threshold or original.missing_data:
        decision = TradeDecision.WAIT
    else:
        decision = TradeDecision.PASS
    triggers = original.reentry_triggers
    if decision is TradeDecision.WAIT and not triggers:
        triggers = ("基于当前保存证据重新核验条件",)
    return original.model_copy(
        update={
            "id": f"eval-{uuid4().hex}",
            "profile_version": profile.version,
            "rule_set_version": "v1",
            "dimension_scores": dimensions,
            "weighted_score": score,
            "decision": decision,
            "reentry_triggers": triggers,
            "replayed_from_evaluation_id": original.id,
        }
    )
