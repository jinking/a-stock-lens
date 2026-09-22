"""三种交易画像的纯确定性评分函数。"""

from collections.abc import Mapping

from astock_lens.domain.enums import MarketValidation
from astock_lens.trade_gate.audit.cli import adjusted_ratio
from astock_lens.trade_gate.models import (
    DimensionScore,
    IndependentAssessment,
    ThesisAuditResult,
    TradeContext,
    TradeIntent,
)
from astock_lens.trade_gate.profiles import StrategyProfileConfig


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _strategy_values(context: TradeContext) -> dict[str, float]:
    values: dict[str, float] = {}
    for result in context.strategy_results:
        strategy_id = getattr(result, "strategy_id", None)
        percentile = getattr(result, "rank_percentile", None)
        eligible = getattr(result, "eligible", False)
        if strategy_id and eligible and percentile is not None:
            values[str(strategy_id).lower()] = float(percentile)
    return values


def _qual_values(context: TradeContext) -> dict[str, float]:
    candidate = context.candidate
    result: dict[str, float] = {}
    for item in getattr(candidate, "strategy_qualifications", ()):
        if getattr(item, "qualified", False):
            result[str(item.strategy_id).lower()] = float(item.rank_percentile)
    return result


def _ai_values(
    audit: ThesisAuditResult, independent: IndependentAssessment
) -> dict[str, tuple[float, tuple[str, ...]]]:
    values = {j.name: (adjusted_ratio(j), j.evidence) for j in independent.dimensions}
    values.update({j.name: (adjusted_ratio(j), j.evidence) for j in audit.dimensions})
    return values


def _scores(
    weights: Mapping[str, float],
    ratios: Mapping[str, tuple[float | None, str, tuple[str, ...]]],
) -> tuple[DimensionScore, ...]:
    output = []
    for name, weight in weights.items():
        item = ratios.get(name)
        if item is None or item[0] is None:
            continue
        ratio, source, evidence = item
        if ratio is None:
            continue
        bounded = clamp(ratio)
        output.append(
            DimensionScore(
                dimension=name,
                weight=weight,
                ratio=bounded,
                score=weight * bounded,
                source=source,
                evidence=evidence,
            )
        )
    return tuple(output)


def score_event(
    *,
    intent: TradeIntent,
    context: TradeContext,
    audit: ThesisAuditResult,
    profile: StrategyProfileConfig,
    independent: IndependentAssessment | None = None,
) -> tuple[DimensionScore, ...]:
    ai = _ai_values(
        audit, independent or IndependentAssessment(summary="", dimensions=())
    )
    sector, stock = context.sector_return_1d, context.stock_return_1d
    relative = (
        (
            clamp(stock / sector)
            if stock is not None and sector is not None and sector > 0
            else (
                1.0
                if stock is not None and sector is not None and stock > sector
                else 0.0
            )
        )
        if stock is not None and sector is not None
        else None
    )
    ratios: dict[str, tuple[float | None, str, tuple[str, ...]]] = {
        name: (value[0], "AI", value[1]) for name, value in ai.items()
    }
    ratios.update(
        {
            "sector_strength": (
                (1.0 if sector > context.benchmark_return_1d else 0.0, "RULE", ())
                if sector is not None and context.benchmark_return_1d is not None
                else (None, "RULE", ())
            ),
            "relative_strength": (relative, "RULE", ()),
            "price_confirmation": (
                (1.0 if context.confirmation_met else 0.0, "RULE", ())
                if context.confirmation_met is not None
                else (None, "RULE", ())
            ),
            "risk_plan": (
                (1.0, "RULE", ("risk proposal complete",))
                if (intent.risk.invalidation_rule or "").strip()
                else (0.0, "RULE", ("invalidation rule missing",))
            ),
        }
    )
    return _scores(profile.weights, ratios)


def score_swing(
    *, intent: TradeIntent, context: TradeContext, profile: StrategyProfileConfig
) -> tuple[DimensionScore, ...]:
    strategies, qualifications = _strategy_values(context), _qual_values(context)
    best = max(qualifications.values(), default=None)
    if best is None:
        best = max((v for v in strategies.values()), default=None)
    ret20, ret60 = context.ret_20d, context.ret_60d
    volume = (
        context.volume_ratio_5_20
        if context.volume_ratio_5_20 is not None
        else (context.overlay.volume_ratio_current if context.overlay else None)
    )
    rr = None
    target = intent.risk.target_price
    if target is not None:
        reward = target - intent.risk.planned_entry_price
        loss = intent.risk.planned_entry_price - intent.risk.stop_loss_price
        if reward > 0 and loss > 0:
            raw_rr = reward / loss
            rr = raw_rr / (1 + raw_rr)
    ratios = {
        "fundamental_support": (best, "RULE", ()),
        "sector_trend": (
            (
                {
                    MarketValidation.CONFIRMED: 1.0,
                    MarketValidation.NEUTRAL: 0.5,
                    MarketValidation.CONTRADICTED: 0.0,
                }[context.market_validation],
                "RULE",
                (),
            )
            if context.market_validation is not None
            else (None, "RULE", ())
        ),
        "stock_trend": (
            ((float(ret20 > 0) + float(ret60 > 0)) / 2, "RULE", ())
            if ret20 is not None and ret60 is not None
            else (None, "RULE", ())
        ),
        "key_level": (
            (1.0 if context.confirmation_met else 0.0, "RULE", ())
            if context.confirmation_met is not None
            else (None, "RULE", ())
        ),
        "volume_confirmation": (
            (clamp(volume), "RULE", ()) if volume is not None else (None, "RULE", ())
        ),
        "relative_strength": (
            (1.0 if context.relative_strength_60d > 0 else 0.0, "RULE", ())
            if context.relative_strength_60d is not None
            else (None, "RULE", ())
        ),
        "risk_reward": (rr, "RULE", ()),
    }
    return _scores(profile.weights, ratios)


def score_position(
    *,
    intent: TradeIntent,
    context: TradeContext,
    audit: ThesisAuditResult,
    profile: StrategyProfileConfig,
    independent: IndependentAssessment | None = None,
) -> tuple[DimensionScore, ...]:
    strategies = _strategy_values(context)
    growth = max(
        (strategies[k] for k in ("growth", "garp") if k in strategies), default=None
    )
    value = max(
        (strategies[k] for k in ("value", "garp") if k in strategies), default=None
    )
    ai = _ai_values(
        audit, independent or IndependentAssessment(summary="", dimensions=())
    )
    ratios: dict[str, tuple[float | None, str, tuple[str, ...]]] = {
        name: (v, "AI", ev) for name, (v, ev) in ai.items()
    }
    ratios.update(
        {
            "financial_quality": (strategies.get("quality"), "RULE", ()),
            "earnings_growth": (growth, "RULE", ()),
            "valuation": (value, "RULE", ()),
            "long_term_trend": (
                (1.0 if context.ret_60d > 0 else 0.0, "RULE", ())
                if context.ret_60d is not None
                else (None, "RULE", ())
            ),
            "execution": (
                (1.0, "RULE", ("risk proposal complete",))
                if (intent.risk.invalidation_rule or "").strip()
                else (0.0, "RULE", ("invalidation rule missing",))
            ),
        }
    )
    return _scores(profile.weights, ratios)
