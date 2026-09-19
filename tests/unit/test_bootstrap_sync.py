"""Liquidity-bootstrap requirement.

Cold start has to fetch some price history before it can know which symbols are
liquid enough to research — `avg_amount_20d` is measured, not assumed. How much
history is "enough" is not a number this code may choose: it is whatever the
configured liquidity factor's window says. These tests pin that the number is
derived from configuration, that a missing or unreviewed configuration fails
loudly instead of falling back, and that the read-only CLI reports it without
touching any state.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astock_lens.cli.app import app
from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    BootstrapRequirementNotConfigured,
    ChunkSyncResult,
    land_bar_chunks,
    liquidity_bootstrap_requirement,
    strategy_history_requirement,
)
from astock_lens.data.bootstrap_checkpoint import BootstrapCheckpoint
from astock_lens.data.contracts import FetchRequest, RawDataset, RawPayload
from astock_lens.data.providers.akshare_provider import AkShareProvider
from astock_lens.data.sync import read_raw_rows
from astock_lens.domain.enums import DataStatus
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.universe.config import load_universe_config

ROOT = Path(__file__).resolve().parents[2]
FACTOR_DIR = ROOT / "configs" / "factors"
LIQUIDITY_FACTOR = "avg_amount_20d"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


def _universe_config() -> object:
    """仓库里的 Universe 配置：门槛是所有者决定的，测试只跟随、不改。"""
    return load_universe_config(ROOT / "configs" / "universe.yaml")


def _checkpoint(root: Path) -> BootstrapCheckpoint:
    """每一块落地都必须经检查点落分片，所以每个调用点都要传一个。"""
    return BootstrapCheckpoint(root, as_of=AS_OF.date(), required_valid_bars=20)


def _configs() -> tuple[FactorConfig, ...]:
    return tuple(load_factor_config(path) for path in sorted(FACTOR_DIR.glob("*.yaml")))


def _liquidity_config(**params: int | None) -> FactorConfig:
    """A liquidity factor config built from the real one, with a new window."""
    real = next(item for item in _configs() if item.name == LIQUIDITY_FACTOR)
    return real.model_copy(update={"params": {**real.params, **params}})


def test_the_requirement_comes_from_the_configured_window() -> None:
    configured = next(item for item in _configs() if item.name == LIQUIDITY_FACTOR)

    requirement = liquidity_bootstrap_requirement(_configs())

    assert isinstance(requirement, BootstrapRequirement)
    assert requirement.factor_name == LIQUIDITY_FACTOR
    assert requirement.required_valid_bars == configured.params["window"]


def test_removing_the_liquidity_factor_fails_loudly() -> None:
    without_it = tuple(item for item in _configs() if item.name != LIQUIDITY_FACTOR)

    with pytest.raises(BootstrapRequirementNotConfigured, match=LIQUIDITY_FACTOR):
        liquidity_bootstrap_requirement(without_it)


def test_an_unreviewed_window_fails_loudly_instead_of_defaulting() -> None:
    """`window: null` is how the config records "not reviewed yet"."""
    broken = (_liquidity_config(window=None),)

    with pytest.raises(BootstrapRequirementNotConfigured, match="window"):
        liquidity_bootstrap_requirement(broken)


def test_a_different_window_changes_the_requirement() -> None:
    """Proof the number is read, not hard-coded: another window moves it."""
    requirement = liquidity_bootstrap_requirement((_liquidity_config(window=61),))

    assert requirement.required_valid_bars == 61


def _price_config(name: str, window: int) -> FactorConfig:
    """A price-history factor config, built from a real one of the same shape."""
    base = next(item for item in _configs() if "window" in item.params)
    return base.model_copy(update={"name": name, "params": {"window": window}})


def test_the_strategy_history_requirement_comes_from_the_longest_window() -> None:
    """Enrichment must cover the longest trailing window any factor needs.

    The longest window in the shipped configuration is `proximity_52w_high`
    (252 bars), and a return factor needs one extra bar for its starting point.
    """
    requirement = strategy_history_requirement(_configs())

    windows = [
        config.params["window"]
        for config in _configs()
        if config.params.get("window") is not None
    ]
    assert requirement == max(windows)


def test_a_return_factor_needs_one_more_bar_than_its_window() -> None:
    """`ret_` factors compare two ends, so they need window + 1 observations."""
    just_a_return = (_price_config("ret_500d", 500),)

    assert strategy_history_requirement(just_a_return) == 501


def test_the_strategy_history_requirement_is_not_hard_coded() -> None:
    """A longer configured window must move the requirement, not be capped."""
    longer = (_price_config("proximity_1000d", 1000),)

    assert strategy_history_requirement(longer) == 1000


def test_a_windowed_factor_without_a_reviewed_window_fails_loudly() -> None:
    broken = (
        _price_config("ret_20d", 20).model_copy(update={"params": {"window": None}}),
    )

    with pytest.raises(BootstrapRequirementNotConfigured, match="window"):
        strategy_history_requirement(broken)


def test_the_cli_reports_the_derived_requirement_and_writes_nothing(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_root = local_tmp / "snapshots"
    watchlist_root = local_tmp / "watchlist"
    job_root = local_tmp / "jobs"
    for root in (snapshot_root, watchlist_root, job_root):
        root.mkdir()
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snapshot_root))
    monkeypatch.setenv("ASTOCK_WATCHLIST_ROOT", str(watchlist_root))
    monkeypatch.setenv("ASTOCK_JOB_ROOT", str(job_root))

    result = CliRunner().invoke(app, ["universe", "bootstrap-requirement"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["factor_name"] == LIQUIDITY_FACTOR
    assert payload["required_valid_bars"] == 20
    # 门槛在 configs/universe.yaml 里（所有者 2026-09-18 上调至 1.5 亿），命令只如实上报。
    configured_floor = _universe_config().min_average_turnover_20d  # type: ignore[attr-defined]
    assert payload["min_average_turnover_20d"] == configured_floor
    assert payload["min_listing_days"] == 120
    assert list(snapshot_root.iterdir()) == []
    assert list(watchlist_root.iterdir()) == []
    assert list(job_root.iterdir()) == []


def test_a_batch_size_must_be_a_real_batch_size(local_tmp: Path) -> None:
    """A zero or negative batch would ask for nothing and cover nothing."""
    with pytest.raises(ValueError, match="batch_size"):
        land_bar_chunks(
            fallback_source=_StubFetcher(),
            root=local_tmp,
            as_of=AS_OF,
            symbols=("000001.SZ",),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 17),
            batch_size=0,
            checkpoint=_checkpoint(local_tmp),
        )


class _StubFetcher:
    """Never called: the guard must reject the batch size first."""

    def fetch_symbol_bars(self, symbol: str, **_: object):  # type: ignore[no-untyped-def]
        raise AssertionError("the guard must run before any fetch")


def _akshare_with(
    rows_by_code: dict[str, tuple[tuple[str, ...], ...]],
) -> AkShareProvider:
    """A provider whose transport answers from a fixed table, per code."""
    columns = (
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover",
    )

    def transport(endpoint: str, params: dict[str, str]):
        assert endpoint == "stock_zh_a_hist_tx"
        return columns, rows_by_code.get(params["symbol"], ())

    return AkShareProvider(version="test", transport=transport)  # type: ignore[arg-type]


def test_the_single_symbol_primitive_reports_a_failure_instead_of_raising() -> None:
    """Isolation needs a verdict per symbol, not an exception for the batch."""
    provider = _akshare_with(
        {"sz000001": (("2026-09-17", "1", "1", "1", "1", "1", "1", "0.01"),)}
    )

    good = provider.fetch_symbol_bars(
        "000001.SZ",
        as_of=AS_OF,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 17),
    )
    missing = provider.fetch_symbol_bars(
        "600519.SH",
        as_of=AS_OF,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 17),
    )

    assert good.status is DataStatus.VALUE
    assert good.row_count == 1
    assert missing.status is DataStatus.SOURCE_ERROR
    assert missing.row_count == 0
    assert missing.payload is None


def test_the_batch_contract_still_fails_as_a_whole() -> None:
    """`fetch` keeps the answer it always gave: one bad symbol fails it all."""
    provider = _akshare_with(
        {"sz000001": (("2026-09-17", "1", "1", "1", "1", "1", "1", "0.01"),)}
    )

    dataset = provider.fetch(
        FetchRequest(
            dataset="daily_bars",
            as_of=AS_OF,
            symbols=("000001.SZ", "600519.SH"),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 17),
        )
    )

    assert dataset.status is DataStatus.SOURCE_ERROR
    assert dataset.row_count == 0


def test_a_chunk_lands_every_symbol_it_could_fetch(local_tmp: Path) -> None:
    provider = _StubFetcherWithRows()

    result = land_bar_chunks(
        fallback_source=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=provider.table,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 17),
        batch_size=2,
        checkpoint=_checkpoint(local_tmp),
    )

    assert isinstance(result, ChunkSyncResult)
    assert result.failed_symbols == ("600519.SH",)
    columns, rows = read_raw_rows(local_tmp / "daily_bars.csv")
    assert columns[0] == "symbol"
    assert {row[0] for row in rows} == {"000001.SZ", "300750.SZ"}


class _StubFetcherWithRows:
    """Two symbols answer, one fails — the shape a real cold start has."""

    table = ("000001.SZ", "600519.SH", "300750.SZ")
    columns = (
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

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        from datetime import UTC as _UTC

        fetched_at = datetime.now(_UTC)
        if symbol == "600519.SH":
            return RawDataset(
                provider="stub",
                dataset="daily_bars",
                fetched_at=fetched_at,
                provider_version="test",
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
            )
        row = (symbol, "2026-09-17", "1", "1", "1", "1", "1", "1", "0.01")
        return RawDataset(
            provider="stub",
            dataset="daily_bars",
            fetched_at=fetched_at,
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=1,
            payload=RawPayload(columns=self.columns, rows=(row,)),
        )


def test_concurrency_changes_the_speed_and_nothing_else(local_tmp: Path) -> None:
    """6 路并发必须与串行产出完全相同的落盘结果。

    并发的批准理由是速度（所有者 2026-09-18 明确同意 6 路）。它不允许改变语义：成功/失败
    集合、写入行数、整份文件的内容都必须与串行一致，否则"快"就变成了"结果不同"。完成顺序
    本来就会因并发而不同（这正是有界调度器按完成顺序回调的目的），所以这里比的是集合与
    落盘字节——行顺序由一次性压实按 symbol 裁决，与到达顺序无关。
    """
    symbols = tuple(f"{index:06d}.SZ" for index in range(12))

    serial_root = local_tmp / "serial"
    serial_root.mkdir()
    serial = land_bar_chunks(
        fallback_source=_StubFetcherWithRows(),
        root=serial_root,
        as_of=AS_OF,
        symbols=symbols,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 17),
        batch_size=5,
        checkpoint=_checkpoint(serial_root),
        max_inflight=1,
    )

    parallel_root = local_tmp / "parallel"
    parallel_root.mkdir()
    parallel = land_bar_chunks(
        fallback_source=_StubFetcherWithRows(),
        root=parallel_root,
        as_of=AS_OF,
        symbols=symbols,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 17),
        batch_size=5,
        checkpoint=_checkpoint(parallel_root),
        max_inflight=6,
    )

    assert set(parallel.completed_symbols) == set(serial.completed_symbols)
    assert set(parallel.failed_symbols) == set(serial.failed_symbols)
    assert parallel.rows_written == serial.rows_written
    assert read_raw_rows(parallel_root / "daily_bars.csv") == read_raw_rows(
        serial_root / "daily_bars.csv"
    )


def test_a_zero_in_flight_bound_is_refused(local_tmp: Path) -> None:
    with pytest.raises(ValueError, match="max_inflight"):
        land_bar_chunks(
            fallback_source=_StubFetcherWithRows(),
            root=local_tmp,
            as_of=AS_OF,
            symbols=("000001.SZ",),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 17),
            batch_size=5,
            checkpoint=_checkpoint(local_tmp),
            max_inflight=0,
        )
