"""Stock-side market evidence.

Extracts auditable market evidence directly from validated factors and historical bars.
Guarantees:
- Volume ratio is strictly computed from the latest 20 valid trade bars on or before as_of;
- If valid bars < 20, volume_ratio_5_20 is None (never silently 0 or 1.0);
- Factors are cleanly extracted and missing/invalid values remain None.
"""

from collections.abc import Sequence
from datetime import datetime

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DailyBar, DomainRecord
from astock_lens.factors.contracts import FactorResult


class StockMarketEvidence(DomainRecord):
    """Auditable stock-level market evidence for validation and candidate ranking."""

    symbol: str
    as_of: datetime
    ret_20d: float | None = None
    proximity_52w_high: float | None = None
    avg_amount_20d: float | None = None
    volume_ratio_5_20: float | None = None


def build_stock_market_evidence(
    *,
    symbol: str,
    factors: Sequence[FactorResult],
    bars: Sequence[DailyBar],
    as_of: datetime,
) -> StockMarketEvidence:
    """Build auditable market evidence for a given symbol."""
    cutoff_date = as_of.date()

    # 1. Filter and sort bars on or before as_of
    valid_bars = [
        bar
        for bar in bars
        if bar.symbol == symbol
        and bar.trade_date <= cutoff_date
        and bar.volume is not None
        and bar.volume > 0
    ]
    valid_bars.sort(key=lambda b: b.trade_date)

    volume_ratio_5_20: float | None = None
    if len(valid_bars) >= 20:
        recent_20 = valid_bars[-20:]
        recent_5 = valid_bars[-5:]
        vol_20_mean = sum(b.volume for b in recent_20 if b.volume is not None) / 20.0
        vol_5_mean = sum(b.volume for b in recent_5 if b.volume is not None) / 5.0
        if vol_20_mean > 0:
            volume_ratio_5_20 = vol_5_mean / vol_20_mean

    # 2. Extract factors
    factor_map: dict[str, float | None] = {}
    for f in factors:
        if f.symbol == symbol and f.status == DataStatus.VALUE:
            factor_map[f.factor] = f.raw_value

    return StockMarketEvidence(
        symbol=symbol,
        as_of=as_of,
        ret_20d=factor_map.get("ret_20d"),
        proximity_52w_high=factor_map.get("proximity_52w_high"),
        avg_amount_20d=factor_map.get("avg_amount_20d"),
        volume_ratio_5_20=volume_ratio_5_20,
    )
