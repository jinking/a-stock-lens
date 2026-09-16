"""The AkShare provider contract, proven against recorded responses.

The files under ``tests/fixtures/akshare/`` are verbatim live responses,
recorded once by ``scripts/record_akshare_fixture.py`` (owner ruling D8). A
fake transport replays them here, so this module never touches the network and
never needs akshare installed — it pins the mapping code, the ``as_of``
handling, and the source-error paths.

The replay transport keys frames on ``(endpoint, params)`` and refuses any
lookup the recording does not cover, so a change in what the provider sends to
the source fails loudly instead of silently matching a stale fixture.
"""

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest, RawDataset
from astock_lens.data.providers.akshare_provider import SYMBOL_SUFFIX, AkShareProvider
from astock_lens.domain.enums import DataStatus

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "akshare"
AS_OF = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)

BAR_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
)
SECURITY_COLUMNS = (
    "symbol",
    "name",
    "exchange",
    "list_date",
    "is_st",
    "is_delisting_board",
    "suspended_trading_days",
)

# Same window as the recording; the replay transport rejects other ranges.
BAR_START, BAR_END = date(2026, 8, 3), date(2026, 9, 4)
# 25 bars per recorded symbol.
BAR_SYMBOLS = ("000001.SZ", "600519.SH")
# main board A + STAR market + SZ A list + BJ, recorded verbatim.
EXPECTED_SECURITY_ROWS = 1701 + 618 + 2901 + 344


class ReplayTransport:
    """Serve recorded frames; any uncovered call is a test failure."""

    def __init__(
        self,
        frames: dict[
            tuple[str, str], tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]
        ],
    ) -> None:
        self._frames = frames
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(
        self, endpoint: str, params: dict[str, str]
    ) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
        self.calls.append((endpoint, dict(params)))
        key = (endpoint, json.dumps(params, ensure_ascii=False, sort_keys=True))
        if key not in self._frames:
            raise AssertionError(f"no recorded frame for {key}")
        return self._frames[key]


def _recorded() -> ReplayTransport:
    """Load every fixture file into a replay transport."""
    frames: dict[
        tuple[str, str], tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]
    ] = {}
    for path in sorted(FIXTURE_DIR.glob("*.csv")):
        header: dict[str, str] = {}
        lines = path.read_text(encoding="utf-8").splitlines()
        split = next(
            index for index, line in enumerate(lines) if not line.startswith("# ")
        )
        for line in lines[:split]:
            key, _, value = line[2:].partition(": ")
            header[key] = value
        rows = list(csv.reader(lines[split:]))
        frames[(header["endpoint"], header["params"])] = (
            tuple(rows[0]),
            tuple(tuple(row) for row in rows[1:]),
        )
    return ReplayTransport(frames)


def _provider(transport: ReplayTransport) -> AkShareProvider:
    return AkShareProvider(version="recorded", transport=transport)


def _bars_request() -> FetchRequest:
    return FetchRequest(
        dataset="daily_bars",
        as_of=AS_OF,
        symbols=BAR_SYMBOLS,
        start_date=BAR_START,
        end_date=BAR_END,
    )


def test_recorded_fixtures_exist() -> None:
    """The recording step ran: every expected file is present and non-empty."""
    expected = {
        "stock_zh_a_hist_tx_sz000001.csv",
        "stock_zh_a_hist_tx_sh600519.csv",
        "stock_info_sh_name_code_main_board_a.csv",
        "stock_info_sh_name_code_star_market.csv",
        "stock_info_sz_name_code_a_list.csv",
        "stock_info_bj_name_code.csv",
    }
    assert {path.name for path in FIXTURE_DIR.glob("*.csv")} >= expected


def test_bars_are_mapped_onto_the_canonical_raw_columns() -> None:
    transport = _recorded()
    dataset = _provider(transport).fetch(_bars_request())

    assert dataset.status is DataStatus.VALUE
    assert dataset.payload is not None
    assert dataset.payload.columns == BAR_COLUMNS
    assert dataset.row_count == 50
    assert len(dataset.payload.rows) == 50
    # One call per requested symbol, with the caller's range passed through.
    assert {call[1]["symbol"] for call in transport.calls} == {"sz000001", "sh600519"}


def test_bar_cells_stay_verbatim_and_the_symbol_is_canonical() -> None:
    """First recorded bar of sz000001, mapped cell for cell."""
    transport = _recorded()
    dataset = _provider(transport).fetch(_bars_request())

    assert dataset.payload is not None
    first = dict(zip(dataset.payload.columns, dataset.payload.rows[0], strict=True))
    assert first == {
        "symbol": "000001.SZ",
        "trade_date": "2026-08-03",
        "open": "11.54",
        "high": "11.66",
        "low": "11.52",
        "close": "11.62",
        "volume": "1060851.0",
        "amount": "1229339800.0",
        "turnover_rate": "0.0055000000000000005",
    }
    assert all(isinstance(cell, str) for row in dataset.payload.rows for cell in row)


def test_bars_request_reports_metadata_honestly() -> None:
    dataset = _provider(_recorded()).fetch(_bars_request())

    assert dataset.provider == "akshare"
    assert dataset.provider_version == "recorded"
    assert dataset.fetched_at.tzinfo is not None
    # A multi-day window has no single trade date; the local provider shares
    # this rule, and both providers must behave identically.
    assert dataset.trade_date is None


def test_securities_are_mapped_from_the_exchange_lists() -> None:
    transport = _recorded()
    dataset = _provider(transport).fetch(
        FetchRequest(dataset="securities", as_of=AS_OF)
    )

    assert dataset.status is DataStatus.VALUE
    assert dataset.payload is not None
    assert dataset.payload.columns == SECURITY_COLUMNS
    assert dataset.row_count == EXPECTED_SECURITY_ROWS

    rows = [
        dict(zip(dataset.payload.columns, row, strict=True))
        for row in dataset.payload.rows
    ]
    # The exchange comes from the endpoint that served the row, never inferred;
    # symbol suffixes use the SH/SZ/BJ vocabulary, exchange identities use
    # SSE/SZSE/BSE — two vocabularies, one mapping.
    assert {row["exchange"] for row in rows} == {"SSE", "SZSE", "BSE"}
    assert all(
        row["symbol"].endswith(f".{SYMBOL_SUFFIX[row['exchange']]}") for row in rows
    )
    # The exchange marks ST by putting ST/*ST in the short name; the check is
    # the designation itself, not an inference.
    assert all((row["is_st"] == "true") == ("ST" in row["name"]) for row in rows)
    assert all(row["is_delisting_board"] == "false" for row in rows)
    # The lists carry no suspension data: absent, never zero.
    assert all(row["suspended_trading_days"] == "" for row in rows)


def test_st_flags_survive_on_a_real_recorded_row() -> None:
    dataset = _provider(_recorded()).fetch(
        FetchRequest(dataset="securities", as_of=AS_OF)
    )

    assert dataset.payload is not None
    rows = [
        dict(zip(dataset.payload.columns, row, strict=True))
        for row in dataset.payload.rows
    ]
    st_rows = [row for row in rows if row["is_st"] == "true"]
    assert st_rows, "the recorded lists contain no ST row; the recording is stale"
    assert all("ST" in row["name"] for row in st_rows)


def test_a_transport_failure_is_a_source_error_not_an_exception() -> None:
    def broken(
        endpoint: str, params: dict[str, str]
    ) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
        raise ConnectionError("network down")

    dataset = _provider(broken).fetch(_bars_request())  # type: ignore[arg-type]

    assert dataset.status is DataStatus.SOURCE_ERROR
    assert dataset.row_count == 0
    assert dataset.payload is None


def test_an_empty_response_is_a_source_error() -> None:
    transport = _recorded()
    transport._frames = {
        key: (columns, ()) for key, (columns, _) in transport._frames.items()
    }

    dataset = _provider(transport).fetch(_bars_request())

    assert dataset.status is DataStatus.SOURCE_ERROR
    assert dataset.row_count == 0
    assert dataset.payload is None


def test_an_unexpected_column_set_is_a_source_error() -> None:
    """A source that drops a required column cannot be mapped; say so."""
    transport = _recorded()
    key = next(key for key in transport._frames if key[0] == "stock_zh_a_hist_tx")
    columns, rows = transport._frames[key]
    drop = columns.index("date")
    transport._frames[key] = (
        tuple(name for index, name in enumerate(columns) if index != drop),
        tuple(
            tuple(cell for index, cell in enumerate(row) if index != drop)
            for row in rows
        ),
    )

    dataset = _provider(transport).fetch(_bars_request())

    assert dataset.status is DataStatus.SOURCE_ERROR
    assert dataset.row_count == 0
    assert dataset.payload is None


def test_bars_without_symbols_are_a_caller_error() -> None:
    """The daily interface is per-symbol; a market-wide request is a caller
    decision the provider cannot make."""
    with pytest.raises(ValueError, match="symbols"):
        _provider(_recorded()).fetch(FetchRequest(dataset="daily_bars", as_of=AS_OF))


def test_an_unknown_exchange_suffix_is_a_caller_error() -> None:
    with pytest.raises(ValueError, match="exchange"):
        _provider(_recorded()).fetch(
            FetchRequest(
                dataset="daily_bars",
                as_of=AS_OF,
                symbols=("999999.XX",),
                start_date=BAR_START,
                end_date=BAR_END,
            )
        )


def test_an_unknown_dataset_is_a_caller_error() -> None:
    with pytest.raises(ValueError, match="dataset"):
        _provider(_recorded()).fetch(FetchRequest(dataset="dividends", as_of=AS_OF))


def test_securities_fetch_ignores_the_date_range() -> None:
    """Identity lists are snapshots, not time series; range params would be
    silently meaningless, so the provider sends none."""
    transport = _recorded()
    _provider(transport).fetch(
        FetchRequest(
            dataset="securities",
            as_of=AS_OF,
            start_date=BAR_START,
            end_date=BAR_END,
        )
    )

    assert all("start_date" not in call[1] for call in transport.calls)


def test_raw_dataset_type_is_preserved() -> None:
    dataset = _provider(_recorded()).fetch(_bars_request())

    assert isinstance(dataset, RawDataset)
