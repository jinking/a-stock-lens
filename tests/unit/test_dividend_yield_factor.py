"""DividendYieldTTMFactor 单元测试 (Plan D Task 2).

验证项目所有者批准的口径：
- A1: TTM 窗口按除权日 (ex_date) 在 [as_of - 365d, as_of] 内；
- B1: 严格排除预案，仅聚合已实施分红；
- C1: 以 as_of 当日收盘价为分母，单位为 %；
- 边界：停牌/缺价返回 NULL，无分红记录返回 NOT_APPLICABLE，有记录但过去一年派息为0返回 0.0。
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from astock_lens.data.contracts import NormalizedDataset
from astock_lens.data.dividends.models import DividendEvent
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DailyBar
from astock_lens.factors.builtin import build_factor
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorContext

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SHANGHAI)


def _config() -> FactorConfig:
    return FactorConfig(
        name="dividend_yield_ttm",
        domain="VALUATION",
        description="Trailing dividend yield, in percent.",
        inputs=("dividend_yield_ttm",),
        frequency="DAILY",
        direction="HIGHER_MEANS_MORE_INCOME_RETURNED",
        null_policy="NULL_UNLESS_THE_METRIC_HAS_A_PUBLISHED_VALUE",
        version="v1",
    )


def _bar(symbol: str, trade_date: date, close: float) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000000.0,
        amount=5000000.0,
    )


def _event(
    symbol: str,
    ex_date: date | None,
    status: str,
    per_10: float | None,
    available_at: datetime = AS_OF,
) -> DividendEvent:
    return DividendEvent(
        symbol=symbol,
        announcement_date=ex_date - timedelta(days=20) if ex_date else date(2026, 8, 1),
        registration_date=ex_date - timedelta(days=1) if ex_date else None,
        ex_date=ex_date,
        implementation_status=status,
        cash_dividend_per_10_shares=per_10,
        currency="CNY",
        available_at=available_at,
        source_text=f"10派{per_10}元" if per_10 else "不分配",
    )


def test_dividend_yield_ttm_standard_annual_distribution() -> None:
    """测试 1: 正常单次已实施分红计算股息率 (A1 + B1 + C1)."""
    symbol = "601398.SH"
    # 股价 5.00 元
    bars = (_bar(symbol, AS_OF.date(), 5.00),)
    # 2026-07-15 除权，每 10 股派 2.50 元 (每股 0.25 元)
    events = (_event(symbol, date(2026, 7, 15), "实施", 2.50),)
    dataset = NormalizedDataset(
        dataset="test",
        as_of=AS_OF,
        daily_bars=bars,
        dividend_events=events,
    )
    context = FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset)

    factor = build_factor(_config())
    result = factor.compute(context)

    assert result.status == DataStatus.VALUE
    # 0.25 / 5.00 * 100 = 5.00%
    assert result.raw_value is not None
    assert round(result.raw_value, 4) == 5.0000
    assert result.unit == "%"


def test_dividend_yield_ttm_multiple_distributions_within_year() -> None:
    """测试 2: 一年多次分红 (中报+年报) 累加派息."""
    symbol = "600519.SH"
    bars = (_bar(symbol, AS_OF.date(), 1500.0),)
    # 两次派息都在 365 天内
    events = (
        _event(symbol, date(2025, 12, 20), "实施", 191.06),  # 每股 19.106
        _event(symbol, date(2026, 6, 25), "实施", 308.76),  # 每股 30.876
    )
    dataset = NormalizedDataset(
        dataset="test",
        as_of=AS_OF,
        daily_bars=bars,
        dividend_events=events,
    )
    context = FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset)

    factor = build_factor(_config())
    result = factor.compute(context)

    assert result.status == DataStatus.VALUE
    # (19.106 + 30.876) / 1500.0 * 100 = 49.982 / 1500 * 100 = 3.332133...%
    expected = (49.982 / 1500.0) * 100.0
    assert result.raw_value is not None
    assert round(result.raw_value, 4) == round(expected, 4)


def test_dividend_yield_ttm_excludes_proposals() -> None:
    """测试 3: 严格排除预案事件 (B1 口径)."""
    symbol = "601398.SH"
    bars = (_bar(symbol, AS_OF.date(), 5.00),)
    # 预案派息 5.00 元，已实施派息 2.50 元
    events = (
        _event(symbol, date(2026, 7, 15), "实施", 2.50),
        _event(symbol, date(2026, 8, 20), "预案", 5.00),
    )
    dataset = NormalizedDataset(
        dataset="test",
        as_of=AS_OF,
        daily_bars=bars,
        dividend_events=events,
    )
    context = FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset)

    factor = build_factor(_config())
    result = factor.compute(context)

    assert result.status == DataStatus.VALUE
    # 仅计入实施的 2.50 (每股 0.25) -> 5.0%
    assert result.raw_value is not None
    assert round(result.raw_value, 4) == 5.0000


def test_dividend_yield_ttm_excludes_events_outside_window() -> None:
    """测试 4: 排除超过 365 天与晚于 as_of 的分红 (A1 口径)."""
    symbol = "601398.SH"
    bars = (_bar(symbol, AS_OF.date(), 5.00),)
    events = (
        # 超过 365 天
        _event(symbol, date(2025, 9, 10), "实施", 3.00),
        # 窗口内
        _event(symbol, date(2026, 7, 15), "实施", 2.50),
        # 晚于 as_of
        _event(
            symbol,
            date(2026, 9, 25),
            "实施",
            4.00,
            available_at=AS_OF + timedelta(days=5),
        ),
    )
    dataset = NormalizedDataset(
        dataset="test",
        as_of=AS_OF,
        daily_bars=bars,
        dividend_events=events,
    )
    context = FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset)

    factor = build_factor(_config())
    result = factor.compute(context)

    assert result.status == DataStatus.VALUE
    assert result.raw_value is not None
    assert round(result.raw_value, 4) == 5.0000


def test_dividend_yield_ttm_missing_price_returns_null() -> None:
    """测试 5: 缺少日线价格或停牌时返回 NULL，不捏造 0."""
    symbol = "601398.SH"
    events = (_event(symbol, date(2026, 7, 15), "实施", 2.50),)
    dataset = NormalizedDataset(
        dataset="test",
        as_of=AS_OF,
        daily_bars=(),  # 无行情
        dividend_events=events,
    )
    context = FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset)

    factor = build_factor(_config())
    result = factor.compute(context)

    assert result.status == DataStatus.NULL
    assert result.raw_value is None


def test_dividend_yield_ttm_no_events_returns_not_applicable() -> None:
    """测试 6: 无任何分红记录返回 NOT_APPLICABLE."""
    symbol = "688001.SH"
    bars = (_bar(symbol, AS_OF.date(), 20.00),)
    dataset = NormalizedDataset(
        dataset="test",
        as_of=AS_OF,
        daily_bars=bars,
        dividend_events=(),  # 该股票无分红事件
    )
    context = FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset)

    factor = build_factor(_config())
    result = factor.compute(context)

    assert result.status == DataStatus.NOT_APPLICABLE
    assert result.raw_value is None


def test_dividend_yield_ttm_has_history_but_zero_in_past_year_returns_zero_value() -> (
    None
):
    """测试 7: 标的有分红历史记录但过去 365 天无已实施派息，返回 VALUE 0.0%."""
    symbol = "600000.SH"
    bars = (_bar(symbol, AS_OF.date(), 10.00),)
    # 分红除权在 500 天前
    events = (_event(symbol, date(2025, 4, 1), "实施", 1.50),)
    dataset = NormalizedDataset(
        dataset="test",
        as_of=AS_OF,
        daily_bars=bars,
        dividend_events=events,
    )
    context = FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset)

    factor = build_factor(_config())
    result = factor.compute(context)

    assert result.status == DataStatus.VALUE
    assert result.raw_value == 0.0
    assert result.unit == "%"
