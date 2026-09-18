"""Cold-start bootstrap for a broad listing.

A whole-market cold start cannot be one long all-or-nothing fetch: a single bad
symbol would lose the work of every symbol before it, and a rerun would start
over. These tests pin the three properties that make the flow usable —
per-symbol failure isolation, resume by coverage rather than by restart, and a
success condition measured in valid bars instead of calendar days.

The provider is a fake on purpose: a test that reaches AkShare would report
whether the network is up, not whether the flow is correct.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    ChunkSyncResult,
    bootstrap_liquidity_history,
    land_bar_chunks,
)
from astock_lens.data.contracts import FetchRequest, RawDataset, RawPayload
from astock_lens.data.sync import read_raw_rows
from astock_lens.domain.enums import DataStatus

AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
END_DATE = date(2026, 9, 17)
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


class FakeBarProvider:
    """Serves one symbol's history on demand, and can be told to fail.

    `histories` maps a symbol to (first day with data, days between rows). A
    step greater than one stands for a sparse instrument whose history fills a
    calendar window more slowly than a daily one.
    """

    def __init__(
        self,
        histories: dict[str, tuple[date, int]],
        *,
        failing: set[str] | None = None,
    ) -> None:
        self.histories = histories
        self.failing = set(failing or ())
        self.requests: list[tuple[str, date, date]] = []

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        self.requests.append((symbol, start_date, end_date))
        fetched_at = datetime.now(UTC)
        first, step = self.histories.get(symbol, (end_date, 1))

        if symbol in self.failing:
            return RawDataset(
                provider="fake",
                dataset="daily_bars",
                fetched_at=fetched_at,
                provider_version="test",
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
                message=f"{symbol} could not be fetched",
            )

        rows: list[tuple[str, ...]] = []
        day = first
        while day <= end_date:
            if day >= start_date:
                rows.append(
                    (symbol, day.isoformat(), "1", "1", "1", "1", "1", "1000", "0.01")
                )
            day += timedelta(days=step)

        if not rows:
            return RawDataset(
                provider="fake",
                dataset="daily_bars",
                fetched_at=fetched_at,
                provider_version="test",
                status=DataStatus.NULL,
                row_count=0,
            )
        return RawDataset(
            provider="fake",
            dataset="daily_bars",
            fetched_at=fetched_at,
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=BAR_COLUMNS, rows=tuple(rows)),
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        raise AssertionError("the bootstrap flow must use fetch_symbol_bars")


def _bars_path(root: Path) -> Path:
    return root / "daily_bars.csv"


def _symbols_in_file(path: Path) -> set[str]:
    columns, rows = read_raw_rows(path)
    if "symbol" not in columns:
        return set()
    index = columns.index("symbol")
    return {row[index] for row in rows}


def test_a_failed_symbol_keeps_the_symbols_that_succeeded(
    local_tmp: Path,
) -> None:
    provider = FakeBarProvider(
        {
            "000001.SZ": (date(2026, 8, 1), 1),
            "600519.SH": (date(2026, 8, 1), 1),
            "300750.SZ": (date(2026, 8, 1), 1),
        },
        failing={"600519.SH"},
    )

    result = land_bar_chunks(
        provider=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("000001.SZ", "600519.SH", "300750.SZ"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        chunk_size=2,
    )

    assert isinstance(result, ChunkSyncResult)
    assert result.completed_symbols == ("000001.SZ", "300750.SZ")
    assert result.failed_symbols == ("600519.SH",)
    assert result.rows_written > 0
    # The failure is visible in the file's absence of the symbol, never as a
    # row of invented values.
    assert _symbols_in_file(_bars_path(local_tmp)) == {"000001.SZ", "300750.SZ"}


def test_a_rerun_retries_only_the_coverage_that_is_missing(local_tmp: Path) -> None:
    histories = {
        "000001.SZ": (date(2026, 8, 1), 1),
        "600519.SH": (date(2026, 8, 1), 1),
    }
    first_run = FakeBarProvider(histories, failing={"600519.SH"})
    land_bar_chunks(
        provider=first_run,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("000001.SZ", "600519.SH"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        chunk_size=10,
    )

    second_run = FakeBarProvider(histories)
    result = land_bar_chunks(
        provider=second_run,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("000001.SZ", "600519.SH"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        chunk_size=10,
    )

    assert [symbol for symbol, _, _ in second_run.requests] == ["600519.SH"]
    assert result.completed_symbols == ("600519.SH",)
    assert _symbols_in_file(_bars_path(local_tmp)) == {"000001.SZ", "600519.SH"}


def test_each_chunk_is_on_disk_before_the_next_chunk_is_requested(
    local_tmp: Path,
) -> None:
    """Persistence per chunk is what makes a crash resumable."""
    seen: list[set[str]] = []
    provider = FakeBarProvider(
        {
            "000001.SZ": (date(2026, 8, 1), 1),
            "000002.SZ": (date(2026, 8, 1), 1),
            "600519.SH": (date(2026, 8, 1), 1),
        }
    )
    original = provider.fetch_symbol_bars

    def watching(symbol: str, *, as_of: datetime, start_date: date, end_date: date):
        seen.append(_symbols_in_file(_bars_path(local_tmp)))
        return original(symbol, as_of=as_of, start_date=start_date, end_date=end_date)

    provider.fetch_symbol_bars = watching  # type: ignore[method-assign]

    land_bar_chunks(
        provider=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("000001.SZ", "000002.SZ", "600519.SH"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        chunk_size=2,
    )

    assert seen[0] == set()
    assert seen[1] == set()
    assert seen[2] == {"000001.SZ", "000002.SZ"}, (
        "the first chunk must be persisted before the second chunk is requested"
    )


def test_short_history_is_extended_backward_until_it_is_enough(
    local_tmp: Path,
) -> None:
    provider = FakeBarProvider(
        {
            "600519.SH": (date(2026, 1, 1), 1),
            "300750.SZ": (date(2026, 6, 1), 3),
        }
    )
    requirement = BootstrapRequirement(
        factor_name="avg_amount_20d", required_valid_bars=20
    )

    result = bootstrap_liquidity_history(
        provider=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("600519.SH", "300750.SZ"),
        requirement=requirement,
        end_date=END_DATE,
        chunk_size=10,
    )

    sparse = next(item for item in result.coverage if item.symbol == "300750.SZ")
    assert sparse.valid_bars >= requirement.required_valid_bars
    assert sparse.satisfied is True
    # The sparse symbol needed a wider window than the first request carried.
    widths = {start for symbol, start, _ in provider.requests if symbol == "300750.SZ"}
    assert min(widths) < max(widths), "the flow must extend backward, not give up"


def test_history_that_runs_out_is_reported_short_not_padded(local_tmp: Path) -> None:
    provider = FakeBarProvider({"688981.SH": (date(2026, 9, 10), 1)})
    requirement = BootstrapRequirement(
        factor_name="avg_amount_20d", required_valid_bars=20
    )

    result = bootstrap_liquidity_history(
        provider=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("688981.SH",),
        requirement=requirement,
        end_date=END_DATE,
        chunk_size=10,
    )

    coverage = result.coverage[0]
    assert coverage.satisfied is False
    assert coverage.valid_bars == 8
    columns, rows = read_raw_rows(_bars_path(local_tmp))
    assert len(rows) == 8, "no row may be invented to reach the requirement"
    assert columns == BAR_COLUMNS
