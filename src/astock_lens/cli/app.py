"""Typer CLI application assembly.

命令实现按职责拆分到独立模块；Trade Gate 继续由既有模块独立注册。
"""

import sys
from datetime import datetime

import typer

from astock_lens.cli import (
    calibration_commands,
    data_commands,
    discovery_commands,
    lifecycle_commands,
    pipeline_commands,
)
from astock_lens.cli import runtime as _cli_runtime
from astock_lens.cli.runtime import (
    _as_of,
    _benchmark_bars_path,
    _benchmark_subset,
    _bulk_provider,
    _financial_provider,
    _HeartbeatSink,
    _latest_industry_file,
    _neodata_provider,
    _production_industry_map,
    _store,
)
from astock_lens.cli.trade import trade_app
from astock_lens.pipelines.daily import run_daily

__all__ = [
    "_HeartbeatSink",
    "_as_of",
    "_benchmark_bars_path",
    "_benchmark_subset",
    "_bulk_provider",
    "_financial_provider",
    "_latest_industry_file",
    "_neodata_provider",
    "_production_industry_map",
    "_run_daily",
    "_store",
    "app",
    "run_daily",
    "sys",
]

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Local-first A-share discovery and research lifecycle system.",
)
factors_app = typer.Typer(no_args_is_help=True, help="Factor engine commands.")
universe_app = typer.Typer(no_args_is_help=True, help="Universe engine commands.")
calibrate_app = typer.Typer(
    no_args_is_help=True, help="Candidate qualification calibration commands."
)
strategy_app = typer.Typer(no_args_is_help=True, help="Strategy scanner commands.")
industry_app = typer.Typer(no_args_is_help=True, help="Industry membership commands.")
calendar_app = typer.Typer(no_args_is_help=True, help="Trading calendar commands.")
app.add_typer(factors_app, name="factors")
app.add_typer(universe_app, name="universe")
app.add_typer(calibrate_app, name="calibrate")
app.add_typer(strategy_app, name="strategy")
app.add_typer(industry_app, name="industry")
app.add_typer(calendar_app, name="calendar")
app.add_typer(trade_app, name="trade")


@app.callback()
def main() -> None:
    """Keep every command a named subcommand."""
    for name in (
        "_bulk_provider",
        "_financial_provider",
        "_neodata_provider",
        "run_daily",
    ):
        setattr(_cli_runtime, name, globals()[name])
        if name != "run_daily":
            setattr(data_commands, name, globals()[name])


def _run_daily(day: datetime, *, land: bool) -> object:
    """Compatibility wrapper for callers importing the former app helper."""
    main()
    return _cli_runtime._run_daily(day, land=land)


data_commands.register_doctor(app)
pipeline_commands.register_early(app, factors_app, universe_app, strategy_app)
discovery_commands.register(app)
lifecycle_commands.register_watch(app)
pipeline_commands.register_daily(app)
data_commands.register_commands(app, industry_app, calendar_app)
lifecycle_commands.register_research(app)
calibration_commands.register(calibrate_app)
