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


def _dataset(
    symbol: str, close: float, events: tuple[DividendEvent, ...]
) -> NormalizedDataset:
    """按原用例的构造方式装配输入：as_of 当日一根日线 + 给定分红事件。"""
    return NormalizedDataset(
        dataset="test",
        as_of=AS_OF,
        daily_bars=(_bar(symbol, AS_OF.date(), close),),
        dividend_events=events,
    )


# 测试 1–4（取值口径）四行：行序与原用例一致，label 即原测试名，
# 原 docstring 与算式注释逐字保留为行注释；unit 为 None 表示该行不断言单位。
YIELD_VALUE_CASES = (
    # test_dividend_yield_ttm_standard_annual_distribution:
    #   测试 1: 正常单次已实施分红计算股息率 (A1 + B1 + C1).
    #   股价 5.00 元；2026-07-15 除权，每 10 股派 2.50 元 (每股 0.25 元)
    #   0.25 / 5.00 * 100 = 5.00%
    (
        "test_dividend_yield_ttm_standard_annual_distribution",
        "601398.SH",
        5.00,
        (_event("601398.SH", date(2026, 7, 15), "实施", 2.50),),
        5.0000,
        "%",
    ),
    # test_dividend_yield_ttm_multiple_distributions_within_year:
    #   测试 2: 一年多次分红 (中报+年报) 累加派息.
    #   两次派息都在 365 天内；每股 19.106 / 每股 30.876
    #   (19.106 + 30.876) / 1500.0 * 100 = 49.982 / 1500 * 100 = 3.332133...%
    (
        "test_dividend_yield_ttm_multiple_distributions_within_year",
        "600519.SH",
        1500.0,
        (
            _event("600519.SH", date(2025, 12, 20), "实施", 191.06),
            _event("600519.SH", date(2026, 6, 25), "实施", 308.76),
        ),
        round((49.982 / 1500.0) * 100.0, 4),
        None,
    ),
    # test_dividend_yield_ttm_excludes_proposals:
    #   测试 3: 严格排除预案事件 (B1 口径).
    #   预案派息 5.00 元，已实施派息 2.50 元；仅计入实施的 2.50 (每股 0.25) -> 5.0%
    (
        "test_dividend_yield_ttm_excludes_proposals",
        "601398.SH",
        5.00,
        (
            _event("601398.SH", date(2026, 7, 15), "实施", 2.50),
            _event("601398.SH", date(2026, 8, 20), "预案", 5.00),
        ),
        5.0000,
        None,
    ),
    # test_dividend_yield_ttm_excludes_events_outside_window:
    #   测试 4: 排除超过 365 天与晚于 as_of 的分红 (A1 口径).
    #   超过 365 天 / 窗口内 / 晚于 as_of
    (
        "test_dividend_yield_ttm_excludes_events_outside_window",
        "601398.SH",
        5.00,
        (
            _event("601398.SH", date(2025, 9, 10), "实施", 3.00),
            _event("601398.SH", date(2026, 7, 15), "实施", 2.50),
            _event(
                "601398.SH",
                date(2026, 9, 25),
                "实施",
                4.00,
                available_at=AS_OF + timedelta(days=5),
            ),
        ),
        5.0000,
        None,
    ),
)


def test_dividend_yield_ttm_value_cases() -> None:
    """测试 1–4：TTM 窗口、已实施口径与 as_of 当日收盘价分母的取值断言。"""
    wrong = []
    for label, symbol, close, events, expected_value, unit in YIELD_VALUE_CASES:
        result = build_factor(_config()).compute(
            FactorContext(
                symbol=symbol,
                as_of=AS_OF,
                dataset=_dataset(symbol, close, events),
            )
        )
        if result.status is not DataStatus.VALUE:
            wrong.append(f"{label}: status={result.status!r}，期望 VALUE")
        elif result.raw_value is None:
            wrong.append(f"{label}: raw_value 为 None，期望 {expected_value!r}")
        elif round(result.raw_value, 4) != expected_value:
            wrong.append(
                f"{label}: raw_value={result.raw_value!r}，期望 {expected_value!r}"
            )
        if unit is not None and result.unit != unit:
            wrong.append(f"{label}: unit={result.unit!r}，期望 {unit!r}")
    assert not wrong, "股息率取值口径未按预期:\n" + "\n".join(wrong)


# 测试 5–7（边界状态）三行：行序与原用例一致，label 即原测试名，
# 原 docstring 与注释逐字保留；expected_value 为 None 时要求 raw_value 就是 None，
# 否则按原用例的精确相等比较（0.0 不经过四舍五入）。
YIELD_STATUS_CASES = (
    # test_dividend_yield_ttm_missing_price_returns_null:
    #   测试 5: 缺少日线价格或停牌时返回 NULL，不捏造 0.
    #   无行情
    (
        "test_dividend_yield_ttm_missing_price_returns_null",
        "601398.SH",
        (),
        (_event("601398.SH", date(2026, 7, 15), "实施", 2.50),),
        DataStatus.NULL,
        None,
        None,
    ),
    # test_dividend_yield_ttm_no_events_returns_not_applicable:
    #   测试 6: 无任何分红记录返回 NOT_APPLICABLE.
    #   该股票无分红事件
    (
        "test_dividend_yield_ttm_no_events_returns_not_applicable",
        "688001.SH",
        (_bar("688001.SH", AS_OF.date(), 20.00),),
        (),
        DataStatus.NOT_APPLICABLE,
        None,
        None,
    ),
    # test_dividend_yield_ttm_has_history_but_zero_in_past_year_returns_zero_value:
    #   测试 7: 标的有分红历史记录但过去 365 天无已实施派息，返回 VALUE 0.0%.
    #   分红除权在 500 天前
    (
        "test_dividend_yield_ttm_has_history_but_zero_in_past_year_returns_zero_value",
        "600000.SH",
        (_bar("600000.SH", AS_OF.date(), 10.00),),
        (_event("600000.SH", date(2025, 4, 1), "实施", 1.50),),
        DataStatus.VALUE,
        0.0,
        "%",
    ),
)


def test_dividend_yield_ttm_status_boundaries() -> None:
    """测试 5–7：缺价 / 无分红记录 / 一年内零派息的状态与取值。"""
    wrong = []
    for (
        label,
        symbol,
        bars,
        events,
        expected_status,
        expected_value,
        unit,
    ) in YIELD_STATUS_CASES:
        result = build_factor(_config()).compute(
            FactorContext(
                symbol=symbol,
                as_of=AS_OF,
                dataset=NormalizedDataset(
                    dataset="test",
                    as_of=AS_OF,
                    daily_bars=bars,
                    dividend_events=events,
                ),
            )
        )
        if result.status is not expected_status:
            wrong.append(f"{label}: status={result.status!r}，期望 {expected_status!r}")
        elif expected_value is None:
            if result.raw_value is not None:
                wrong.append(f"{label}: raw_value={result.raw_value!r}，期望 None")
        elif result.raw_value != expected_value:
            wrong.append(
                f"{label}: raw_value={result.raw_value!r}，期望 {expected_value!r}"
            )
        if unit is not None and result.unit != unit:
            wrong.append(f"{label}: unit={result.unit!r}，期望 {unit!r}")
    assert not wrong, "股息率边界状态未按预期:\n" + "\n".join(wrong)
