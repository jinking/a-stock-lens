"""Benchmark market evidence unit tests.

Auditable benchmark evidence tests:
- Strict fail-closed when benchmark series or bars are insufficient (< 60 bars);
- Deterministic calculation of ret_60d and trend_value (ma_20 / ma_60);
- No future bar leakage.
"""

from datetime import UTC, datetime, timedelta

import pytest

from astock_lens.domain.models import DailyBar
from astock_lens.market.benchmark import (
    BenchmarkEvidence,
    BenchmarkEvidenceUnavailable,
    compute_benchmark_evidence,
)

AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def _benchmark_bar(
    day_offset: int, close: float, benchmark_id: str = "000300.SH"
) -> DailyBar:
    trade_date = AS_OF.date() - timedelta(days=100 - day_offset)
    return DailyBar(
        symbol=benchmark_id,
        trade_date=trade_date,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=100000.0,
    )


def test_compute_benchmark_evidence_exact_calculation() -> None:
    # 构造 60 根 bar：前 40 根收盘价 3000.0，后 20 根收盘价 3300.0
    # close_60_ago = 3000.0, close_latest = 3300.0
    # ret_60d = (3300 - 3000) / 3000 = +0.10 (+10.0%)
    # ma_20 = 3300.0
    # ma_60 = (40 * 3000 + 20 * 3300) / 60 = (120000 + 66000) / 60 = 186000 / 60 = 3100.0
    # trend_value = 3300.0 / 3100.0 = 1.064516...
    bars = tuple(_benchmark_bar(i, 3000.0) for i in range(40)) + tuple(
        _benchmark_bar(i + 40, 3300.0) for i in range(20)
    )

    evidence = compute_benchmark_evidence(
        benchmark_id="000300.SH",
        bars=bars,
        as_of=AS_OF,
        source="test_fixture",
    )

    assert isinstance(evidence, BenchmarkEvidence)
    assert evidence.benchmark_id == "000300.SH"
    assert evidence.as_of == AS_OF
    assert evidence.ret_60d == pytest.approx(0.10)
    assert evidence.trend_value == pytest.approx(3300.0 / 3100.0)
    assert evidence.source == "test_fixture"


def test_insufficient_bars_raises_benchmark_evidence_unavailable() -> None:
    # 仅 59 根 bar，不足 60 根窗口，必须抛出 BenchmarkEvidenceUnavailable，绝不静默兜底
    bars = tuple(_benchmark_bar(i, 3000.0) for i in range(59))

    with pytest.raises(BenchmarkEvidenceUnavailable) as exc_info:
        compute_benchmark_evidence(
            benchmark_id="000300.SH",
            bars=bars,
            as_of=AS_OF,
        )

    assert "Insufficient benchmark bars" in str(exc_info.value)
    assert "000300.SH" in str(exc_info.value)


def test_empty_bars_raises_benchmark_evidence_unavailable() -> None:
    with pytest.raises(BenchmarkEvidenceUnavailable):
        compute_benchmark_evidence(
            benchmark_id="000300.SH",
            bars=(),
            as_of=AS_OF,
        )


def test_future_bars_strictly_excluded() -> None:
    # 60 根历史 bar，各收盘价 3000.0；另有 2 根未来 bar，收盘价 9999.0
    past_bars = tuple(_benchmark_bar(i, 3000.0) for i in range(60))
    future_bars = (
        DailyBar(
            symbol="000300.SH",
            trade_date=AS_OF.date() + timedelta(days=1),
            open=9999.0,
            high=9999.0,
            low=9999.0,
            close=9999.0,
            volume=100000.0,
        ),
        DailyBar(
            symbol="000300.SH",
            trade_date=AS_OF.date() + timedelta(days=2),
            open=9999.0,
            high=9999.0,
            low=9999.0,
            close=9999.0,
            volume=100000.0,
        ),
    )

    evidence = compute_benchmark_evidence(
        benchmark_id="000300.SH",
        bars=past_bars + future_bars,
        as_of=AS_OF,
    )

    # 历史 60 根均为 3000.0，ret_60d = 0.0, trend_value = 1.0
    assert evidence.ret_60d == pytest.approx(0.0)
    assert evidence.trend_value == pytest.approx(1.0)
