"""Default multi-strategy market state signal detector.

Based on approved decision packet 2026-09-20:
- Signals describe market state, never buy/sell recommendations.
- Rules:
  - BREAKDOWN: ret_20d < -15%
  - TREND_WEAKEN: ret_60d > 15% but ret_20d < -5%
  - Momentum BREAKOUT: proximity_52w_high >= 0.95
  - Momentum PULLBACK: ret_60d >= 20% and 0% <= ret_20d <= 5%
  - Momentum TREND_CONTINUE: ret_20d >= 6.4% and 0.85 <= proximity_52w_high < 0.95
  - Value/Dividend DIVIDEND_SUPPORT: dividend_yield_ttm >= 3.0% and ret_20d > -5%
  - Value/Dividend VALUE_CONTRARIAN: -5% <= ret_20d <= +2%
  - NO_SIGNAL: default
"""

from astock_lens.domain.enums import DataStatus, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.signals.contracts import SignalContext, SignalResult


class DefaultSignalDetector:
    """Default signal detector mapping factor evidence to market state signals."""

    def __init__(self, *, version: str = "v1") -> None:
        self.version = version

    def detect(self, context: SignalContext) -> SignalResult:
        """Detect the market state signal for the symbol."""
        factor_map: dict[str, FactorResult] = {
            f.factor: f
            for f in context.factors
            if f.status == DataStatus.VALUE and f.raw_value is not None
        }

        ret_20d_res = factor_map.get("ret_20d")
        ret_60d_res = factor_map.get("ret_60d")
        prox_res = factor_map.get("proximity_52w_high")
        div_res = factor_map.get("dividend_yield_ttm")

        ret_20d = (
            float(ret_20d_res.raw_value)
            if ret_20d_res is not None and ret_20d_res.raw_value is not None
            else None
        )
        ret_60d = (
            float(ret_60d_res.raw_value)
            if ret_60d_res is not None and ret_60d_res.raw_value is not None
            else None
        )
        prox = (
            float(prox_res.raw_value)
            if prox_res is not None and prox_res.raw_value is not None
            else None
        )
        div_yield = (
            float(div_res.raw_value)
            if div_res is not None and div_res.raw_value is not None
            else None
        )

        signal = Signal.NO_SIGNAL
        reasons: list[str] = []

        # 1. 优先判定通用严重破位
        if ret_20d is not None and ret_20d < -0.15:
            signal = Signal.BREAKDOWN
            reasons.append(f"短期破位加速下行 (20日跌幅 {ret_20d:+.2%})")

        # 2. 中期走强但短期显著转弱
        elif (
            ret_60d is not None
            and ret_60d > 0.15
            and ret_20d is not None
            and ret_20d < -0.05
        ):
            signal = Signal.TREND_WEAKEN
            reasons.append(
                f"中期强势但短期明显走弱 (60日涨幅 {ret_60d:+.2%}, 20日跌幅 {ret_20d:+.2%})"
            )

        # 3. 策略特定技术特征判定
        elif context.strategy_id in ("momentum", None):
            if prox is not None and prox >= 0.95:
                signal = Signal.BREAKOUT
                reasons.append(f"向上突破一年新高区域 (距52周最高点 {prox:.2f})")
            elif (
                ret_60d is not None
                and ret_60d >= 0.20
                and ret_20d is not None
                and 0.0 <= ret_20d <= 0.05
            ):
                signal = Signal.PULLBACK
                reasons.append(
                    f"中期强势良性技术回踩 (60日涨幅 {ret_60d:+.2%}, 20日窄幅整理 {ret_20d:+.2%})"
                )
            elif (
                ret_20d is not None
                and ret_20d >= 0.064
                and prox is not None
                and 0.85 <= prox < 0.95
            ):
                signal = Signal.TREND_CONTINUE
                reasons.append(
                    f"上升通道强趋势持续 (20日涨幅 {ret_20d:+.2%}, 距高点 {prox:.2f})"
                )

        if signal == Signal.NO_SIGNAL and context.strategy_id in (
            "value",
            "dividend",
            None,
        ):
            if (
                div_yield is not None
                and div_yield >= 3.0
                and ret_20d is not None
                and ret_20d > -0.05
            ):
                signal = Signal.DIVIDEND_SUPPORT
                reasons.append(
                    f"高股息防御底仓特征 (股息率TTM {div_yield:.2f}%, 20日收益率 {ret_20d:+.2%})"
                )
            elif ret_20d is not None and -0.05 <= ret_20d <= 0.02:
                signal = Signal.VALUE_CONTRARIAN
                reasons.append(f"低估值区间筑底企稳 (20日收益率 {ret_20d:+.2%})")

        if not reasons:
            reasons.append("当前技术特征处于中性无特殊形态")

        return SignalResult(
            symbol=context.symbol,
            signal=signal,
            as_of=context.as_of,
            reasons=tuple(reasons),
            lineage=SnapshotLineage(signal_version=self.version),
        )
