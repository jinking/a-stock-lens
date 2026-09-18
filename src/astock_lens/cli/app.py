"""Typer command line application.

The CLI is a first-class surface: it must stay usable from cron and from coding
agents without the Web UI. It never prints a reassuring summary for a run that
did nothing — a failure exits non-zero with the reason.
"""

import csv
import json
import os
import platform
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from pydantic import BaseModel, ValidationError

from astock_lens.calibration.candidate_report import generate_calibration_report
from astock_lens.calibration.factor_distribution import CalibrationPopulation
from astock_lens.calibration.render import render_json, render_markdown
from astock_lens.candidates.models import Candidate
from astock_lens.data.bootstrap import (
    bootstrap_liquidity_history,
    bootstrap_strategy_history,
    liquidity_bootstrap_requirement,
    strategy_history_requirement,
)
from astock_lens.data.bootstrap_sources import SymbolBarFallbackSource
from astock_lens.data.contracts import DataProvider, FetchRequest
from astock_lens.data.health import raw_datasets
from astock_lens.data.industry import (
    WestockSectorSource,
    build_industry_map,
)
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.providers.akshare_provider import AkShareProvider
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.providers.neodata import NeodataProvider
from astock_lens.data.providers.westock import FINANCIAL_DATASETS, WestockCliProvider
from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.data.sync import (
    DONE_STATUSES,
    INDUSTRY_ROOT,
    DatasetLanding,
    SyncResult,
    land_financial_statements,
    land_industry_memberships,
    land_neodata_blocks,
    land_raw,
    land_securities_listing,
    read_industry_memberships,
    read_raw_rows,
    read_symbols,
)
from astock_lens.domain.enums import SnapshotKind, WatchlistState
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.factors.contracts import FactorResult
from astock_lens.jobs.models import StageOutcome
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines import stages
from astock_lens.pipelines.analysis import (
    AnalysisState,
    FactorState,
    compute_factor_state,
    compute_research_universe,
    run_analysis,
    run_research_analysis,
)
from astock_lens.pipelines.daily import DailyRunResult, run_daily
from astock_lens.research.adapters.cli import (
    CliDeepResearchAdapter,
    DeepResearchInvocationError,
    DeepResearchNotConfigured,
    resolve_adapter,
)
from astock_lens.research.models import ResearchRequest
from astock_lens.settings import load_app_config
from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.registry import (
    RegisteredStrategy,
    StrategyNotImplementedError,
    build_scanner,
    load_scanners,
    strategy_paths,
)
from astock_lens.universe.config import load_universe_config
from astock_lens.universe.models import UniverseSnapshot
from astock_lens.universe.prefilter import prefilter_listing
from astock_lens.watchlist.models import WatchlistEntry
from astock_lens.watchlist.state_machine import (
    WatchlistTransitionError,
    open_entry,
    transition,
)
from astock_lens.watchlist.store import WatchlistStore, resolve_watchlist_store

MINIMUM_PYTHON = (3, 12)

CSV_ROOT_ENV = "ASTOCK_CSV_ROOT"
SNAPSHOT_ROOT_ENV = "ASTOCK_SNAPSHOT_ROOT"
WATCHLIST_ROOT_ENV = "ASTOCK_WATCHLIST_ROOT"
WATCHLIST_BACKEND_ENV = "ASTOCK_WATCHLIST_BACKEND"
JOB_ROOT_ENV = "ASTOCK_JOB_ROOT"
DATASET_ENV = "ASTOCK_DATASET"
SECURITIES_DATASET_ENV = "ASTOCK_SECURITIES_DATASET"
FACTOR_CONFIG_DIR_ENV = "ASTOCK_FACTOR_CONFIG_DIR"
UNIVERSE_CONFIG_ENV = "ASTOCK_UNIVERSE_CONFIG"
STRATEGY_CONFIG_DIR_ENV = "ASTOCK_STRATEGY_CONFIG_DIR"
DEFAULT_CSV_ROOT = Path("data/raw")
DEFAULT_SNAPSHOT_ROOT = Path("data/snapshots")
DEFAULT_WATCHLIST_ROOT = Path("data/watchlist")
DEFAULT_JOB_ROOT = Path("var/jobs")
DEFAULT_DATASET = "daily_bars"
DEFAULT_SECURITIES_DATASET = "securities"
DEFAULT_FACTOR_CONFIG_DIR = Path("configs/factors")
DEFAULT_UNIVERSE_CONFIG = Path("configs/universe.yaml")
DEFAULT_STRATEGY_CONFIG_DIR = Path("configs/strategies")

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
calibrate_app = typer.Typer(
    no_args_is_help=True,
    help="Candidate qualification calibration commands.",
)
app.add_typer(calibrate_app, name="calibrate")


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


def _factor_state(as_of_value: str) -> FactorState:
    """把因子算完就停下，配置文件里的路径全部照旧生效。"""
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
    """跑唯一分析执行链；它只计算，不落任何正式快照。"""
    return run_analysis(
        csv_root=_csv_root(),
        as_of=_as_of(as_of_value),
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=_factor_configs(),
        scanners=scanners,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
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


def _universe_state(as_of_value: str) -> AnalysisState:
    """跑到 Universe 为止：不配置 Scanner，就不做任何策略计算。"""
    return _analysis(as_of_value, scanners=())


def _preview_state(as_of_value: str) -> AnalysisState:
    """预览用完整分析链：跑遍所有已实现的 Scanner，但不落盘。"""
    return _analysis(as_of_value, scanners=load_scanners(_strategy_dir()))


def _universe_config_path() -> Path:
    return Path(os.getenv(UNIVERSE_CONFIG_ENV, str(DEFAULT_UNIVERSE_CONFIG)))


def _strategy_dir() -> Path:
    return Path(os.getenv(STRATEGY_CONFIG_DIR_ENV, str(DEFAULT_STRATEGY_CONFIG_DIR)))


def _watchlist_store() -> WatchlistStore:
    root = Path(os.getenv(WATCHLIST_ROOT_ENV, str(DEFAULT_WATCHLIST_ROOT)))
    return resolve_watchlist_store(root)


def _job_store() -> JsonJobStore:
    return JsonJobStore(Path(os.getenv(JOB_ROOT_ENV, str(DEFAULT_JOB_ROOT))))


def _financial_provider() -> WestockCliProvider:
    """The provider financial statements are landed from (design spec §24)."""
    return WestockCliProvider()


def _neodata_provider() -> NeodataProvider:
    """语义与估值数据源（规格 §24 补遗）。"""
    return NeodataProvider()


def _bulk_provider() -> DataProvider:
    """The bulk provider `astock sync` lands data from.

    Named once so a test (or a future provider swap) can replace it without
    touching the commands that use it.
    """
    return AkShareProvider()


def _symbol_bar_provider(provider: DataProvider) -> SymbolBarFallbackSource:
    """The bulk provider narrowed to the symbol-level contract.

    Isolation between symbols is only possible when the provider answers for
    one symbol at a time. Saying which provider cannot do that here keeps the
    limitation visible, instead of failing somewhere deep in the flow.
    """
    if not isinstance(provider, SymbolBarFallbackSource):
        typer.echo(
            f"provider {provider.health().provider} cannot fetch one symbol at a "
            "time, so the bootstrap cannot isolate failures with it",
            err=True,
        )
        raise typer.Exit(code=1)
    return provider


def _today_close() -> datetime:
    """The A-share close on the current date in Shanghai."""
    today = datetime.now(SHANGHAI).date()
    return datetime(today.year, today.month, today.day, CLOSE_HOUR, tzinfo=SHANGHAI)


def _snapshot_records[T: BaseModel](
    kind: SnapshotKind, as_of: datetime, model: type[T]
) -> tuple[T, ...]:
    """Read one snapshot and parse it back into the model that wrote it."""
    return tuple(model.model_validate(record) for record in _store().read(kind, as_of))


def _value_text(value: float | None, status: object) -> str:
    """Show a measurement, or the reason there is none."""
    return "no value" if value is None else f"{value} ({status})"


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

    # Data Health (`docs/DATA_SOURCES.md` §4): what a scan would read, and how
    # fresh it is. This reads local files only — it never fetches, so it cannot
    # turn a health check into a data-pipeline run.
    csv_root = _csv_root()
    presence = "ok" if csv_root.is_dir() else "missing"
    typer.echo(f"provider local-csv: {csv_root} [{presence}]")
    datasets = raw_datasets(csv_root)
    if not datasets:
        typer.echo("  datasets: none landed under this root")
    for freshness in datasets:
        span = (
            f"{freshness.first_trade_date} .. {freshness.last_trade_date}"
            if freshness.covers_dates
            else "no trade_date column"
        )
        unreadable = (
            f", {freshness.unreadable_trade_dates} unreadable trade dates"
            if freshness.unreadable_trade_dates
            else ""
        )
        typer.echo(f"  {freshness.dataset}: {freshness.rows} rows, {span}{unreadable}")

    provider_health = _bulk_provider().health()
    provider_state = "ok" if provider_health.healthy else "unavailable"
    detail = f" ({provider_health.message})" if provider_health.message else ""
    typer.echo(f"provider {provider_health.provider} [{provider_state}]{detail}")

    # The financial-statement source (design spec §24). Reported without being
    # run: `doctor` stays read-only, and liveness is only proven by a fetch.
    westock_health = WestockCliProvider().health()
    westock_state = "ok" if westock_health.healthy else "unavailable"
    westock_detail = f" ({westock_health.message})" if westock_health.message else ""
    typer.echo(f"provider {westock_health.provider} [{westock_state}]{westock_detail}")

    # 语义数据源（规格 §24 补遗，2026-09-17 修订）：估值、行业与语义维度的主数据源，
    # 同时是财报的交叉验证源。凭证 12 小时过期且只能由平台刷新，因此状态必须一眼可见。
    neodata_health = NeodataProvider().health()
    neodata_state = "ok" if neodata_health.healthy else "unavailable"
    neodata_detail = f" ({neodata_health.message})" if neodata_health.message else ""
    typer.echo(f"provider {neodata_health.provider} [{neodata_state}]{neodata_detail}")

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

    This is a computation, not a run. Nothing is persisted: asking what a
    factor currently measures must never rewrite the day's formal snapshots.
    """
    measured = _factor_state(as_of)

    for factor_result in measured.factor_results:
        typer.echo(
            json.dumps(factor_result.model_dump(mode="json"), ensure_ascii=False)
        )

    report = measured.outcome.quality_report
    typer.echo(f"quality: {report.accepted}/{report.checked} bars accepted", err=True)
    typer.echo("snapshot: none (a computation does not write)", err=True)


@universe_app.command("research")
def universe_research(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Show the Research Universe this data would produce. It writes nothing.

    The count is reported, not enforced: the approved semantics put the target
    around 2,000–3,000 symbols as an observation, and a result of 1,850 or 3,200
    must never move a threshold to reach a rounder number.
    """
    day = _as_of(as_of)
    state = compute_research_universe(
        csv_root=_csv_root(),
        as_of=day,
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=_factor_configs(),
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )

    by_rule = Counter(exclusion.rule.value for exclusion in state.excluded)
    typer.echo(f"listing prefilter: {len(state.listing_prefilter_symbols)} symbols")
    typer.echo(f"research universe: {len(state.research_symbols)} symbols")
    for rule, count in sorted(by_rule.items()):
        typer.echo(f"  excluded by {rule}: {count}")
    typer.echo("target size is observational (approximately 2,000-3,000), not a quota")
    typer.echo("snapshot: none written (preview)", err=True)


@universe_app.command("bootstrap-requirement")
def universe_bootstrap_requirement() -> None:
    """Report how much price history the liquidity rule needs before it can run.

    A cold start has to fetch bars before `avg_amount_20d` can be measured, and
    how many bars that takes comes from the configured factor's window — not
    from this command. Read-only: it prints the derived requirement plus the two
    approved Universe thresholds and writes nothing anywhere.
    """
    requirement = liquidity_bootstrap_requirement(_factor_configs())
    config = load_universe_config(_universe_config_path())

    typer.echo(
        json.dumps(
            {
                "factor_name": requirement.factor_name,
                "required_valid_bars": requirement.required_valid_bars,
                "min_average_turnover_20d": config.min_average_turnover_20d,
                "min_listing_days": config.min_listing_days,
            },
            ensure_ascii=False,
        )
    )


@universe_app.command("build")
def universe_build(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Apply the Universe rules and report every verdict. It writes nothing.

    Every verdict is printed: a symbol missing from the universe must always
    be answerable with the rule that removed it, and a deferred rule is
    reported as deferred rather than silently skipped.

    Formal daily snapshots are written only by `astock daily`.
    """
    analysis = _universe_state(as_of)
    universe = analysis.universe

    typer.echo(f"included: {len(universe.included)}")
    typer.echo(f"excluded: {len(universe.exclusions)}")
    by_rule = Counter(exclusion.rule.value for exclusion in universe.exclusions)
    for rule, count in sorted(by_rule.items()):
        typer.echo(f"  {rule}: {count}")
    for deferred in universe.deferred_rules:
        typer.echo(f"deferred: {deferred.rule.value} ({deferred.reason})")
    report = analysis.outcome.quality_report
    typer.echo(f"quality: {report.accepted}/{report.checked} bars accepted", err=True)
    typer.echo("snapshot: none (a computation does not write)", err=True)


@app.command()
def scan(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Run a non-persistent scan preview.

    Every enabled scanner scores the Universe this run admits, and the rankings
    are printed for inspection. Formal daily snapshots are written only by
    `astock daily`; a preview never writes, so it can never replace the day's
    formal result with a subset of it.
    """
    analysis = _preview_state(as_of)

    typer.echo(f"universe: {len(analysis.universe.included)} symbols considered")
    for strategy_id in sorted(
        {result.strategy_id for result in analysis.strategy_results}
    ):
        typer.echo(f"{strategy_id}:")
        for result in _ranked(
            tuple(
                item
                for item in analysis.strategy_results
                if item.strategy_id == strategy_id
            )
        ):
            score = "no score" if result.score is None else f"score {result.score:.2f}"
            verdict = "eligible" if result.eligible else "not eligible"
            typer.echo(f"  {result.symbol} {score} ({verdict})")
    typer.echo("snapshot: none written (preview)", err=True)


strategy_app = typer.Typer(
    no_args_is_help=True,
    help="Strategy scanner commands.",
)
app.add_typer(strategy_app, name="strategy")


@strategy_app.command("run")
def strategy_run(
    strategy: Annotated[str, typer.Argument(help="Strategy id, e.g. momentum.")],
    as_of: Annotated[str, AS_OF_OPTION],
) -> None:
    """Score the Universe with one scanner and print its ranking.

    This runs one scanner against the current data and prints where it placed
    each symbol. It writes no snapshot: the daily pipeline owns the day's
    snapshots, and a targeted run must not overwrite them with a subset.
    """
    day = _as_of(as_of)
    try:
        config = _strategy_config(strategy)
        scanner = build_scanner(config)
    except StrategyNotImplementedError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    outcome = stages.normalize_stage(
        csv_root=_csv_root(),
        as_of=day,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )
    factor_results = stages.factor_stage(
        outcome=outcome, factor_configs=_factor_configs(), as_of=day
    )
    universe = stages.universe_stage(
        outcome=outcome,
        factor_results=factor_results,
        config=load_universe_config(_universe_config_path()),
        as_of=day,
    )
    results = stages.strategy_stage(
        scanners=(RegisteredStrategy(config=config, plugin=scanner),),
        universe=universe,
        factor_results=factor_results,
        as_of=day,
    )

    typer.echo(f"strategy {config.id} {config.version} ({as_of})")
    for result in _ranked(results):
        score = "no score" if result.score is None else f"score {result.score:.2f}"
        rank = (
            "-" if result.rank_percentile is None else f"{result.rank_percentile:.3f}"
        )
        verdict = "eligible" if result.eligible else "not eligible"
        typer.echo(f"  {result.symbol} {score} rank_percentile {rank} ({verdict})")

    typer.echo(f"universe: {len(universe.included)} symbols considered", err=True)
    typer.echo(
        f"quality: {outcome.quality_report.accepted}/"
        f"{outcome.quality_report.checked} bars accepted",
        err=True,
    )


def _strategy_config(strategy_id: str) -> StrategyConfig:
    """Load one scanner's configuration, refusing an id nobody configured."""
    for path in strategy_paths(_strategy_dir()):
        config = load_strategy_config(path)
        if config.id == strategy_id:
            return config
    configured = sorted(
        load_strategy_config(path).id for path in strategy_paths(_strategy_dir())
    )
    raise StrategyNotImplementedError(
        f"strategy {strategy_id!r} has no configuration under "
        f"{_strategy_dir()}; configured scanners are {configured}"
    )


def _ranked(results: tuple[StrategyResult, ...]) -> tuple[StrategyResult, ...]:
    """Order a scanner's results from best to worst, unscored ones last."""
    return tuple(
        sorted(results, key=lambda item: (item.score is None, -(item.score or 0.0)))
    )


@app.command()
def stock(symbol: str, as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Show everything the stored snapshots say about one symbol.

    This is the Stock Profile in the terminal (`spec §12.4`): what the Universe
    decided, which factors were measured, how each scanner scored it, what the
    candidate says, and what the watchlist records. Nothing is recomputed —
    every line comes from the snapshots a scan already wrote.
    """
    day = _as_of(as_of)
    universes = _snapshot_records(SnapshotKind.UNIVERSE, day, UniverseSnapshot)
    if not universes:
        typer.echo(
            f"no UNIVERSE snapshot for {as_of}; run the formal pipeline "
            f"`astock daily --as-of {as_of} --allow-incomplete` first",
            err=True,
        )
        raise typer.Exit(code=1)

    universe = universes[0]
    typer.echo(f"{symbol} ({as_of})")
    if symbol in universe.included:
        typer.echo(f"  universe: included (snapshot {universe.snapshot_id})")
    else:
        rules = [
            exclusion.rule.value
            for exclusion in universe.exclusions
            if exclusion.symbol == symbol
        ]
        named = ", ".join(rules) if rules else "no recorded rule"
        typer.echo(f"  universe: excluded by {named}")

    factors = [
        item
        for item in _snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
        if item.symbol == symbol
    ]
    typer.echo("  factors:" if factors else "  factors: none stored for this symbol")
    for factor in factors:
        value = _value_text(factor.raw_value, factor.status)
        typer.echo(f"    {factor.factor} {factor.factor_version}: {value}")

    strategies = [
        item
        for item in _snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)
        if item.symbol == symbol
    ]
    typer.echo(
        "  strategies:" if strategies else "  strategies: none scored this symbol"
    )
    for result in strategies:
        score = "no score" if result.score is None else f"score {result.score:.2f}"
        rank = (
            "-"
            if result.rank_percentile is None
            else f"rank_percentile {result.rank_percentile:.3f}"
        )
        typer.echo(
            f"    {result.strategy_id} {result.strategy_version}: "
            f"{score} {rank} eligible={result.eligible}"
        )
        for reason in result.reasons:
            typer.echo(f"      {reason}")

    candidates = [
        item
        for item in _snapshot_records(SnapshotKind.CANDIDATE, day, Candidate)
        if item.symbol == symbol
    ]
    if candidates:
        candidate = candidates[0]
        typer.echo(f"  candidate: {candidate.next_action}")
        lineage = candidate.lineage
    elif strategies:
        # 有策略结果却没有候选，说明当天的 Candidate 阶段没有产出，而不是
        # "这只股票没被任何 Scanner 看中"——后者是一句没人验证过的猜测。
        typer.echo(
            "  candidate: none stored for this date "
            "(no approved qualification policy, so BUILD_CANDIDATES is blocked)"
        )
        lineage = strategies[0].lineage
    else:
        lineage = universe.lineage
    typer.echo(
        f"  lineage: universe={lineage.universe_snapshot} "
        f"factor={lineage.factor_version} strategy={lineage.strategy_version}"
    )

    entry = _watchlist_store().read(symbol)
    if entry is not None:
        _echo_entry(entry)


@app.command()
def watch(
    symbol: Annotated[
        str | None, typer.Argument(help="Symbol to track; omit to list the watchlist.")
    ] = None,
    thesis: Annotated[str | None, typer.Option("--thesis")] = None,
    key_question: Annotated[list[str] | None, typer.Option("--key-question")] = None,
    risk_condition: Annotated[
        list[str] | None, typer.Option("--risk-condition")
    ] = None,
    waiting_for: Annotated[list[str] | None, typer.Option("--waiting-for")] = None,
    state: Annotated[
        str | None, typer.Option("--state", help="Move the entry to this state.")
    ] = None,
    note: Annotated[str | None, typer.Option("--note")] = None,
) -> None:
    """Track a symbol, or list what is already tracked.

    A new entry starts at `DISCOVERED`. `--state` moves it along the path the
    design confirms — `DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL` — and
    refuses anything else, including the states V1 must not reach.
    """
    store = _watchlist_store()
    if symbol is None:
        symbols = store.symbols()
        if not symbols:
            typer.echo("watchlist: empty")
            return
        for tracked in symbols:
            entry = store.read(tracked)
            if entry is not None:
                typer.echo(
                    f"{entry.symbol} {entry.state} updated {entry.updated_at.isoformat()}"
                )
        return

    now = datetime.now(UTC)
    entry = store.read(symbol)
    if entry is None:
        entry = open_entry(
            symbol,
            at=now,
            thesis=thesis,
            key_questions=key_question or (),
            risk_conditions=risk_condition or (),
            waiting_for=waiting_for or (),
        )
    else:
        entry = _edited(entry, now, thesis, key_question, risk_condition, waiting_for)

    if state is not None:
        try:
            entry = transition(entry, _watchlist_state(state), at=now, note=note)
        except WatchlistTransitionError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from error

    store.write(entry)
    typer.echo(f"{entry.symbol} {entry.state}")
    _echo_entry(entry)


def _watchlist_state(value: str) -> WatchlistState:
    """Parse a state name, naming the vocabulary when it does not match."""
    try:
        return WatchlistState(value.upper())
    except ValueError as error:
        known = ", ".join(item.value for item in WatchlistState)
        raise typer.BadParameter(
            f"{value!r} is not a watchlist state; known states are {known}"
        ) from error


def _edited(
    entry: WatchlistEntry,
    now: datetime,
    thesis: str | None,
    key_question: list[str] | None,
    risk_condition: list[str] | None,
    waiting_for: list[str] | None,
) -> WatchlistEntry:
    """Apply the fields the caller actually supplied, and nothing else."""
    updates: dict[str, object] = {}
    if thesis is not None:
        updates["thesis"] = thesis
    if key_question:
        updates["key_questions"] = tuple(key_question)
    if risk_condition:
        updates["risk_conditions"] = tuple(risk_condition)
    if waiting_for:
        updates["waiting_for"] = tuple(waiting_for)
    if not updates:
        return entry
    return entry.model_copy(update=updates | {"updated_at": now})


def _echo_entry(entry: WatchlistEntry) -> None:
    """Print one watchlist entry with the reasoning that put it there."""
    typer.echo(f"  watchlist: {entry.state} (since {entry.updated_at.isoformat()})")
    if entry.thesis is not None:
        typer.echo(f"    thesis: {entry.thesis}")
    for question in entry.key_questions:
        typer.echo(f"    key question: {question}")
    for risk in entry.risk_conditions:
        typer.echo(f"    risk: {risk}")
    for waiting in entry.waiting_for:
        typer.echo(f"    waiting for: {waiting}")
    for event in entry.timeline:
        origin = event.from_state.value if event.from_state else "new"
        detail = f" ({event.note})" if event.note else ""
        typer.echo(
            f"    timeline: {event.at.isoformat()} {origin} -> {event.to_state}{detail}"
        )


@app.command()
def daily(
    as_of: Annotated[str, AS_OF_OPTION],
    land: Annotated[
        bool, typer.Option("--sync", help="Land raw data from the bulk provider first.")
    ] = False,
    allow_incomplete: Annotated[
        bool,
        typer.Option(
            "--allow-incomplete",
            help="Exit 0 even though some stages are blocked.",
        ),
    ] = False,
) -> None:
    """Run the daily pipeline stage by stage and report every verdict.

    Six of the design's eleven stages can run today. The rest are reported as
    `BLOCKED` with the decision they wait for, so an incomplete pipeline is
    visible rather than implied by a short summary.
    """
    day = _as_of(as_of)
    result = _run_daily(day, land=land)

    for run in result.runs:
        counts = ""
        if run.rows_in is not None or run.rows_out is not None:
            counts = f" rows {run.rows_in} -> {run.rows_out}"
        typer.echo(f"{run.job_type} {run.status}{counts}")
        if run.error is not None:
            typer.echo(f"  {run.error}")
        if run.note is not None:
            typer.echo(f"  note: {run.note}")

    typer.echo(f"candidates: {len(result.candidates)}")
    if result.missing_snapshot_kinds:
        missing = ", ".join(kind.value for kind in result.missing_snapshot_kinds)
        typer.echo(f"missing snapshots: {missing}")
    typer.echo(f"job manifest: {_job_store().path_for(day)}")

    if not result.is_complete:
        typer.echo(
            "daily pipeline incomplete: "
            f"{len(result.blocked_stages)} blocked, "
            f"{len(result.failed_stages)} failed",
            err=True,
        )
        if not allow_incomplete:
            raise typer.Exit(code=1)


def _run_daily(day: datetime, *, land: bool) -> DailyRunResult:
    """Run the daily pipeline with the configured paths."""
    scanners = load_scanners(_strategy_dir())
    return run_daily(
        csv_root=_csv_root(),
        as_of=day,
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=_factor_configs(),
        scanners=scanners,
        strategy_directory=_strategy_dir(),
        store=_store(),
        job_store=_job_store(),
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
        sync=_sync_stage(day) if land else None,
    )


def _sync_stage(day: datetime) -> Callable[[], StageOutcome]:
    """Land raw data, and report the landing as a stage outcome."""

    def stage() -> StageOutcome:
        result = _land(day)
        return StageOutcome(
            rows_in=len(result.landings),
            rows_out=sum(landing.rows_written for landing in result.landings),
            note=", ".join(
                f"{landing.dataset} {landing.status.value}"
                for landing in result.landings
            ),
        )

    return stage


def _land(day: datetime) -> SyncResult:
    """Land raw data from the bulk provider, failing loudly when unusable."""
    provider = _bulk_provider()
    health = provider.health()
    if not health.healthy:
        raise RuntimeError(
            f"provider {health.provider} is not usable: {health.message}"
        )
    return land_raw(provider=provider, root=_csv_root(), as_of=day)


industry_app = typer.Typer(
    no_args_is_help=True,
    help="Industry membership commands.",
)
app.add_typer(industry_app, name="industry")


@app.command("sync-industry")
def sync_industry(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Land the canonical industry catalog and its memberships.

    Catalog first, then one call per board: what lands is a per-fetch-day file
    whose every row says which board it came from and when it was asked for.
    The catalog is the authority — this never invents a board list.
    """
    day = _as_of(as_of)
    landing = land_industry_memberships(
        source=WestockSectorSource(), root=_csv_root(), as_of=day
    )
    typer.echo(f"industry {landing.status.value}: {landing.rows_written} memberships")
    typer.echo(f"written to {landing.path}")
    if landing.note is not None:
        typer.echo(f"note: {landing.note}", err=True)


@industry_app.command("export-map")
def industry_export_map(
    as_of: Annotated[str, AS_OF_OPTION],
    output: Annotated[
        Path, typer.Option("--output", help="写出的 symbol,industry CSV 路径。")
    ],
) -> None:
    """Write the `symbol,industry` CSV the calibration command consumes.

    Only the named output file is written: Snapshot / Watchlist / Job state is
    untouched, so exporting a map can never change what the system believes.
    """
    day = _as_of(as_of)
    path = _csv_root() / INDUSTRY_ROOT / f"{day.date().isoformat()}.csv"
    memberships = read_industry_memberships(path)
    if not memberships:
        typer.echo(
            f"no landed industry memberships at {path}; run `astock sync-industry` "
            "first",
            err=True,
        )
        raise typer.Exit(code=1)

    mapping = build_industry_map(memberships, as_of=day)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("symbol", "industry"))
        for symbol in sorted(mapping):
            writer.writerow((symbol, mapping[symbol]))
    typer.echo(f"industry map: {len(mapping)} symbols written to {output}")


@app.command("sync-research")
def sync_research(
    as_of: Annotated[str, AS_OF_OPTION],
    financials: Annotated[
        bool,
        typer.Option(
            "--financials",
            help="只为研究股票池刷新 WeStock 三大表。",
        ),
    ] = False,
    batch_size: Annotated[
        int,
        typer.Option(
            "--chunk-size",
            help="一次批量请求最多覆盖多少只标的；技术默认 100，不是产品阈值。",
        ),
    ] = 100,
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            help=(
                "并发取数的上限（in-flight）；默认 1（串行），"
                "并发需所有者批准后显式传入。"
            ),
        ),
    ] = 1,
) -> None:
    """Enrich the Research Universe only, with resumable chunking.

    The expensive layer — strategy-length price history, and optionally the
    financial statements — is fetched for the research population and nobody
    else. Valuation stays blocked: this command will not issue ~2,500
    single-symbol neodata calls, and reports the block instead.
    """
    day = _as_of(as_of)
    provider = _bulk_provider()
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    factor_configs = _factor_configs()
    state = compute_research_universe(
        csv_root=_csv_root(),
        as_of=day,
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=factor_configs,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )
    required_bars = strategy_history_requirement(factor_configs)

    typer.echo(f"listing: {len(state.excluded) + len(state.research_symbols)} counted")
    typer.echo(f"listing prefilter: {len(state.listing_prefilter_symbols)} symbols")
    typer.echo(f"research universe: {len(state.research_symbols)} symbols")
    typer.echo(f"price history required: {required_bars} bars per symbol")

    result = bootstrap_strategy_history(
        # Task 3 的只读探测结论是 `NO_BATCH_PRIMARY_AVAILABLE`：
        # 没有经过证据背书的批量行情来源，就不接线、不发明。
        batch_source=None,
        fallback_source=_symbol_bar_provider(provider),
        root=_csv_root(),
        as_of=day,
        symbols=state.research_symbols,
        required_price_bars=required_bars,
        end_date=day.date(),
        batch_size=batch_size,
        max_inflight=workers,
    )
    typer.echo(f"price history satisfied: {len(result.satisfied_symbols)}")
    typer.echo(f"price history short: {len(result.short_symbols)}")
    typer.echo(f"could not be fetched: {len(result.failed_symbols)}")

    if financials:
        statements = land_financial_statements(
            provider=_financial_provider(),
            root=_csv_root(),
            as_of=day,
            symbols=state.research_symbols,
            datasets=tuple(sorted(FINANCIAL_DATASETS)),
        )
        for landing in statements.landings:
            typer.echo(
                f"{landing.dataset} {landing.status.value}: "
                f"{landing.rows_written} rows written"
            )

    typer.echo("valuation enrichment: BLOCKED_PENDING_INDUSTRY_PATH")

    if result.failed_symbols:
        raise typer.Exit(code=1)


@app.command("sync-bootstrap")
def sync_bootstrap(
    as_of: Annotated[str, AS_OF_OPTION],
    batch_size: Annotated[
        int,
        typer.Option(
            "--chunk-size",
            help=(
                "一次批量请求最多覆盖多少只标的。技术默认 50，可按源站限速调整；"
                "它不是产品阈值，不写入 configs/。"
            ),
        ),
    ] = 50,
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            help=(
                "并发取数的上限（in-flight）。默认 1（串行）——设计文档把限速与并发策略列为 "
                "Deferred，因此并发必须由资源所有者显式批准后传入，不是默认行为。"
            ),
        ),
    ] = 1,
) -> None:
    """Land the least price history a cold start needs, resumably.

    The listing lands first, the listing-only prefilter decides which symbols
    deserve history, and only those symbols are fetched. How much history is
    enough comes from the configured liquidity factor's window and is measured
    in valid bars, never in calendar days.

    Every completed chunk is persisted before the next one starts, so an
    interrupted run resumes at the missing coverage instead of from zero. A
    symbol the source could not answer for is reported; no row is invented.
    """
    day = _as_of(as_of)
    provider = _bulk_provider()
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    root = _csv_root()
    dataset = _securities_dataset()
    landing = land_securities_listing(
        provider=provider, root=root, as_of=day, dataset=dataset
    )
    typer.echo(
        f"securities {landing.status.value}: {landing.rows_total} rows "
        f"in {landing.path}"
    )
    if landing.status not in DONE_STATUSES:
        typer.echo(
            "the listing did not land, so a prefilter would be judging an "
            f"incomplete market: {landing.note or landing.status.value}",
            err=True,
        )
        raise typer.Exit(code=1)

    raw = LocalCsvProvider(root).fetch(
        FetchRequest(dataset=dataset, as_of=day, symbols=None)
    )
    profiles = CsvSecurityNormalizer().normalize(raw, as_of=day).securities
    universe_config = load_universe_config(_universe_config_path())
    prefiltered = prefilter_listing(profiles, config=universe_config, as_of=day)
    requirement = liquidity_bootstrap_requirement(_factor_configs())

    typer.echo(f"listing: {len(profiles)} symbols")
    typer.echo(f"prefilter: {len(prefiltered.included)} symbols pass listing rules")
    typer.echo(
        f"bootstrap: {requirement.required_valid_bars} valid bars of "
        f"{requirement.factor_name} per symbol, window read from configs/factors"
    )

    result = bootstrap_liquidity_history(
        # 同上：批量来源没有证据背书，接线为 None，补缺逐标的进行。
        batch_source=None,
        fallback_source=_symbol_bar_provider(provider),
        root=root,
        as_of=day,
        symbols=prefiltered.included,
        requirement=requirement,
        end_date=day.date(),
        batch_size=batch_size,
        max_inflight=workers,
    )

    _, bar_rows = read_raw_rows(root / f"{_dataset()}.csv")
    typer.echo(f"satisfied: {len(result.satisfied_symbols)}")
    typer.echo(f"short of history: {len(result.short_symbols)}")
    typer.echo(f"could not be fetched: {len(result.failed_symbols)}")
    typer.echo(f"bars landed: {len(bar_rows)} rows")

    if result.failed_symbols:
        raise typer.Exit(code=1)


@app.command()
def sync(
    as_of: Annotated[
        str | None,
        typer.Option(
            "--as-of", help="Trade date, YYYY-MM-DD; defaults to today's close."
        ),
    ] = None,
    symbol: Annotated[
        list[str] | None,
        typer.Option("--symbol", help="Limit the sync to these symbols."),
    ] = None,
    financials: Annotated[
        bool,
        typer.Option(
            "--financials",
            help="Also land the three financial statements from the WeStock CLI.",
        ),
    ] = False,
    statements_only: Annotated[
        bool,
        typer.Option(
            "--statements-only",
            help=(
                "Land only the financial statements, using the listing already "
                "on disk. This is the quarterly whole-market refresh: it skips "
                "the per-symbol daily-bar fetch entirely."
            ),
        ),
    ] = False,
    valuation: Annotated[
        bool,
        typer.Option(
            "--valuation",
            help=(
                "同时取 neodata 估值（PE/PB/PS/历史分位/PEG…）。"
                "需要 --symbol：估值批量覆盖极低（实测 10 只只回 1–2 只），"
                "且 neodata 不做标的枚举。"
            ),
        ),
    ] = False,
) -> None:
    """Land raw data for one date, skipping what is already there.

    Symbols already carrying the target date are not fetched again, which is
    the incremental rule `spec §15` requires. Without `--symbol`, the listing
    decides which symbols to fetch, so the scan covers the market it claims to.
    """
    day = _as_of(as_of) if as_of is not None else _today_close()
    # 调用方错误先报，再去做昂贵的事：脚本化的入口更该 fail fast，
    # 而不是先抓几十秒行情、再告诉使用者参数不对。
    if valuation and not symbol:
        typer.echo(
            "取估值需要 --symbol：neodata 不做标的枚举，且估值批量覆盖极低"
            "（实测 10 只只回 1–2 只）",
            err=True,
        )
        raise typer.Exit(code=1)

    provider = _bulk_provider()
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    landings: list[DatasetLanding] = []
    failed: list[str] = []
    if not statements_only:
        result = land_raw(
            provider=provider,
            root=_csv_root(),
            as_of=day,
            symbols=tuple(symbol) if symbol else None,
        )
        landings.extend(result.landings)
        failed.extend(result.failed_datasets)

    if financials or statements_only:
        financial_result = _land_financials(day, symbols=symbol)
        landings.extend(financial_result.landings)
        failed.extend(financial_result.failed_datasets)

    if valuation:
        landings.append(_land_valuation(day, symbols=symbol))

    for landing in landings:
        typer.echo(
            f"{landing.dataset} {landing.status}: {landing.rows_written} rows "
            f"written, {landing.rows_total} in {landing.path}"
        )
        if landing.symbols_skipped:
            typer.echo(
                f"  skipped {len(landing.symbols_skipped)} symbols already "
                "landed for this date"
            )
        if landing.symbols_missing:
            typer.echo(
                f"  {len(landing.symbols_missing)} symbols were requested but "
                "the source returned nothing for them"
            )
        if landing.note is not None:
            typer.echo(f"  {landing.note}")

    if failed:
        typer.echo(f"sync incomplete: {', '.join(failed)}", err=True)
        raise typer.Exit(code=1)


def _land_financials(day: datetime, *, symbols: list[str] | None) -> SyncResult:
    """Land the three statements for the symbols the listing carries."""
    wanted = tuple(symbols) if symbols else read_symbols(_csv_root() / "securities.csv")
    if not wanted:
        typer.echo(
            "no symbols to fetch statements for: land the securities listing "
            "first, or pass --symbol",
            err=True,
        )
        raise typer.Exit(code=1)

    provider = _financial_provider()
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    return land_financial_statements(
        provider=provider,
        root=_csv_root(),
        as_of=day,
        symbols=wanted,
        datasets=tuple(sorted(FINANCIAL_DATASETS)),
    )


def _land_valuation(day: datetime, *, symbols: list[str] | None) -> DatasetLanding:
    """取并落一天的估值数据。

    必须显式给名单：neodata 不做标的枚举，而它的估值批量覆盖极低
    （实测 10 只一批只回 1–2 只），拿整份名单逐只跑是几小时级的事情。
    与其猜一个名单，不如要求调用方明确说要哪几只。
    """
    if not symbols:
        typer.echo(
            "取估值需要 --symbol：neodata 不做标的枚举，且估值批量覆盖极低"
            "（实测 10 只只回 1–2 只）",
            err=True,
        )
        raise typer.Exit(code=1)

    provider = _neodata_provider()
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    return land_neodata_blocks(
        provider=provider,
        root=_csv_root(),
        dataset="valuation",
        values=tuple(symbols),
        as_of=day,
    )


@app.command()
def research(
    symbol: Annotated[
        str | None, typer.Argument(help="Symbol to research, or a job id below.")
    ] = None,
    status: Annotated[
        str | None, typer.Option("--status", help="Poll this job instead.")
    ] = None,
    result: Annotated[
        str | None, typer.Option("--result", help="Read this job's summary instead.")
    ] = None,
    thesis: Annotated[
        str | None, typer.Option("--thesis", help="Override the watchlist thesis.")
    ] = None,
) -> None:
    """Hand a research request to the deep research adapter.

    The request is built from the watchlist entry's own reasoning, so the
    other system receives the questions this one was tracking. No adapter is
    configured by default: without `ASTOCK_DEEP_RESEARCH_CMD` there is nothing
    to submit to, and nothing is invented in its place.
    """
    try:
        adapter = resolve_adapter()
    except DeepResearchNotConfigured as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    try:
        _research_action(
            adapter, symbol=symbol, status=status, result=result, thesis=thesis
        )
    except (DeepResearchInvocationError, ValidationError) as error:
        typer.echo(f"deep research adapter failed: {error}", err=True)
        raise typer.Exit(code=1) from error


def _research_action(
    adapter: CliDeepResearchAdapter,
    *,
    symbol: str | None,
    status: str | None,
    result: str | None,
    thesis: str | None,
) -> None:
    """Poll a job, read a summary, or submit a new request."""
    if status is not None:
        observed = adapter.status(status)
        typer.echo(
            f"{observed.job_id} {observed.state} "
            f"(terminal: {observed.is_terminal}) observed "
            f"{observed.observed_at.isoformat()}"
        )
        if observed.message is not None:
            typer.echo(f"  {observed.message}")
        return

    if result is not None:
        summary = adapter.result(result)
        typer.echo(
            f"{summary.job_id} {summary.symbol} completed "
            f"{summary.completed_at.isoformat()}"
        )
        typer.echo(f"  summary: {summary.summary}")
        typer.echo(f"  artifact: {summary.artifact_reference}")
        return

    if symbol is None:
        typer.echo(
            "research needs a symbol to submit, or --status/--result with a job id",
            err=True,
        )
        raise typer.Exit(code=1)

    entry = _watchlist_store().read(symbol)
    job = adapter.submit(
        ResearchRequest(
            symbol=symbol,
            as_of=datetime.now(UTC),
            thesis=thesis if thesis is not None else (entry.thesis if entry else None),
            key_questions=entry.key_questions if entry else (),
            risk_conditions=entry.risk_conditions if entry else (),
            waiting_for=entry.waiting_for if entry else (),
        )
    )
    typer.echo(
        f"{job.job_id} submitted for {job.symbol} at {job.submitted_at.isoformat()}"
    )


def _load_industry_map(path: Path) -> dict[str, str]:
    """Load and validate the symbol-to-industry CSV mapping."""
    if not path.is_file():
        typer.echo(f"industry map file not found: {path}", err=True)
        raise typer.Exit(code=1)

    mapping: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                typer.echo(f"industry map CSV is empty: {path}", err=True)
                raise typer.Exit(code=1)
            fields = [field.strip() for field in reader.fieldnames if field]
            if "symbol" not in fields or "industry" not in fields:
                typer.echo(
                    f"industry map CSV must have 'symbol' and 'industry' columns: {path}",
                    err=True,
                )
                raise typer.Exit(code=1)
            for row_idx, row in enumerate(reader, start=2):
                sym = (row.get("symbol") or "").strip()
                ind = (row.get("industry") or "").strip()
                if not sym or not ind:
                    typer.echo(
                        f"industry map row {row_idx} is missing symbol or industry",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                if sym in mapping:
                    typer.echo(
                        f"duplicate symbol in industry map at row {row_idx}: {sym}",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                mapping[sym] = ind
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"failed to read industry map {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not mapping:
        typer.echo(f"industry map CSV has no data rows: {path}", err=True)
        raise typer.Exit(code=1)

    return mapping


@calibrate_app.command("candidates")
def calibrate_candidates(
    as_of: Annotated[
        str,
        typer.Option(
            "--as-of",
            help="Trade date, YYYY-MM-DD.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Directory where calibration reports will be written.",
        ),
    ],
    industry_map: Annotated[
        Path | None,
        typer.Option(
            "--industry-map",
            help=(
                "显式指定 symbol,industry 的 CSV；不给就自动加载 canonical 行业映射"
                "（astock sync-industry 落地的结果）。给出时报告按“外部映射证据”呈现。"
            ),
        ),
    ] = None,
) -> None:
    """Generate cross-sectional candidate calibration report without mutating state."""
    day = _as_of(as_of)
    factor_configs = _factor_configs()
    universe_config = load_universe_config(_universe_config_path())
    scanners = load_scanners(_strategy_dir())
    population_state, analysis = run_research_analysis(
        csv_root=_csv_root(),
        as_of=day,
        universe_config=universe_config,
        factor_configs=factor_configs,
        scanners=scanners,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )

    if industry_map is not None:
        mapping = _load_industry_map(industry_map)
        requires_full_coverage = False
    else:
        canonical = read_industry_memberships(
            _csv_root() / INDUSTRY_ROOT / f"{day.date().isoformat()}.csv"
        )
        if not canonical:
            typer.echo(
                "no canonical industry mapping for this date: run "
                "`astock sync-industry --as-of "
                f"{day.date().isoformat()}` or pass --industry-map for "
                "externally mapped evidence",
                err=True,
            )
            raise typer.Exit(code=1)
        mapping = build_industry_map(canonical, as_of=day)
        requires_full_coverage = True

    report = generate_calibration_report(
        strategy_results=analysis.strategy_results,
        factor_results=analysis.factor_results,
        industry_map=mapping,
        as_of=analysis.as_of,
        population=CalibrationPopulation(
            broad_listing_count=len(analysis.outcome.securities),
            prefilter_count=len(population_state.listing_prefilter_symbols),
            research_count=len(population_state.research_symbols),
            research_ratio=round(
                len(population_state.research_symbols)
                / len(analysis.outcome.securities),
                4,
            )
            if analysis.outcome.securities
            else 0.0,
            universe_config_digest=universe_config.digest()[:12],
            min_average_turnover_20d=universe_config.min_average_turnover_20d,
            min_listing_days=universe_config.min_listing_days,
            factor_versions=tuple(
                (config.name, config.version) for config in factor_configs
            ),
            strategy_versions=tuple(
                (scanner.config.id, scanner.config.version) for scanner in scanners
            ),
        ),
        require_full_industry_coverage=requires_full_coverage,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = analysis.as_of.strftime("%Y-%m-%d")
    json_path = output_dir / f"{date_str}-candidate-calibration.json"
    md_path = output_dir / f"{date_str}-candidate-calibration.md"

    json_path.write_text(render_json(report), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    typer.echo("Calibration report written:")
    typer.echo(f"  {json_path}")
    typer.echo(f"  {md_path}")
