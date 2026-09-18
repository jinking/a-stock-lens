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

import pytest
from typer.testing import CliRunner

from astock_lens.cli.app import app
from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    ChunkSyncResult,
    bootstrap_liquidity_history,
    land_bar_chunks,
)
from astock_lens.data.bootstrap_checkpoint import BootstrapCheckpoint
from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.data.sync import read_raw_rows
from astock_lens.domain.enums import DataStatus
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.pipelines import analysis
from astock_lens.pipelines.analysis import compute_research_universe
from astock_lens.universe.config import UniverseConfig, load_universe_config

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


def _parts_dir(root: Path) -> Path:
    return root / "bootstrap" / END_DATE.isoformat() / "parts"


def _checkpoint(root: Path) -> BootstrapCheckpoint:
    """每块落地都经检查点落分片，所以每个调用点都要传入它。"""
    return BootstrapCheckpoint(root, as_of=END_DATE, required_valid_bars=20)


def _staged_symbols(root: Path) -> set[str]:
    parts = _parts_dir(root)
    if not parts.is_dir():
        return set()
    return {path.stem for path in parts.glob("*.csv")}


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
        fallback_source=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("000001.SZ", "600519.SH", "300750.SZ"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        batch_size=2,
        checkpoint=_checkpoint(local_tmp),
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
        fallback_source=first_run,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("000001.SZ", "600519.SH"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        batch_size=10,
        checkpoint=_checkpoint(local_tmp),
    )

    second_run = FakeBarProvider(histories)
    result = land_bar_chunks(
        fallback_source=second_run,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("000001.SZ", "600519.SH"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        batch_size=10,
        checkpoint=_checkpoint(local_tmp),
    )

    assert [symbol for symbol, _, _ in second_run.requests] == ["600519.SH"]
    assert result.completed_symbols == ("600519.SH",)
    assert _symbols_in_file(_bars_path(local_tmp)) == {"000001.SZ", "600519.SH"}


def test_a_finished_symbol_is_on_disk_before_the_scheduler_forgets_it(
    local_tmp: Path,
) -> None:
    """Persistence per completion is what makes a crash resumable.

    落盘的形状变了两次（分片 + 清单；有界完成顺序调度），要钉住的性质没变：一有标的完成
    就得先在磁盘上，之后才能腾出 in-flight 名额去请求下一只。
    """
    symbols = ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ")
    seen_parts: list[set[str]] = []
    seen_file: list[bool] = []
    provider = FakeBarProvider({symbol: (date(2026, 8, 1), 1) for symbol in symbols})
    original = provider.fetch_symbol_bars
    max_inflight = 2

    def watching(symbol: str, *, as_of: datetime, start_date: date, end_date: date):
        seen_parts.append(_staged_symbols(local_tmp))
        seen_file.append(_bars_path(local_tmp).exists())
        return original(symbol, as_of=as_of, start_date=start_date, end_date=end_date)

    provider.fetch_symbol_bars = watching  # type: ignore[method-assign]

    land_bar_chunks(
        fallback_source=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=symbols,
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        batch_size=10,
        max_inflight=max_inflight,
        checkpoint=_checkpoint(local_tmp),
    )

    # 第 k 只标的被请求时，至少 k - max_inflight 只更早的标的已经把分片落在磁盘上：
    # 名额是靠"结果已消费"腾出来的，而消费就是先落盘、再记账。
    for requested, staged in enumerate(seen_parts, start=1):
        assert len(staged) >= max(requested - max_inflight, 0), (
            f"请求第 {requested} 只时只落盘了 {sorted(staged)}；"
            "完成的标的必须先落盘再让调度器继续提交"
        )
    assert seen_file == [False, False, False, False], (
        "整份 daily_bars.csv 不得在取数过程中被反复重写；它只在落地调用结束时压实一次"
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
        batch_source=None,
        fallback_source=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("600519.SH", "300750.SZ"),
        requirement=requirement,
        end_date=END_DATE,
        batch_size=10,
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
        batch_source=None,
        fallback_source=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=("688981.SH",),
        requirement=requirement,
        end_date=END_DATE,
        batch_size=10,
    )

    coverage = result.coverage[0]
    assert coverage.satisfied is False
    assert coverage.valid_bars == 8
    columns, rows = read_raw_rows(_bars_path(local_tmp))
    assert len(rows) == 8, "no row may be invented to reach the requirement"
    assert columns == BAR_COLUMNS


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "csv"


def _universe_config() -> UniverseConfig:
    return load_universe_config(
        Path(__file__).resolve().parents[2] / "configs" / "universe.yaml"
    )


def _factor_configs() -> tuple[FactorConfig, ...]:
    directory = Path(__file__).resolve().parents[2] / "configs" / "factors"
    return tuple(load_factor_config(path) for path in sorted(directory.glob("*.yaml")))


def test_the_research_universe_is_a_subset_of_the_listing_prefilter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two layers must agree: nothing reaches research that the prefilter dropped."""
    seen: list[tuple[str, ...]] = []
    original = analysis.factor_stage

    def watching(*, outcome, factor_configs, as_of):
        seen.append(tuple(config.name for config in factor_configs))
        return original(outcome=outcome, factor_configs=factor_configs, as_of=as_of)

    # Patch where the flow looks it up: `analysis` imported the stage directly.
    monkeypatch.setattr(analysis, "factor_stage", watching)

    state = compute_research_universe(
        csv_root=FIXTURE_ROOT,
        as_of=datetime(2026, 9, 4, 15, 0, tzinfo=UTC),
        universe_config=_universe_config(),
        factor_configs=_factor_configs(),
        dataset="daily_bars_long",
    )

    assert set(state.research_symbols) <= set(state.listing_prefilter_symbols)
    assert state.research_symbols, "the fixture carries symbols that must survive"
    assert seen == [("avg_amount_20d",)], (
        "deciding membership must compute the liquidity measure only, not all "
        f"24 factors; saw {seen}"
    )


def test_the_research_command_reports_an_observational_target_and_writes_nothing(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_root = local_tmp / "snapshots"
    watchlist_root = local_tmp / "watchlist"
    job_root = local_tmp / "jobs"
    for root in (snapshot_root, watchlist_root, job_root):
        root.mkdir()
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(FIXTURE_ROOT))
    monkeypatch.setenv("ASTOCK_DATASET", "daily_bars_long")
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snapshot_root))
    monkeypatch.setenv("ASTOCK_WATCHLIST_ROOT", str(watchlist_root))
    monkeypatch.setenv("ASTOCK_JOB_ROOT", str(job_root))

    result = CliRunner().invoke(app, ["universe", "research", "--as-of", "2026-09-04"])

    assert result.exit_code == 0, result.output
    assert "not a quota" in result.stdout
    assert "research universe" in result.stdout
    assert list(snapshot_root.iterdir()) == []
    assert list(watchlist_root.iterdir()) == []
    assert list(job_root.iterdir()) == []


SECURITIES_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "list_date",
    "is_st",
    "is_delisting_board",
    "suspended_trading_days",
]


def _write_listing(root: Path, *, broad: int, research: int) -> tuple[str, ...]:
    """Write a listing where only `research` symbols survive the prefilter.

    The other 60 are ST or too young, which is the cheapest way to build a
    broad/production-shaped split without inventing a business rule: those two
    exclusions already exist in `configs/universe.yaml`.
    """
    rows = [
        "symbol,name,exchange,list_date,is_st,is_delisting_board,suspended_trading_days"
    ]
    surviving: list[str] = []
    for index in range(broad):
        symbol = f"{index:06d}.SZ"
        if index < research:
            surviving.append(symbol)
            rows.append(f"{symbol},name{index},SZSE,2015-01-05,False,False,")
        elif index % 2 == 0:
            rows.append(f"{symbol},name{index},SZSE,2015-01-05,True,False,")
        else:
            rows.append(f"{symbol},name{index},SZSE,2026-09-10,False,False,")
    (root / "securities.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return tuple(surviving)


def _write_bars(root: Path, symbols: tuple[str, ...], *, days: int) -> None:
    rows = ["symbol,trade_date,open,high,low,close,volume,amount,turnover_rate"]
    for symbol in symbols:
        for offset in range(days):
            day = date(2026, 9, 17) - timedelta(days=offset)
            rows.append(f"{symbol},{day.isoformat()},10,11,9,10.5,1000,30000000,0.01")
    (root / "daily_bars.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


class RecordingProvider:
    """Narrow provider that records every symbol it was asked to enrich."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="recording",
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=datetime.now(UTC),
        )

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        self.asked.append(symbol)
        row = (symbol, end_date.isoformat(), "10", "11", "9", "10.5", "1", "1", "0.01")
        return RawDataset(
            provider="recording",
            dataset="daily_bars",
            fetched_at=datetime.now(UTC),
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=1,
            payload=RawPayload(columns=BAR_COLUMNS, rows=(row,)),
        )


def test_only_the_research_universe_is_asked_for_expensive_history(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """100 broad symbols / 40 research symbols: 40 requests, not 100."""
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_listing(csv_root, broad=100, research=40)
    _write_bars(csv_root, surviving, days=30)

    provider = RecordingProvider()
    monkeypatch.setattr("astock_lens.cli.app._bulk_provider", lambda: provider)
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(csv_root))

    result = CliRunner().invoke(app, ["sync-research", "--as-of", "2026-09-17"])

    assert result.exit_code == 0, result.output
    # The set is the claim, not the call count: a symbol short of history is
    # asked again with a wider window, and that retry is the resumable flow
    # working. What may never happen is a request for a symbol outside the
    # research population.
    assert set(provider.asked) == set(surviving), (
        "only the research population may be enriched; asked for "
        f"{sorted(set(provider.asked) - set(surviving))}"
    )
    assert len(set(provider.asked)) == 40
    assert "valuation enrichment: BLOCKED_PENDING_INDUSTRY_PATH" in result.stdout
