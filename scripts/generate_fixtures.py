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


def main() -> None:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    write_securities()


if __name__ == "__main__":
    main()
