"""Benchmark market evidence contract and calculator.

Auditable evidence layer: provides benchmark index performance (ret_60d and trend_value)
for Market Regime (R2) and Market Validation.

Guarantees:
- If approved benchmark data is unavailable or insufficient (< 60 valid bars), raises BenchmarkEvidenceUnavailable;
- Never invents synthetic fallback or substitutes Research Universe median;
- Calculates ret_60d and trend_value (ma_20 / ma_60) deterministically from verified bars on or before as_of.
"""

from collections.abc import Sequence
from datetime import datetime

from astock_lens.domain.models import DailyBar, DomainRecord


class BenchmarkEvidenceUnavailable(RuntimeError):
    """Raised when approved benchmark series or bars are unavailable or insufficient."""


class BenchmarkEvidence(DomainRecord):
    """Auditable benchmark index evidence."""

    benchmark_id: str
    as_of: datetime
    ret_60d: float
    trend_value: float
    source: str


def compute_benchmark_evidence(
    *,
    benchmark_id: str,
    bars: Sequence[DailyBar],
    as_of: datetime,
    source: str = "canonical_index_bars",
) -> BenchmarkEvidence:
    """Compute benchmark evidence from validated benchmark daily bars.

    Definitions:
    - ret_60d = (close_latest / close_60d_ago) - 1.0 (requires >= 60 valid trading bars on/before as_of)
    - trend_value = ma_20 / ma_60 (ratio of 20-day simple moving average to 60-day simple moving average)
    """
    cutoff_date = as_of.date()
    valid_bars = [
        bar
        for bar in bars
        if bar.trade_date <= cutoff_date and bar.close is not None and bar.close > 0
    ]
    valid_bars.sort(key=lambda b: b.trade_date)

    if len(valid_bars) < 60:
        raise BenchmarkEvidenceUnavailable(
            f"Insufficient benchmark bars for {benchmark_id}: requires at least 60 valid bars, "
            f"found {len(valid_bars)} on or before {cutoff_date}"
        )

    recent_60 = valid_bars[-60:]
    close_latest = recent_60[-1].close
    close_60_ago = recent_60[0].close
    if close_latest is None or close_60_ago is None or close_60_ago <= 0:
        raise BenchmarkEvidenceUnavailable(
            f"Invalid close prices for benchmark {benchmark_id} within 60-day window"
        )

    ret_60d = (close_latest - close_60_ago) / close_60_ago

    recent_20 = valid_bars[-20:]
    ma_20 = sum(b.close for b in recent_20 if b.close is not None) / 20.0
    ma_60 = sum(b.close for b in recent_60 if b.close is not None) / 60.0

    if ma_60 <= 0:
        raise BenchmarkEvidenceUnavailable(
            f"Non-positive 60-day moving average for benchmark {benchmark_id}"
        )

    trend_value = ma_20 / ma_60

    return BenchmarkEvidence(
        benchmark_id=benchmark_id,
        as_of=as_of,
        ret_60d=ret_60d,
        trend_value=trend_value,
        source=source,
    )
