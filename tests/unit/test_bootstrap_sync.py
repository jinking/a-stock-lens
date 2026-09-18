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
)
from astock_lens.data.contracts import FetchRequest, RawDataset, RawPayload
from astock_lens.data.providers.akshare_provider import AkShareProvider
from astock_lens.data.sync import read_raw_rows
from astock_lens.domain.enums import DataStatus
from astock_lens.factors.config import FactorConfig, load_factor_config

ROOT = Path(__file__).resolve().parents[2]
FACTOR_DIR = ROOT / "configs" / "factors"
LIQUIDITY_FACTOR = "avg_amount_20d"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


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
    assert payload["min_average_turnover_20d"] == 20_000_000
    assert payload["min_listing_days"] == 120
    assert list(snapshot_root.iterdir()) == []
    assert list(watchlist_root.iterdir()) == []
    assert list(job_root.iterdir()) == []


def test_a_chunk_size_must_be_a_real_chunk_size(local_tmp: Path) -> None:
    """A zero or negative chunk would loop forever or land nothing."""
    with pytest.raises(ValueError, match="chunk_size"):
        land_bar_chunks(
            provider=_StubFetcher(),
            root=local_tmp,
            as_of=AS_OF,
            symbols=("000001.SZ",),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 17),
            chunk_size=0,
        )


class _StubFetcher:
    """Never called: the guard must reject the chunk size first."""

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
        provider=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=provider.table,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 17),
        chunk_size=2,
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
