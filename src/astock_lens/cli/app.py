"""Typer command line application.

The CLI is a first-class surface: it must stay usable from cron and from coding
agents without the Web UI. It never prints a reassuring summary for a run that
did nothing — a failure exits non-zero with the reason.
"""

import json
import os
import platform
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from pydantic import ValidationError

from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.pipelines.daily_scan import (
    DailyScanResult,
    UniverseBuildResult,
    build_universe,
    run_daily_scan,
)
from astock_lens.pipelines.first_slice import FirstSliceResult, run_first_slice
from astock_lens.settings import load_app_config
from astock_lens.strategies.config import load_strategy_config
from astock_lens.universe.config import load_universe_config

MINIMUM_PYTHON = (3, 12)

CSV_ROOT_ENV = "ASTOCK_CSV_ROOT"
SNAPSHOT_ROOT_ENV = "ASTOCK_SNAPSHOT_ROOT"
DATASET_ENV = "ASTOCK_DATASET"
SECURITIES_DATASET_ENV = "ASTOCK_SECURITIES_DATASET"
FACTOR_CONFIG_DIR_ENV = "ASTOCK_FACTOR_CONFIG_DIR"
UNIVERSE_CONFIG_ENV = "ASTOCK_UNIVERSE_CONFIG"
DEFAULT_CSV_ROOT = Path("data/raw")
DEFAULT_SNAPSHOT_ROOT = Path("data/snapshots")
DEFAULT_DATASET = "daily_bars"
DEFAULT_SECURITIES_DATASET = "securities"
DEFAULT_FACTOR_CONFIG_DIR = Path("configs/factors")
DEFAULT_UNIVERSE_CONFIG = Path("configs/universe.yaml")

STRATEGY_CONFIG_PATH = Path("configs/strategies/momentum.yaml")

# A bare trade date means the A-share close on that day.
SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE_HOUR = 15

AS_OF_OPTION = typer.Option("--as-of", help="Trade date, YYYY-MM-DD.")

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Local-first A-share discovery and research lifecycle system.",
)
factors_app = typer.Typer(
    no_args_is_help=True,
    help="Factor engine commands.",
)
app.add_typer(factors_app, name="factors")
universe_app = typer.Typer(
    no_args_is_help=True,
    help="Universe engine commands.",
)
app.add_typer(universe_app, name="universe")


@app.callback()
def main() -> None:
    """Keep every command a named subcommand.

    Without an explicit callback Typer promotes a single command to the root,
    which would make `astock doctor` an error.
    """


def _configured_config_path() -> Path:
    """Return the configuration path the loader would use."""
    return Path(os.getenv("ASTOCK_CONFIG", "configs/app.yaml"))


def _as_of(value: str) -> datetime:
    """Interpret a bare date as the A-share close on that day."""
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(
            f"--as-of must be YYYY-MM-DD, got {value!r}"
        ) from error
    return datetime(day.year, day.month, day.day, CLOSE_HOUR, tzinfo=SHANGHAI)


def _factor_configs() -> tuple[FactorConfig, ...]:
    """Load every factor configured under the factor directory.

    Every factor is computed for every symbol; the scanner then uses the subset
    its own configuration requires. Adding a factor is therefore a new file
    here rather than a code change.
    """
    directory = Path(os.getenv(FACTOR_CONFIG_DIR_ENV, str(DEFAULT_FACTOR_CONFIG_DIR)))
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        typer.echo(f"no factor configuration found under {directory}", err=True)
        raise typer.Exit(code=1)
    return tuple(load_factor_config(path) for path in paths)


def _run_slice(as_of_value: str) -> FirstSliceResult:
    """Run the first slice using the configured paths."""
    return run_first_slice(
        csv_root=_csv_root(),
        as_of=_as_of(as_of_value),
        factor_configs=_factor_configs(),
        strategy_config=load_strategy_config(STRATEGY_CONFIG_PATH),
        store=_store(),
        dataset=_dataset(),
    )


def _csv_root() -> Path:
    return Path(os.getenv(CSV_ROOT_ENV, str(DEFAULT_CSV_ROOT)))


def _dataset() -> str:
    return os.getenv(DATASET_ENV, DEFAULT_DATASET)


def _securities_dataset() -> str:
    return os.getenv(SECURITIES_DATASET_ENV, DEFAULT_SECURITIES_DATASET)


def _store() -> SnapshotStore:
    return resolve_snapshot_store(
        Path(os.getenv(SNAPSHOT_ROOT_ENV, str(DEFAULT_SNAPSHOT_ROOT)))
    )


def _run_universe(as_of_value: str) -> UniverseBuildResult:
    """Run the Universe stage using the configured paths."""
    return build_universe(
        csv_root=_csv_root(),
        as_of=_as_of(as_of_value),
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=_factor_configs(),
        store=_store(),
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )


def _run_daily_scan(as_of_value: str) -> DailyScanResult:
    """Run the daily scan using the configured paths."""
    return run_daily_scan(
        csv_root=_csv_root(),
        as_of=_as_of(as_of_value),
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=_factor_configs(),
        strategy_config=load_strategy_config(STRATEGY_CONFIG_PATH),
        store=_store(),
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )


def _universe_config_path() -> Path:
    return Path(os.getenv(UNIVERSE_CONFIG_ENV, str(DEFAULT_UNIVERSE_CONFIG)))


@app.command()
def doctor() -> None:
    """Check local configuration and runtime health.

    This command only reads local files. It never fetches market data, never
    contacts a provider, and never creates the DuckDB file.
    """
    failures: list[str] = []

    current = sys.version_info
    python_ok = (current.major, current.minor) >= MINIMUM_PYTHON
    typer.echo(
        f"Python {platform.python_version()} [{'ok' if python_ok else 'unsupported'}]"
    )
    if not python_ok:
        failures.append(
            f"Python >= 3.12 is required, found {platform.python_version()}"
        )

    config_path = _configured_config_path()
    try:
        config = load_app_config(config_path)
    except (OSError, ValueError, ValidationError) as error:
        typer.echo(f"config {config_path} [failed]", err=True)
        typer.echo(f"  {error}", err=True)
        failures.append(f"configuration could not be loaded from {config_path}")
    else:
        typer.echo(f"config {config_path} [ok]")
        typer.echo(f"app.name: {config.app.name}")
        # Missing paths are reported, not created: bootstrap must not write.
        for label, path in (
            ("storage.database", config.storage.database),
            ("storage.parquet_root", config.storage.parquet_root),
        ):
            presence = "present" if path.exists() else "absent"
            typer.echo(f"{label}: {path} [{presence}]")

    try:
        configured = _factor_configs()
    except (OSError, ValueError, ValidationError) as error:
        typer.echo("factor configs [failed]", err=True)
        typer.echo(f"  {error}", err=True)
        failures.append("factor configuration could not be loaded")
    else:
        typer.echo(f"factors: {', '.join(config.name for config in configured)}")

    strategy_path = STRATEGY_CONFIG_PATH
    try:
        strategy = load_strategy_config(strategy_path)
    except (OSError, ValueError, ValidationError) as error:
        typer.echo(f"strategy {strategy_path} [failed]", err=True)
        typer.echo(f"  {error}", err=True)
        failures.append(
            f"strategy configuration could not be loaded from {strategy_path}"
        )
    else:
        weights = (
            "none reviewed, a scan will not rank"
            if not strategy.weights
            else ", ".join(
                f"{name}={value}" for name, value in strategy.weights.items()
            )
        )
        typer.echo(f"strategy {strategy.id} {strategy.version} [ok]")
        typer.echo(f"  weights: {weights}")

    if failures:
        typer.echo("doctor found problems:", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)


@factors_app.command("compute")
def factors_compute(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Compute every configured factor and print one JSON document per result.

    Machine-readable output goes to stdout; run notes go to stderr, so the
    stream can be piped into another tool unchanged.
    """
    result = _run_slice(as_of)

    for factor_result in result.factor_results:
        typer.echo(
            json.dumps(factor_result.model_dump(mode="json"), ensure_ascii=False)
        )

    report = result.quality_report
    typer.echo(f"quality: {report.accepted}/{report.checked} bars accepted", err=True)
    typer.echo(f"snapshot: {result.factor_snapshot_path}", err=True)


@universe_app.command("build")
def universe_build(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Apply the Universe rules and write the UNIVERSE snapshot.

    Every verdict is printed: a symbol missing from the universe must always
    be answerable with the rule that removed it, and a deferred rule is
    reported as deferred rather than silently skipped.
    """
    result = _run_universe(as_of)
    universe = result.universe

    typer.echo(f"included: {len(universe.included)}")
    typer.echo(f"excluded: {len(universe.exclusions)}")
    by_rule = Counter(exclusion.rule.value for exclusion in universe.exclusions)
    for rule, count in sorted(by_rule.items()):
        typer.echo(f"  {rule}: {count}")
    for deferred in universe.deferred_rules:
        typer.echo(f"deferred: {deferred.rule.value} ({deferred.reason})")
    report = result.quality_report
    typer.echo(f"quality: {report.accepted}/{report.checked} bars accepted", err=True)
    typer.echo(f"snapshot: {result.universe_snapshot_path}")


@app.command()
def scan(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Run the daily scan and report the ranked candidates it produced.

    A candidate is a research object, not a recommendation. `next_action`
    follows from the score by ordering alone: an eligible symbol carrying a
    measured score is worth watching, and nothing else is.
    """
    result = _run_daily_scan(as_of)
    by_symbol = {item.symbol: item for item in result.strategy_results}

    typer.echo(f"candidates: {len(result.candidates)}")
    for candidate in result.candidates:
        strategy_result = by_symbol[candidate.symbol]
        score = (
            "score -"
            if strategy_result.score is None
            else f"score {strategy_result.score:.2f}"
        )
        typer.echo(f"  {candidate.symbol} -> {candidate.next_action} ({score})")
    typer.echo(f"snapshot: {result.candidate_snapshot_path}")
