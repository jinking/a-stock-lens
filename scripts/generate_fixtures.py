"""Generate the CSV fixtures the test suite reads.

Committed fixtures are part of the specification: a test that asserts a funding
rate, a listing age, or a momentum ranking is only meaningful if the input it
asserts against is auditable. A 300-row hand-edited CSV is not. This script
writes those files from formulas that can be read, reviewed, and re-run, and it
prints the verdicts each row is designed to produce so the fixture and the
assertions share one source of truth.

It never touches ``daily_bars.csv`` or ``dirty_bars.csv``: those are the inputs
to assertions computed by hand in an earlier slice, and rewriting them would
move the trailing windows those expectations were calculated over.

Usage::

    uv run python scripts/generate_fixtures.py
"""

import csv
from datetime import date, timedelta
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "csv"

SECURITY_COLUMNS = (
    "symbol",
    "name",
    "exchange",
    "list_date",
    "is_st",
    "is_delisting_board",
    "suspended_trading_days",
)

# (symbol, name, exchange, list_date, is_st, is_delisting, suspended_days, intent)
#
# Every row exists to make exactly one Universe rule observable. The `intent`
# column is documentation; it is not written to the CSV.
SECURITIES: tuple[tuple[str, str, str, str, str, str, str, str], ...] = (
    (
        "600000.SH",
        "浦发银行",
        "SSE",
        "1999-11-10",
        "false",
        "false",
        "0",
        "included: long history, healthy liquidity",
    ),
    (
        "000001.SZ",
        "平安银行",
        "SZSE",
        "1991-04-03",
        "false",
        "false",
        "0",
        "included: long history, healthy liquidity",
    ),
    (
        "600519.SH",
        "贵州茅台",
        "SSE",
        "2001-08-27",
        "false",
        "false",
        "0",
        "included: long history, healthy liquidity",
    ),
    (
        "300750.SZ",
        "宁德时代",
        "SZSE",
        "2018-06-11",
        "false",
        "false",
        "0",
        "included: ChiNext board, long history",
    ),
    (
        "830799.BJ",
        "艾融软件",
        "BSE",
        "2020-07-27",
        "false",
        "false",
        "0",
        "included: Beijing exchange is in the configured list",
    ),
    (
        "900948.SH",
        "伊泰B股",
        "SSE",
        "1994-01-01",
        "false",
        "false",
        "0",
        "included: liquidity comes from the measure, not the board",
    ),
    (
        "000002.SZ",
        "ST中兵",
        "SZSE",
        "1991-01-29",
        "true",
        "false",
        "0",
        "excluded: ST",
    ),
    (
        "000003.SZ",
        "退市金泰",
        "SZSE",
        "1992-06-01",
        "false",
        "true",
        "0",
        "excluded: delisting board",
    ),
    (
        "000004.SZ",
        "新股一只",
        "SZSE",
        "2026-08-01",
        "false",
        "false",
        "0",
        "excluded: 34 days listed against a 120-day minimum",
    ),
    (
        "000005.SZ",
        "冷门股份",
        "SZSE",
        "1995-03-15",
        "false",
        "false",
        "0",
        "excluded: 20-day average turnover below the 20,000,000 floor",
    ),
    (
        "000006.SZ",
        "停牌股份",
        "SZSE",
        "1996-05-20",
        "false",
        "false",
        "400",
        "included by default: LONG_SUSPENSION is deferred until a day count is set",
    ),
    (
        "000007.SZ",
        "无行情股份",
        "SZSE",
        "1998-09-09",
        "false",
        "false",
        "0",
        "excluded: no bar on the as-of date and no liquidity measure",
    ),
)


BAR_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "volume",
    "amount",
    "turnover_rate",
    "pct_change",
    "adj_factor",
)

# Long enough to contain a 252-day trailing window with room to spare. The
# fixture models weekdays only; A-share holidays are not simulated, and no
# assertion depends on a specific calendar.
HISTORY_DAYS = 300
AS_OF_DATE = date(2026, 9, 4)

# The newest listing gets a history short enough to fail a 60-day window while
# still satisfying a 20-day one, so both branches are observable in one file.
NEW_LISTING_DAYS = 34

SPIKE_DAYS_BEFORE_END = 30
DAILY_HIGH_RATIO = 1.01
DAILY_LOW_RATIO = 0.99
DEFAULT_AMOUNT = 80_000_000.0
LOW_AMOUNT = 5_000_000.0
DEFAULT_VOLUME = 1_000_000.0

# symbol -> (first-day close, daily growth rate, spike ratio)
#
# The growth rate makes the momentum ordering unambiguous and checkable by
# hand: 300750.SZ rises fastest, 000001.SZ falls. The spike plants one high
# inside the trailing year, so `proximity_52w_high` is not the same constant
# 1/1.01 for every rising symbol — without it the factor would have no
# cross-sectional spread to rank.
PRICE_PATHS: dict[str, tuple[float, float, float]] = {
    "600000.SH": (10.00, 0.0020, 1.10),
    "000001.SZ": (20.00, -0.0020, 1.00),
    "600519.SH": (100.00, 0.0000, 1.05),
    "300750.SZ": (30.00, 0.0050, 1.20),
    "830799.BJ": (8.00, 0.0010, 1.08),
    "900948.SH": (6.00, -0.0010, 1.00),
    # The four below exist to be excluded by a Universe rule, not to be ranked.
    # Each still carries a full price history so the only rule it fails is the
    # one it was designed to fail.
    "000002.SZ": (5.00, 0.0000, 1.00),
    "000003.SZ": (4.00, 0.0000, 1.00),
    "000005.SZ": (7.00, 0.0010, 1.00),
    "000006.SZ": (9.00, 0.0010, 1.00),
    "000004.SZ": (12.00, 0.0010, 1.00),
}

# 000007.SZ is absent on purpose: it is the symbol with no bar on the as-of
# date, which the NO_MARKET_DATA rule is written to catch.

# Symbols with a full history that are expected to survive every Universe
# rule, listed in the momentum order their price paths were designed to
# produce. The generator prints this ordering so a reviewer can check the
# fixture against the assertions by eye.
RANKED_SYMBOLS = (
    "300750.SZ",
    "600000.SH",
    "830799.BJ",
    "600519.SH",
    "900948.SH",
    "000001.SZ",
)


def trading_days(*, end: date, count: int) -> list[date]:
    """Return `count` weekdays ending on `end`, oldest first."""
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def bar_rows(symbol: str, days: list[date]) -> list[list[str]]:
    """Build one symbol's daily bars from its configured price path."""
    base, rate, spike_ratio = PRICE_PATHS[symbol]
    spike_index = len(days) - 1 - SPIKE_DAYS_BEFORE_END
    closes = [round(base * (1.0 + rate) ** index, 2) for index in range(len(days))]

    rows: list[list[str]] = []
    for index, day in enumerate(days):
        close = closes[index]
        previous = closes[index - 1] if index > 0 else base
        high = close * (spike_ratio if index == spike_index else DAILY_HIGH_RATIO)
        amount = LOW_AMOUNT if symbol == "000005.SZ" else DEFAULT_AMOUNT
        rows.append(
            [
                symbol,
                day.isoformat(),
                f"{previous:.2f}",
                f"{round(high, 2):.2f}",
                f"{round(close * DAILY_LOW_RATIO, 2):.2f}",
                f"{close:.2f}",
                f"{previous:.2f}",
                f"{DEFAULT_VOLUME:.0f}",
                f"{amount:.0f}",
                "1.00",
                f"{rate * 100:.2f}",
                "1.0",
            ]
        )
    return rows


def write_securities() -> Path:
    """Write the securities master fixture and report each row's intent."""
    path = FIXTURE_ROOT / "securities.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(SECURITY_COLUMNS)
        writer.writerows(row[:7] for row in SECURITIES)
    print(f"{path.name}: {len(SECURITIES)} rows")
    for row in SECURITIES:
        print(f"  {row[0]}  {row[7]}")
    return path


def write_daily_bars_long() -> Path:
    """Write the long-history daily-bar fixture and report its intended shape."""
    days = trading_days(end=AS_OF_DATE, count=HISTORY_DAYS)
    recent = days[-NEW_LISTING_DAYS:]

    rows: list[list[str]] = []
    for symbol in PRICE_PATHS:
        symbol_days = recent if symbol == "000004.SZ" else days
        rows.extend(bar_rows(symbol, symbol_days))

    path = FIXTURE_ROOT / "daily_bars_long.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(BAR_COLUMNS)
        writer.writerows(rows)

    print(f"{path.name}: {len(rows)} rows over {len(PRICE_PATHS)} symbols")
    print(f"  window: {days[0].isoformat()} .. {days[-1].isoformat()}")
    print("  momentum order these paths were designed to produce:")
    for symbol in RANKED_SYMBOLS:
        rate = PRICE_PATHS[symbol][1]
        print(f"    {symbol}  ret_20d ~ {((1 + rate) ** 20 - 1) * 100:+.2f}%")
    print("  000004.SZ has only the newest days, so ret_60d is NULL for it")
    print("  000007.SZ has no bars at all, so it fails NO_MARKET_DATA")
    return path


def main() -> None:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    write_securities()
    print()
    write_daily_bars_long()


if __name__ == "__main__":
    main()
