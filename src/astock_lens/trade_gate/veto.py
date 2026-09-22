"""交易准入的显式否决规则。"""

from astock_lens.domain.enums import (
    MarketValidation,
    Signal,
    TradeAction,
    TradeProfile,
    VetoSeverity,
)
from astock_lens.trade_gate.models import (
    IndependentAssessment,
    ThesisAuditResult,
    TradeContext,
    TradeIntent,
    VetoResult,
)
from astock_lens.trade_gate.profiles import StrategyProfileConfig


def evaluate_vetoes(
    *,
    intent: TradeIntent,
    context: TradeContext,
    profile: StrategyProfileConfig,
    audit: ThesisAuditResult,
    fomo_score: int,
    independent: IndependentAssessment | None = None,
) -> tuple[VetoResult, ...]:
    hits: list[VetoResult] = []

    def add(code: str, severity: VetoSeverity, reason: str) -> None:
        if code in profile.enabled_vetoes:
            hits.append(VetoResult(code=code, severity=severity, reason=reason))

    if not intent.risk.invalidation_rule.strip():
        add("NO_INVALIDATION", VetoSeverity.HARD, "未提供明确失效条件")
    if intent.risk.account_nav <= 0 or intent.risk.quantity <= 0:
        add("NO_RISK_BUDGET", VetoSeverity.HARD, "无法计算风险预算")
    if context.market_validation is MarketValidation.CONTRADICTED:
        add("UPSTREAM_MARKET_CONTRADICTED", VetoSeverity.HARD, "上游市场验证相矛盾")
    if context.signal is Signal.BREAKDOWN:
        add("UPSTREAM_BREAKDOWN", VetoSeverity.HARD, "上游信号为 BREAKDOWN")
    if (
        intent.action is TradeAction.ADD
        and intent.existing_position
        and intent.existing_position.is_losing
        and not (intent.new_independent_confirmation or "").strip()
    ):
        add(
            "AVERAGING_DOWN_WITHOUT_SIGNAL",
            VetoSeverity.HARD,
            "亏损头寸加仓缺少新的独立确认",
        )
    if (
        context.sector_return_1d is not None
        and context.stock_return_1d is not None
        and context.sector_return_1d > 0
        and context.stock_return_1d <= 0
    ):
        add("RELATIVE_WEAKNESS", VetoSeverity.CONDITIONAL, "板块上涨而个股当日未上涨")
    if (
        intent.profile in (TradeProfile.EVENT, TradeProfile.SWING)
        and context.confirmation_met is not True
    ):
        add("NO_PRICE_CONFIRMATION", VetoSeverity.CONDITIONAL, "盘中价格确认尚未成立")
    if not 0 <= fomo_score <= 10:
        raise ValueError("fomo_score must be within 0..10")
    if fomo_score >= profile.fomo_wait_threshold:
        add("EXTREME_FOMO", VetoSeverity.CONDITIONAL, "FOMO 达到画像冷静阈值")
    if intent.profile is TradeProfile.EVENT and audit.priced_in is True:
        add(
            "EXPECTATION_ALREADY_PRICED",
            VetoSeverity.CONDITIONAL,
            "催化已被市场提前定价",
        )
    return tuple(hits)
