"""Typer command line application.

The CLI is a first-class surface: it must stay usable from cron and from coding
agents without the Web UI. It never prints a reassuring summary for a run that
did nothing — a failure exits non-zero with the reason.
"""

import json
import os
import platform
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from pydantic import ValidationError

from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.factors.config import load_factor_config
from astock_lens.pipelines.first_slice import FirstSliceResult, run_first_slice
from astock_lens.settings import load_app_config
from astock_lens.strategies.config import load_strategy_config

MINIMUM_PYTHON = (3, 12)

CSV_ROOT_ENV = "ASTOCK_CSV_ROOT"
SNAPSHOT_ROOT_ENV = "ASTOCK_SNAPSHOT_ROOT"
DEFAULT_CSV_ROOT = Path("data/raw")
DEFAULT_SNAPSHOT_ROOT = Path("data/snapshots")

FACTOR_CONFIG_PATH = Path("configs/factors/avg_amount_20d.yaml")
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


def _run_slice(as_of_value: str) -> FirstSliceResult:
    """Run the first slice using the configured paths."""
    return run_first_slice(
        csv_root=Path(os.getenv(CSV_ROOT_ENV, str(DEFAULT_CSV_ROOT))),
        as_of=_as_of(as_of_value),
        factor_config=load_factor_config(FACTOR_CONFIG_PATH),
        strategy_config=load_strategy_config(STRATEGY_CONFIG_PATH),
        store=JsonSnapshotStore(
            Path(os.getenv(SNAPSHOT_ROOT_ENV, str(DEFAULT_SNAPSHOT_ROOT)))
        ),
    )


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

    if failures:
        typer.echo("doctor found problems:", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)


@factors_app.command("compute")
def factors_compute(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Compute the configured factors and print one JSON document per result.

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


@app.command()
def scan(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Run the first slice and report the candidates it produced.

    A candidate is a research object, not a recommendation. Every candidate
    currently carries `IGNORE` because no reviewed routing rule exists yet.
    """
    result = _run_slice(as_of)

    typer.echo(f"candidates: {len(result.candidates)}")
    for candidate in result.candidates:
        typer.echo(f"  {candidate.symbol} -> {candidate.next_action}")
    typer.echo(f"snapshot: {result.candidate_snapshot_path}")
