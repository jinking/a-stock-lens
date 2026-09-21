"""Market regime detection engine (Option R2 multi-input regime).

Based on approved decision packet 2026-09-20:
- Market breadth ratio (stocks > MA20):
  - > 0.55: aggressive / strong breadth
  - 0.40 ~ 0.55: oscillating / range
  - < 0.40: defensive / weak breadth
- Combined with benchmark index trend (positive -> BULL / BEAR confirmation)
- Extreme volatility risk downgrades aggressive states
"""

from datetime import datetime

from astock_lens.domain.enums import MarketRegime
from astock_lens.domain.models import DomainRecord, SnapshotLineage


class MarketRegimeEvidenceIncomplete(ValueError, RuntimeError):
    """Raised when essential evidence for market regime detection is missing or incomplete."""


class MarketRegimeContext(DomainRecord):
    """Context input for market regime detection."""

    as_of: datetime
    breadth_ratio: float | None = None
    index_trend: float | None = None
    extreme_volatility: bool = False
    reasons: tuple[str, ...] = ()


class MarketRegimeResult(DomainRecord):
    """Result of market regime detection."""

    as_of: datetime
    regime: MarketRegime
    breadth_ratio: float | None = None
    index_trend: float | None = None
    reasons: tuple[str, ...] = ()
    lineage: SnapshotLineage


class MarketRegimeDetector:
    """Detects market regime state based on multi-dimensional evidence."""

    def __init__(self, *, version: str = "v1") -> None:
        self.version = version

    def detect(self, context: MarketRegimeContext) -> MarketRegimeResult:
        """Detect the market regime from context.

        Fail-closed: raises ValueError when all essential inputs are None.
        """
        breadth = context.breadth_ratio
        index_trend = context.index_trend

        if breadth is None and index_trend is None:
            raise MarketRegimeEvidenceIncomplete(
                "Missing market regime inputs: both breadth_ratio and index_trend are None"
            )

        reasons: list[str] = list(context.reasons)

        def _is_trend_up(t: float) -> bool:
            return t > 1.0 if t > 0.5 else t > 0.0

        def _is_trend_down(t: float) -> bool:
            return t < 1.0 if t > 0.5 else t < 0.0

        def _fmt_trend(t: float) -> str:
            return f"ma_20/ma_60 = {t:.4f}" if t > 0.5 else f"{t:+.2%}"

        if breadth is not None:
            if breadth > 0.55:
                if index_trend is not None and _is_trend_up(index_trend):
                    regime = MarketRegime.BULL
                    reasons.append(
                        f"全市场宽度强劲 ({breadth:.1%}) 且基准指数均线走多 ({_fmt_trend(index_trend)})"
                    )
                else:
                    regime = MarketRegime.RANGE_UP
                    reasons.append(
                        f"全市场宽度强劲 ({breadth:.1%})，指数走势中性或未单边向上"
                    )
            elif breadth >= 0.40:
                regime = MarketRegime.RANGE
                reasons.append(f"全市场宽度处于均衡震荡区间 ({breadth:.1%})")
            else:
                if index_trend is not None and _is_trend_down(index_trend):
                    regime = MarketRegime.BEAR
                    reasons.append(
                        f"全市场宽度偏弱 ({breadth:.1%}) 且基准指数下行 ({_fmt_trend(index_trend)})"
                    )
                else:
                    regime = MarketRegime.RANGE_DOWN
                    reasons.append(f"全市场宽度偏弱 ({breadth:.1%})，处于防守区间")
        else:
            # breadth is None but index_trend is available
            assert index_trend is not None
            if index_trend > 1.02 if index_trend > 0.5 else index_trend > 0.02:
                regime = MarketRegime.BULL
                reasons.append(f"基准指数单边强劲走多 ({_fmt_trend(index_trend)})")
            elif index_trend < 0.98 if index_trend > 0.5 else index_trend < -0.02:
                regime = MarketRegime.BEAR
                reasons.append(f"基准指数单边下行 ({_fmt_trend(index_trend)})")
            else:
                regime = MarketRegime.RANGE
                reasons.append(f"基准指数处于横盘震荡 ({_fmt_trend(index_trend)})")

        # 极端波动率降级检查
        if context.extreme_volatility:
            reasons.append("触发宏观极端波动率预警，下调激进偏多等级防范踩踏风险")
            if regime == MarketRegime.BULL:
                regime = MarketRegime.RANGE_UP
            elif regime == MarketRegime.RANGE_UP:
                regime = MarketRegime.RANGE

        return MarketRegimeResult(
            as_of=context.as_of,
            regime=regime,
            breadth_ratio=breadth,
            index_trend=index_trend,
            reasons=tuple(reasons),
            lineage=SnapshotLineage(regime_version=self.version),
        )
