"""Typer command line application.

The CLI is a first-class surface: it must stay usable from cron and from coding
agents without the Web UI. Only bootstrap-safe commands exist so far.
"""

import os
import platform
import sys
from pathlib import Path

import typer
from pydantic import ValidationError

from astock_lens.settings import load_app_config

MINIMUM_PYTHON = (3, 12)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Local-first A-share discovery and research lifecycle system.",
)


@app.callback()
def main() -> None:
    """Keep `doctor` a named subcommand.

    Without an explicit callback Typer promotes a single command to the root,
    which would make `astock doctor` an error.
    """


def _configured_config_path() -> Path:
    """Return the configuration path the loader would use."""
    return Path(os.getenv("ASTOCK_CONFIG", "configs/app.yaml"))


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
