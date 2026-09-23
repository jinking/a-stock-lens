"""CLI 共用运行时：配置、存储与 Provider 组合。"""

import os
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import typer
from pydantic import BaseModel

from astock_lens.data.benchmark import BENCHMARK_BARS_ENV
from astock_lens.data.bootstrap_sources import SymbolBarFallbackSource
from astock_lens.data.contracts import DataProvider
from astock_lens.data.providers.akshare_provider import AkShareProvider
from astock_lens.data.providers.neodata import NeodataProvider
from astock_lens.data.providers.westock import WestockCliProvider
from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.data.storage.paths import StoragePaths, resolve_storage_paths
from astock_lens.domain.enums import SnapshotKind
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines.analysis import (
    AnalysisState,
    FactorState,
    compute_factor_state,
    run_analysis,
)
from astock_lens.settings import resolve_config_path
from astock_lens.strategies.registry import RegisteredStrategy, load_scanners
from astock_lens.universe.config import load_universe_config
from astock_lens.watchlist.store import WatchlistStore, resolve_watchlist_store

MINIMUM_PYTHON = (3, 12)
CSV_ROOT_ENV = "ASTOCK_CSV_ROOT"
DATASET_ENV = "ASTOCK_DATASET"
SECURITIES_DATASET_ENV = "ASTOCK_SECURITIES_DATASET"
WATCHLIST_BACKEND_ENV = "ASTOCK_WATCHLIST_BACKEND"
FACTOR_CONFIG_DIR_ENV = "ASTOCK_FACTOR_CONFIG_DIR"
UNIVERSE_CONFIG_ENV = "ASTOCK_UNIVERSE_CONFIG"
STRATEGY_CONFIG_DIR_ENV = "ASTOCK_STRATEGY_CONFIG_DIR"
DEFAULT_CSV_ROOT = Path("data/raw")
DEFAULT_DATASET = "daily_bars"
DEFAULT_SECURITIES_DATASET = "securities"
DEFAULT_FACTOR_CONFIG_DIR = Path("configs/factors")
DEFAULT_UNIVERSE_CONFIG = Path("configs/universe.yaml")
DEFAULT_STRATEGY_CONFIG_DIR = Path("configs/strategies")
STRATEGY_CONFIG_PATH = Path("configs/strategies/momentum.yaml")
LOW_COVERAGE_WARNING_RATIO = 0.90
SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE_HOUR = 15
AS_OF_OPTION = typer.Option("--as-of", help="Trade date, YYYY-MM-DD.")


def _configured_config_path() -> Path:
    return resolve_config_path()


def _as_of(value: str) -> datetime:
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(
            f"--as-of must be YYYY-MM-DD, got {value!r}"
        ) from error
    return datetime(day.year, day.month, day.day, CLOSE_HOUR, tzinfo=SHANGHAI)


def _factor_configs() -> tuple[FactorConfig, ...]:
    directory = Path(os.getenv(FACTOR_CONFIG_DIR_ENV, str(DEFAULT_FACTOR_CONFIG_DIR)))
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        typer.echo(f"no factor configuration found under {directory}", err=True)
        raise typer.Exit(code=1)
    return tuple(load_factor_config(path) for path in paths)


def _csv_root() -> Path:
    return Path(os.getenv(CSV_ROOT_ENV, str(DEFAULT_CSV_ROOT)))


def _dataset() -> str:
    return os.getenv(DATASET_ENV, DEFAULT_DATASET)


def _securities_dataset() -> str:
    return os.getenv(SECURITIES_DATASET_ENV, DEFAULT_SECURITIES_DATASET)


def _benchmark_bars_path() -> Path:
    configured_path = os.getenv(BENCHMARK_BARS_ENV)
    return (
        Path(configured_path) if configured_path else _csv_root() / "benchmark_bars.csv"
    )


def _storage_paths() -> StoragePaths:
    return resolve_storage_paths()


def _store() -> SnapshotStore:
    paths = _storage_paths()
    return resolve_snapshot_store(paths.snapshot_root, database=paths.database)


def _factor_state(as_of_value: str) -> FactorState:
    return compute_factor_state(
        csv_root=_csv_root(),
        as_of=_as_of(as_of_value),
        factor_configs=_factor_configs(),
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )


def _analysis(
    as_of_value: str, *, scanners: Sequence[RegisteredStrategy]
) -> AnalysisState:
    return run_analysis(
        csv_root=_csv_root(),
        as_of=_as_of(as_of_value),
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=_factor_configs(),
        scanners=scanners,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )


def _universe_state(as_of_value: str) -> AnalysisState:
    return _analysis(as_of_value, scanners=())


def _preview_state(as_of_value: str) -> AnalysisState:
    return _analysis(as_of_value, scanners=load_scanners(_strategy_dir()))


def _universe_config_path() -> Path:
    return Path(os.getenv(UNIVERSE_CONFIG_ENV, str(DEFAULT_UNIVERSE_CONFIG)))


def _strategy_dir() -> Path:
    return Path(os.getenv(STRATEGY_CONFIG_DIR_ENV, str(DEFAULT_STRATEGY_CONFIG_DIR)))


def _watchlist_store() -> WatchlistStore:
    paths = _storage_paths()
    return resolve_watchlist_store(paths.watchlist_root, database=paths.database)


def _job_store() -> JsonJobStore:
    return JsonJobStore(_storage_paths().job_root)


def _financial_provider() -> WestockCliProvider:
    return WestockCliProvider()


def _neodata_provider(batch_size: int | None = None) -> NeodataProvider:
    return (
        NeodataProvider()
        if batch_size is None
        else NeodataProvider(batch_size=batch_size)
    )


def _bulk_provider() -> DataProvider:
    return AkShareProvider()


def _symbol_bar_provider(provider: DataProvider) -> SymbolBarFallbackSource:
    if not isinstance(provider, SymbolBarFallbackSource):
        typer.echo(
            f"provider {provider.health().provider} cannot fetch one symbol at a "
            "time, so the bootstrap cannot isolate failures with it",
            err=True,
        )
        raise typer.Exit(code=1)
    return provider


def _snapshot_records[T: BaseModel](
    kind: SnapshotKind, as_of: datetime, model: type[T]
) -> tuple[T, ...]:
    return tuple(model.model_validate(record) for record in _store().read(kind, as_of))


def _value_text(value: float | None, status: object) -> str:
    return "no value" if value is None else f"{value} ({status})"
