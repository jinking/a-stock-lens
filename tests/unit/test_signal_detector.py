"""Signal detector unit tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from astock_lens.domain.enums import DataStatus, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.signals.contracts import SignalContext, SignalResult
from astock_lens.signals.detector import DefaultSignalDetector

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SHANGHAI)


def _fr(symbol: str, factor: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=AS_OF,
        status=DataStatus.VALUE,
        raw_value=value,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
    )


def test_signal_breakout() -> None:
    """测试动量突破：距一年高点 >= 0.95 输出 BREAKOUT。"""
    detector = DefaultSignalDetector(version="v1")
    factors = (
        _fr("300741.SZ", "proximity_52w_high", 0.98),
        _fr("300741.SZ", "ret_20d", 0.35),
    )
    ctx = SignalContext(
        symbol="300741.SZ", as_of=AS_OF, factors=factors, strategy_id="momentum"
    )
    res = detector.detect(ctx)
    assert isinstance(res, SignalResult)
    assert res.signal == Signal.BREAKOUT
    assert res.lineage.signal_version == "v1"


def test_signal_trend_continue() -> None:
    """测试强趋势持续：ret_20d >= 6.4% 且高点在 0.85 ~ 0.95 输出 TREND_CONTINUE。"""
    detector = DefaultSignalDetector(version="v1")
    factors = (
        _fr("000001.SZ", "proximity_52w_high", 0.89),
        _fr("000001.SZ", "ret_20d", 0.08),
    )
    ctx = SignalContext(
        symbol="000001.SZ", as_of=AS_OF, factors=factors, strategy_id="momentum"
    )
    res = detector.detect(ctx)
    assert res.signal == Signal.TREND_CONTINUE


def test_signal_pullback() -> None:
    """测试良性回踩：ret_60d >= 20% 且 ret_20d 在 0% ~ 5% 窄幅休整输出 PULLBACK。"""
    detector = DefaultSignalDetector(version="v1")
    factors = (
        _fr("300434.SZ", "proximity_52w_high", 0.88),
        _fr("300434.SZ", "ret_60d", 0.25),
        _fr("300434.SZ", "ret_20d", 0.02),
    )
    ctx = SignalContext(
        symbol="300434.SZ", as_of=AS_OF, factors=factors, strategy_id="momentum"
    )
    res = detector.detect(ctx)
    assert res.signal == Signal.PULLBACK


def test_signal_value_contrarian() -> None:
    """测试价值策略筑底企稳：ret_20d 处于 -5% ~ +2% 输出 VALUE_CONTRARIAN。"""
    detector = DefaultSignalDetector(version="v1")
    factors = (
        _fr("600000.SH", "ret_20d", -0.01),
        _fr("600000.SH", "pe_ttm", 6.5),
    )
    ctx = SignalContext(
        symbol="600000.SH", as_of=AS_OF, factors=factors, strategy_id="value"
    )
    res = detector.detect(ctx)
    assert res.signal == Signal.VALUE_CONTRARIAN


def test_signal_dividend_support() -> None:
    """测试红利防御特征：dividend_yield_ttm >= 3.0% 且不创新低输出 DIVIDEND_SUPPORT。"""
    detector = DefaultSignalDetector(version="v1")
    factors = (
        _fr("601398.SH", "dividend_yield_ttm", 5.2),
        _fr("601398.SH", "ret_20d", -0.01),
    )
    ctx = SignalContext(
        symbol="601398.SH", as_of=AS_OF, factors=factors, strategy_id="dividend"
    )
    res = detector.detect(ctx)
    assert res.signal == Signal.DIVIDEND_SUPPORT


def test_signal_breakdown() -> None:
    """测试严重破位下跌：ret_20d < -15% 输出 BREAKDOWN。"""
    detector = DefaultSignalDetector(version="v1")
    factors = (_fr("688525.SH", "ret_20d", -0.22),)
    ctx = SignalContext(
        symbol="688525.SH", as_of=AS_OF, factors=factors, strategy_id="growth"
    )
    res = detector.detect(ctx)
    assert res.signal == Signal.BREAKDOWN


def test_signal_trend_weaken() -> None:
    """测试强势转弱：中期大涨 (ret_60d > 15%) 但短期走弱 (ret_20d < -5%) 输出 TREND_WEAKEN。"""
    detector = DefaultSignalDetector(version="v1")
    factors = (
        _fr("000002.SZ", "ret_60d", 0.22),
        _fr("000002.SZ", "ret_20d", -0.08),
    )
    ctx = SignalContext(
        symbol="000002.SZ", as_of=AS_OF, factors=factors, strategy_id="momentum"
    )
    res = detector.detect(ctx)
    assert res.signal == Signal.TREND_WEAKEN


def test_signal_no_signal_default() -> None:
    """测试无显著交易特征时，输出 NO_SIGNAL。"""
    detector = DefaultSignalDetector(version="v1")
    factors = (_fr("600519.SH", "ret_20d", -0.09),)
    ctx = SignalContext(
        symbol="600519.SH", as_of=AS_OF, factors=factors, strategy_id="growth"
    )
    res = detector.detect(ctx)
    assert res.signal == Signal.NO_SIGNAL
