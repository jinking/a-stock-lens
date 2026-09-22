"""Market validation 5-dimension matrix engine.

Based on approved decision packet 2026-09-20:
- 5 Dimensions:
  1. Stock Trend: ret_20d, proximity_52w_high (strategy-differentiated)
  2. Industry Trend: industry_excess_return
  3. Relative Strength: relative_strength_60d
  4. Volume/Price: vol_ratio
  5. Liquidity Floor: avg_amount_20d (hard veto threshold: < 1.0e8)
- State Matrix:
  - CONTRADICTED: avg_amount_20d < 1.0e8 or negative_count >= 2 (vetoed)
  - CONFIRMED: avg_amount_20d >= 1.5e8, stock trend is positive, and negative_count == 0
  - NEUTRAL: in-between states
"""

from datetime import datetime

from astock_lens.domain.enums import DataStatus, MarketValidation
from astock_lens.domain.models import DomainRecord, SnapshotLineage
from astock_lens.factors.contracts import FactorResult


class MarketValidationEvidenceIncomplete(RuntimeError):
    """Raised when required 5-dimension market validation inputs are missing or incomplete."""


class MarketValidationContext(DomainRecord):
    """Context input for market validation."""

    symbol: str
    strategy_id: str
    as_of: datetime
    factors: tuple[FactorResult, ...] = ()
    industry_excess_return: float | None = None
    vol_ratio: float | None = None
    relative_strength_60d: float | None = None


class MarketValidationResult(DomainRecord):
    """Outcome of market validation."""

    symbol: str
    strategy_id: str
    as_of: datetime
    status: MarketValidation
    positive_count: int
    negative_count: int
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    lineage: SnapshotLineage


class MarketValidator:
    """Evaluates a candidate stock against the 5-dimension market validation matrix."""

    def __init__(self, *, version: str = "v1") -> None:
        self.version = version

    def validate(self, context: MarketValidationContext) -> MarketValidationResult:
        """Validate market behaviour for a given symbol and strategy."""
        if not context.strategy_id:
            raise ValueError(
                f"Market validation requires an explicit strategy_id for {context.symbol}, got {context.strategy_id!r}"
            )

        factor_map: dict[str, FactorResult] = {
            f.factor: f
            for f in context.factors
            if f.status == DataStatus.VALUE and f.raw_value is not None
        }

        missing: list[str] = []
        if factor_map.get("ret_20d") is None:
            missing.append("ret_20d")
        if (
            context.strategy_id == "momentum"
            and factor_map.get("proximity_52w_high") is None
        ):
            missing.append("proximity_52w_high")
        if factor_map.get("avg_amount_20d") is None:
            missing.append("avg_amount_20d")
        if context.industry_excess_return is None:
            missing.append("industry_excess_return_20d")
        if context.relative_strength_60d is None:
            missing.append("relative_strength_60d")
        if context.vol_ratio is None:
            missing.append("volume_ratio_5_20")
        if missing:
            raise MarketValidationEvidenceIncomplete(
                f"{context.symbol} missing required 5D evidence: {', '.join(missing)}"
            )

        reasons: list[str] = []
        risks: list[str] = []
        positive_count = 0
        negative_count = 0

        # 1. 维度 5: 流动性底线 (优先检查一票否决警戒线)
        avg_amount = float(factor_map["avg_amount_20d"].raw_value)  # type: ignore[arg-type]
        liquidity_vetoed = False
        if avg_amount < 100_000_000.0:  # < 1.0 亿元
            liquidity_vetoed = True
            negative_count += 1
            risks.append(
                f"20日均成交额 ({avg_amount / 1e8:.2f}亿) 击穿 1.0 亿元流动性警戒线，触发一票否决"
            )
        elif avg_amount >= 150_000_000.0:  # >= 1.5 亿元
            positive_count += 1
            reasons.append(
                f"流动性充沛 (20日均成交额 {avg_amount / 1e8:.2f}亿 >= 1.5亿)"
            )
        else:
            reasons.append(
                f"流动性处于观察区间 (20日均成交额 {avg_amount / 1e8:.2f}亿)"
            )

        # 2. 维度 1: 个股趋势
        ret_20d = float(factor_map["ret_20d"].raw_value)  # type: ignore[arg-type]
        stock_trend_positive = False

        if context.strategy_id == "momentum":
            prox = float(factor_map["proximity_52w_high"].raw_value)  # type: ignore[arg-type]
            if ret_20d > 0.064 and prox > 0.85:
                positive_count += 1
                stock_trend_positive = True
                reasons.append(
                    f"动量趋势强劲 (20日涨幅 {ret_20d:+.2%}, 距高点 {prox:.2f})"
                )
            elif ret_20d < 0.0 or prox < 0.80:
                negative_count += 1
                risks.append(
                    f"动量结构破坏 (20日涨幅 {ret_20d:+.2%}, 距高点 {prox:.2f})"
                )
        else:
            if ret_20d > 0.0:
                positive_count += 1
                stock_trend_positive = True
                reasons.append(f"短期走势向好 (20日涨幅 {ret_20d:+.2%})")
            elif ret_20d < -0.15:
                negative_count += 1
                risks.append(f"短期破位大跌 (20日跌幅 {ret_20d:+.2%})")
            else:
                reasons.append(f"短期震荡调整中 (20日涨幅 {ret_20d:+.2%})")

        # 3. 维度 2: 板块/行业超额
        industry_excess = context.industry_excess_return
        assert industry_excess is not None
        if industry_excess > 0.0:
            positive_count += 1
            reasons.append(f"所属行业具备超额收益 ({industry_excess:+.2%})")
        elif industry_excess < -0.05:
            negative_count += 1
            risks.append(f"所属行业处于严重退潮期 ({industry_excess:+.2%})")

        # 4. 维度 3: 相对强弱
        rel_str = context.relative_strength_60d
        assert rel_str is not None
        if rel_str > 0.0:
            positive_count += 1
            reasons.append(f"相对基准超额向上 (相对强弱 {rel_str:+.2%})")
        elif rel_str < -0.15:
            negative_count += 1
            risks.append(f"相对基准大幅落后 (相对强弱 {rel_str:+.2%})")
        else:
            reasons.append(f"相对基准表现平稳 (相对强弱 {rel_str:+.2%})")

        # 5. 维度 4: 量价配合
        vol_ratio = context.vol_ratio
        assert vol_ratio is not None
        if vol_ratio > 1.05:
            positive_count += 1
            reasons.append(f"量价配合放量 (量比 {vol_ratio:.2f})")
        elif vol_ratio < 0.70:
            negative_count += 1
            risks.append(f"成交量急剧萎缩 (量比 {vol_ratio:.2f})")

        # 判定状态矩阵
        if liquidity_vetoed or negative_count >= 2:
            status = MarketValidation.CONTRADICTED
        elif not liquidity_vetoed and stock_trend_positive and negative_count == 0:
            status = MarketValidation.CONFIRMED
        else:
            status = MarketValidation.NEUTRAL

        return MarketValidationResult(
            symbol=context.symbol,
            strategy_id=context.strategy_id,
            as_of=context.as_of,
            status=status,
            positive_count=positive_count,
            negative_count=negative_count,
            reasons=tuple(reasons),
            risks=tuple(risks),
            lineage=SnapshotLineage(market_validation_version=self.version),
        )
