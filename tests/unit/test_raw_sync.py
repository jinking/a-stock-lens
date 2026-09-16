"""Raw landing tests.

`spec §15` requires the daily pipeline to be incremental: "do not redownload
full history every day when unchanged". These tests pin that rule, and the two
honesty rules around it — a provider problem is reported rather than papered
over with an empty file, and re-landing the same date replaces rows instead of
duplicating them.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import (
    DataProvider,
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.data.sync import land_raw, landed_symbols, read_raw_rows
from astock_lens.domain.enums import DataStatus

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
FETCHED_AT = datetime(2026, 9, 4, 15, 5, tzinfo=UTC)

BAR_COLUMNS = ("symbol", "trade_date", "close")
SECURITY_COLUMNS = ("symbol", "name", "exchange", "list_date")

SECURITIES = (
    ("600519.SH", "Kweichow Moutai", "SSE", "2001-08-27"),
    ("000001.SZ", "Ping An Bank", "SZSE", "1991-04-03"),
)


class StubProvider:
    """A provider that records what it was asked for."""

    def __init__(self, *, fail_bars: bool = False) -> None:
        self.requests: list[FetchRequest] = []
        self._fail_bars = fail_bars

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="stub",
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=FETCHED_AT,
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        self.requests.append(request)

        if request.dataset == "securities":
            return self._dataset(request, SECURITY_COLUMNS, SECURITIES)

        if self._fail_bars:
            return RawDataset(
                provider="stub",
                dataset=request.dataset,
                fetched_at=FETCHED_AT,
                provider_version="v1",
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
            )

        symbols: Sequence[str] = request.symbols or ()
        rows = tuple((symbol, AS_OF.date().isoformat(), "10.5") for symbol in symbols)
        return self._dataset(request, BAR_COLUMNS, rows)

    @staticmethod
    def _dataset(
        request: FetchRequest,
        columns: tuple[str, ...],
        rows: Sequence[tuple[str, ...]],
    ) -> RawDataset:
        return RawDataset(
            provider="stub",
            dataset=request.dataset,
            fetched_at=FETCHED_AT,
            provider_version="v1",
            status=DataStatus.VALUE if rows else DataStatus.NULL,
            row_count=len(rows),
            payload=RawPayload(columns=columns, rows=tuple(rows)),
        )


def _land(local_tmp: Path, provider: StubProvider) -> object:
    return land_raw(provider=provider, root=local_tmp, as_of=AS_OF)


def test_landing_writes_both_datasets_in_the_canonical_shape(
    local_tmp: Path,
) -> None:
    provider = StubProvider()

    result = _land(local_tmp, provider)

    assert {landing.dataset for landing in result.landings} == {
        "securities",
        "daily_bars",
    }
    columns, rows = read_raw_rows(local_tmp / "securities.csv")
    assert columns == SECURITY_COLUMNS
    assert len(rows) == 2

    columns, rows = read_raw_rows(local_tmp / "daily_bars.csv")
    assert columns == BAR_COLUMNS
    assert {row[0] for row in rows} == {"600519.SH", "000001.SZ"}


def test_the_symbol_list_comes_from_the_securities_dataset(
    local_tmp: Path,
) -> None:
    """Nothing named the symbols, so the listing decided them."""
    provider = StubProvider()

    _land(local_tmp, provider)

    bar_requests = [r for r in provider.requests if r.dataset == "daily_bars"]
    assert bar_requests[-1].symbols == ("000001.SZ", "600519.SH")


def test_explicit_symbols_win_over_the_listing(local_tmp: Path) -> None:
    provider = StubProvider()

    land_raw(provider=provider, root=local_tmp, as_of=AS_OF, symbols=("600519.SH",))

    bar_requests = [r for r in provider.requests if r.dataset == "daily_bars"]
    assert bar_requests[-1].symbols == ("600519.SH",)


def test_a_second_run_for_the_same_date_asks_for_nothing_already_landed(
    local_tmp: Path,
) -> None:
    _land(local_tmp, StubProvider())
    provider = StubProvider()

    result = _land(local_tmp, provider)

    bar_requests = [r for r in provider.requests if r.dataset == "daily_bars"]
    assert bar_requests == []
    bars = next(item for item in result.landings if item.dataset == "daily_bars")
    assert bars.rows_written == 0
    assert bars.status is DataStatus.NOT_APPLICABLE
    assert bars.symbols_skipped == ("000001.SZ", "600519.SH")


def test_incremental_landing_only_fetches_what_is_missing(local_tmp: Path) -> None:
    (local_tmp / "daily_bars.csv").write_text(
        "symbol,trade_date,close\n600519.SH,2026-09-04,10.5\n", encoding="utf-8"
    )
    provider = StubProvider()

    result = land_raw(provider=provider, root=local_tmp, as_of=AS_OF)

    bar_requests = [r for r in provider.requests if r.dataset == "daily_bars"]
    assert bar_requests[-1].symbols == ("000001.SZ",)
    bars = next(item for item in result.landings if item.dataset == "daily_bars")
    assert bars.symbols_skipped == ("600519.SH",)


def test_re_landing_the_listing_does_not_duplicate_its_rows(local_tmp: Path) -> None:
    """The listing carries no trade date, so the merge key is the whole row.

    Landing it twice must leave two symbols, not four: the same payload merged
    again replaces what it already covers.
    """
    land_raw(provider=StubProvider(), root=local_tmp, as_of=AS_OF)

    land_raw(provider=StubProvider(), root=local_tmp, as_of=AS_OF)

    _, rows = read_raw_rows(local_tmp / "securities.csv")
    assert len(rows) == len(SECURITIES)


def test_landing_a_listing_replaces_a_symbol_whose_details_changed(
    local_tmp: Path,
) -> None:
    """A listing is keyed by instrument, not by every cell.

    The source reformats names and dates between releases; keying on the whole
    row would append a second row for the same instrument — and a Universe that
    admitted one symbol twice would rank a duplicated cross-section.
    """
    (local_tmp / "securities.csv").write_text(
        "symbol,name,exchange,list_date\n"
        "600519.SH,OLD NAME,SSE,1900-01-01\n"
        "000001.SZ,Ping An Bank,SZSE,1991-04-03\n",
        encoding="utf-8",
    )

    land_raw(provider=StubProvider(), root=local_tmp, as_of=AS_OF)

    _, rows = read_raw_rows(local_tmp / "securities.csv")
    symbols = [row[0] for row in rows]
    assert sorted(symbols) == ["000001.SZ", "600519.SH"]


def test_earlier_rows_are_kept_when_a_new_date_is_landed(local_tmp: Path) -> None:
    (local_tmp / "daily_bars.csv").write_text(
        "symbol,trade_date,close\n600519.SH,2026-09-03,10.0\n", encoding="utf-8"
    )

    land_raw(
        provider=StubProvider(), root=local_tmp, as_of=AS_OF, symbols=("600519.SH",)
    )

    _, rows = read_raw_rows(local_tmp / "daily_bars.csv")
    assert rows == (
        ("600519.SH", "2026-09-03", "10.0"),
        ("600519.SH", "2026-09-04", "10.5"),
    )


def test_a_provider_failure_is_reported_and_writes_nothing(local_tmp: Path) -> None:
    result = _land(local_tmp, StubProvider(fail_bars=True))

    bars = next(item for item in result.landings if item.dataset == "daily_bars")
    assert bars.status is DataStatus.SOURCE_ERROR
    assert bars.rows_written == 0
    # The securities listing landed; the failure did not erase it.
    assert (local_tmp / "securities.csv").is_file()
    assert not (local_tmp / "daily_bars.csv").exists()
    assert result.failed_datasets == ("daily_bars",)
    assert not result.is_complete


def test_a_file_of_another_dataset_is_refused_rather_than_appended(
    local_tmp: Path,
) -> None:
    (local_tmp / "daily_bars.csv").write_text(
        "code,date,price\n600519.SH,2026-09-03,10.0\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="shape"):
        land_raw(
            provider=StubProvider(),
            root=local_tmp,
            as_of=AS_OF,
            symbols=("600519.SH",),
        )


def test_a_row_shape_the_file_has_not_seen_widens_it_instead_of_failing(
    local_tmp: Path,
) -> None:
    """Instrument-specific columns appear as the market is covered.

    A whole-market statement legitimately gains columns when a bank or an
    insurer is in the batch; the file widens, and the rows that never carried
    the column stay empty rather than being refused or filled with a zero.
    """
    (local_tmp / "daily_bars.csv").write_text(
        "symbol,trade_date,close\n600519.SH,2026-09-03,10.0\n", encoding="utf-8"
    )

    class WiderProvider(StubProvider):
        def fetch(self, request: FetchRequest) -> RawDataset:
            self.requests.append(request)
            return RawDataset(
                provider="stub",
                dataset=request.dataset,
                fetched_at=FETCHED_AT,
                provider_version="v1",
                status=DataStatus.VALUE,
                row_count=1,
                payload=RawPayload(
                    columns=("symbol", "trade_date", "close", "deposit"),
                    rows=(("600519.SH", "2026-09-04", "11.0", "777.0"),),
                ),
            )

    land_raw(
        provider=WiderProvider(),
        root=local_tmp,
        as_of=AS_OF,
        symbols=("600519.SH",),
    )

    columns, rows = read_raw_rows(local_tmp / "daily_bars.csv")
    assert columns == ("symbol", "trade_date", "close", "deposit")
    assert rows == (
        ("600519.SH", "2026-09-03", "10.0", ""),  # never had a deposit
        ("600519.SH", "2026-09-04", "11.0", "777.0"),
    )


def test_landed_symbols_reads_only_the_dates_it_was_asked_about(
    local_tmp: Path,
) -> None:
    path = local_tmp / "daily_bars.csv"
    path.write_text(
        "symbol,trade_date,close\n"
        "600519.SH,2026-09-04,10.5\n"
        "000001.SZ,2026-09-03,9.0\n",
        encoding="utf-8",
    )

    assert landed_symbols(path, as_of=AS_OF) == frozenset({"600519.SH"})
    earlier = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    assert landed_symbols(path, as_of=earlier) == frozenset({"000001.SZ"})
    assert landed_symbols(local_tmp / "missing.csv", as_of=AS_OF) == frozenset()


def test_the_landing_record_names_the_file_and_the_date(local_tmp: Path) -> None:
    result = _land(local_tmp, StubProvider())

    for landing in result.landings:
        assert landing.path.parent == local_tmp
        assert landing.rows_total >= landing.rows_written
    assert result.as_of == AS_OF


def test_a_stub_provider_satisfies_the_provider_contract() -> None:
    """The type checker proves the stub is a real provider, not a mock shape."""
    provider: DataProvider = StubProvider()

    fetched = provider.fetch(FetchRequest(dataset="securities", as_of=AS_OF))
    assert isinstance(fetched, RawDataset)


def test_rows_are_written_verbatim_as_strings(local_tmp: Path) -> None:
    """Raw keeps the source's shape: no reformatting on the way to disk."""
    _land(local_tmp, StubProvider())

    text = (local_tmp / "daily_bars.csv").read_text(encoding="utf-8")

    assert text.splitlines()[0] == "symbol,trade_date,close"
    assert "10.5" in text


def test_an_empty_source_writes_no_file(local_tmp: Path) -> None:
    class EmptyProvider(StubProvider):
        def fetch(self, request: FetchRequest) -> RawDataset:
            self.requests.append(request)
            return RawDataset(
                provider="stub",
                dataset=request.dataset,
                fetched_at=FETCHED_AT,
                provider_version="v1",
                status=DataStatus.NULL,
                row_count=0,
                payload=None,
            )

    result = _land(local_tmp, EmptyProvider())

    assert all(landing.rows_written == 0 for landing in result.landings)
    assert not (local_tmp / "securities.csv").exists()
    assert not result.is_complete
