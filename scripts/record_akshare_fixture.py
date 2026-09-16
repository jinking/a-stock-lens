"""Record real AkShare responses as offline contract fixtures.

The owner's ruling (D8): the AkShare contract test runs against a *recorded*
response, never a hand-written one. This script performs the live calls once
and writes each response verbatim under ``tests/fixtures/akshare/`` as CSV,
prefixed by a ``# ``-commented header recording the source, endpoint, params,
AkShare version, fetch timestamp, and row count. The provider contract test
replays these files through a fake transport; nothing in it invents a cell.

Endpoint choice (2026-09-16, see the slice ledger): this environment's proxy
drops Python clients talking to eastmoney's ``push2*`` domains, so the daily
bars come from akshare's Tencent-domain interface ``stock_zh_a_hist_tx`` (it
carries amount in yuan and turnover, which the liquidity factor needs). The
listing lists come from the three exchange domains, which are reachable. SH
needs both the main board and the STAR market, otherwise every 688-prefixed
symbol would silently vanish from the universe.

Usage::

    uv run python scripts/record_akshare_fixture.py
"""

import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import akshare as ak

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "akshare"

BAR_SYMBOLS = ("sz000001", "sh600519")
BAR_START, BAR_END = "20260803", "20260904"

# (file stem, endpoint, params) — the securities endpoints are one call each;
# their exchange identity lives in the provider's endpoint table, not here.
RECORDINGS: tuple[tuple[str, str, dict[str, str]], ...] = (
    *(
        (
            f"stock_zh_a_hist_tx_{symbol}",
            "stock_zh_a_hist_tx",
            {
                "symbol": symbol,
                "start_date": BAR_START,
                "end_date": BAR_END,
                "adjust": "",
            },
        )
        for symbol in BAR_SYMBOLS
    ),
    (
        "stock_info_sh_name_code_main_board_a",
        "stock_info_sh_name_code",
        {"symbol": "主板A股"},
    ),
    (
        "stock_info_sh_name_code_star_market",
        "stock_info_sh_name_code",
        {"symbol": "科创板"},
    ),
    (
        "stock_info_sz_name_code_a_list",
        "stock_info_sz_name_code",
        {"symbol": "A股列表"},
    ),
    ("stock_info_bj_name_code", "stock_info_bj_name_code", {}),
)


def record(stem: str, endpoint: str, params: dict[str, str]) -> None:
    """Call one endpoint live and write the response verbatim."""
    frame = getattr(ak, endpoint)(**params)
    columns = [str(column) for column in frame.columns]
    rows = [
        [_cell(value) for value in row]
        for row in frame.itertuples(index=False, name=None)
    ]

    header = {
        "source": "akshare",
        "endpoint": endpoint,
        "params": json.dumps(params, ensure_ascii=False, sort_keys=True),
        "akshare_version": ak.__version__,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rows": str(len(rows)),
    }

    path = FIXTURE_DIR / f"{stem}.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        for key, value in header.items():
            stream.write(f"# {key}: {value}\n")
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"{path.name}: {len(rows)} rows, columns={columns}")


def _cell(value: object) -> str:
    """Render one cell the way ``to_csv`` would: missing values become ''."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value)
    return "" if text in {"<NA>", "NaT"} else text


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for stem, endpoint, params in RECORDINGS:
        record(stem, endpoint, params)


if __name__ == "__main__":
    main()
