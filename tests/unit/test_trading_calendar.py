"""中国 A 股交易日历单元测试。"""

from datetime import date

from astock_lens.calendar.china import ChinaTradingCalendar


def test_regular_weekday_is_trade_date() -> None:
    calendar = ChinaTradingCalendar()
    # 2026-09-18 是周五，正常交易日
    assert calendar.is_trade_date(date(2026, 9, 18)) is True


def test_weekend_is_not_trade_date() -> None:
    calendar = ChinaTradingCalendar()
    # 2026-09-19 是周六，2026-09-20 是周日
    assert calendar.is_trade_date(date(2026, 9, 19)) is False
    assert calendar.is_trade_date(date(2026, 9, 20)) is False


def test_statutory_holiday_is_not_trade_date() -> None:
    calendar = ChinaTradingCalendar()
    # 2026-01-01 元旦，周四，休市
    assert calendar.is_trade_date(date(2026, 1, 1)) is False
    # 2026-05-01 劳动节，周五，休市
    assert calendar.is_trade_date(date(2026, 5, 1)) is False
    # 2026-10-01 国庆节，周四，休市
    assert calendar.is_trade_date(date(2026, 10, 1)) is False


def test_latest_trade_date_on_trade_date_returns_self() -> None:
    calendar = ChinaTradingCalendar()
    d = date(2026, 9, 18)
    assert calendar.get_latest_trade_date(d) == d


def test_latest_trade_date_on_weekend_returns_previous_friday() -> None:
    calendar = ChinaTradingCalendar()
    friday = date(2026, 9, 18)
    assert calendar.get_latest_trade_date(date(2026, 9, 19)) == friday
    assert calendar.get_latest_trade_date(date(2026, 9, 20)) == friday


def test_custom_dates_override() -> None:
    custom_dates = {date(2026, 9, 19)}  # 假设周六特殊开市
    calendar = ChinaTradingCalendar(trade_dates=custom_dates)
    assert calendar.is_trade_date(date(2026, 9, 19)) is True
    assert calendar.is_trade_date(date(2026, 9, 18)) is False
