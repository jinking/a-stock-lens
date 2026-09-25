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


SIGNAL_CASES = (
    # test_signal_breakout: 测试动量突破：距一年高点 >= 0.95 输出 BREAKOUT。
    (
        "test_signal_breakout",
        "300741.SZ",
        "momentum",
        (("proximity_52w_high", 0.98), ("ret_20d", 0.35)),
        Signal.BREAKOUT,
        "v1",
    ),
    # test_signal_trend_continue: 测试强趋势持续：ret_20d >= 6.4% 且高点在 0.85 ~ 0.95 输出 TREND_CONTINUE。
    (
        "test_signal_trend_continue",
        "000001.SZ",
        "momentum",
        (("proximity_52w_high", 0.89), ("ret_20d", 0.08)),
        Signal.TREND_CONTINUE,
        None,
    ),
    # test_signal_pullback: 测试良性回踩：ret_60d >= 20% 且 ret_20d 在 0% ~ 5% 窄幅休整输出 PULLBACK。
    (
        "test_signal_pullback",
        "300434.SZ",
        "momentum",
        (("proximity_52w_high", 0.88), ("ret_60d", 0.25), ("ret_20d", 0.02)),
        Signal.PULLBACK,
        None,
    ),
    # test_signal_value_contrarian: 测试价值策略筑底企稳：ret_20d 处于 -5% ~ +2% 输出 VALUE_CONTRARIAN。
    (
        "test_signal_value_contrarian",
        "600000.SH",
        "value",
        (("ret_20d", -0.01), ("pe_ttm", 6.5)),
        Signal.VALUE_CONTRARIAN,
        None,
    ),
    # test_signal_dividend_support: 测试红利防御特征：dividend_yield_ttm >= 3.0% 且不创新低输出 DIVIDEND_SUPPORT。
    (
        "test_signal_dividend_support",
        "601398.SH",
        "dividend",
        (("dividend_yield_ttm", 5.2), ("ret_20d", -0.01)),
        Signal.DIVIDEND_SUPPORT,
        None,
    ),
    # test_signal_breakdown: 测试严重破位下跌：ret_20d < -15% 输出 BREAKDOWN。
    (
        "test_signal_breakdown",
        "688525.SH",
        "growth",
        (("ret_20d", -0.22),),
        Signal.BREAKDOWN,
        None,
    ),
    # test_signal_trend_weaken: 测试强势转弱：中期大涨 (ret_60d > 15%) 但短期走弱 (ret_20d < -5%) 输出 TREND_WEAKEN。
    (
        "test_signal_trend_weaken",
        "000002.SZ",
        "momentum",
        (("ret_60d", 0.22), ("ret_20d", -0.08)),
        Signal.TREND_WEAKEN,
        None,
    ),
    # test_signal_no_signal_default: 测试无显著交易特征时，输出 NO_SIGNAL。
    (
        "test_signal_no_signal_default",
        "600519.SH",
        "growth",
        (("ret_20d", -0.09),),
        Signal.NO_SIGNAL,
        None,
    ),
)


def test_signal_profiles_map_to_expected_signals() -> None:
    """测试 8 组因子画像各自输出预期 signal（原 8 条判定用例收表）。

    末列携带原 breakout 行的 lineage 断言（`"v1"`）；其余行按原用例只断言 signal。
    """
    detector = DefaultSignalDetector(version="v1")
    wrong = []
    for (
        label,
        symbol,
        strategy_id,
        factor_values,
        expected,
        expected_signal_version,
    ) in SIGNAL_CASES:
        ctx = SignalContext(
            symbol=symbol,
            as_of=AS_OF,
            factors=tuple(
                _fr(symbol, factor, value) for factor, value in factor_values
            ),
            strategy_id=strategy_id,
        )
        res = detector.detect(ctx)
        if not isinstance(res, SignalResult):
            wrong.append(f"{label}: 期望 SignalResult，实际 {type(res).__name__}")
            continue
        if res.signal != expected:
            wrong.append(f"{label}: signal 得到 {res.signal!r}，期望 {expected!r}")
        if (
            expected_signal_version is not None
            and res.lineage.signal_version != expected_signal_version
        ):
            wrong.append(
                f"{label}: lineage.signal_version 得到 "
                f"{res.lineage.signal_version!r}，期望 {expected_signal_version!r}"
            )
    assert not wrong, "信号判定未按预期:\n" + "\n".join(wrong)
