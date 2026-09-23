"""Typer command line application.

The CLI is a first-class surface: it must stay usable from cron and from coding
agents without the Web UI. It never prints a reassuring summary for a run that
did nothing — a failure exits non-zero with the reason.
"""

import csv
import hashlib
import json
import platform
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from astock_lens.calendar.china import get_calendar
from astock_lens.calibration.candidate_report import (
    IndustryEvidence,
    generate_calibration_report,
)
from astock_lens.calibration.dividend_coverage import (
    audit_dividend_coverage,
    render_dividend_coverage_json,
    render_dividend_coverage_markdown,
)
from astock_lens.calibration.factor_distribution import CalibrationPopulation
from astock_lens.calibration.market_signal_readiness import (
    build_market_signal_readiness,
    compute_strategy_qualifications,
    render_readiness_json,
    render_readiness_markdown,
)
from astock_lens.calibration.qualification_impact import (
    build_qualification_impact,
    render_impact_json,
    render_impact_markdown,
)
from astock_lens.calibration.render import render_json, render_markdown
from astock_lens.calibration.valuation_coverage import valuation_coverage
from astock_lens.candidates.policy import RepresentativeCandidatePolicy
from astock_lens.cli import discovery_commands, lifecycle_commands
from astock_lens.cli.runtime import (
    AS_OF_OPTION,
    CLOSE_HOUR,
    MINIMUM_PYTHON,
    SHANGHAI,
    STRATEGY_CONFIG_PATH,
    _as_of,
    _benchmark_bars_path,
    _bulk_provider,
    _configured_config_path,
    _csv_root,
    _dataset,
    _factor_configs,
    _factor_state,
    _financial_provider,
    _job_store,
    _neodata_provider,
    _preview_state,
    _securities_dataset,
    _snapshot_records,
    _store,
    _strategy_dir,
    _symbol_bar_provider,
    _universe_config_path,
    _universe_state,
)
from astock_lens.data.benchmark import (
    read_benchmark_bars,
)
from astock_lens.data.bootstrap import (
    bootstrap_liquidity_history,
    bootstrap_strategy_history,
    liquidity_bootstrap_requirement,
    strategy_history_requirement,
)
from astock_lens.data.bootstrap_progress import BootstrapProgress, render_progress
from astock_lens.data.contracts import FetchRequest
from astock_lens.data.dividends.models import DividendEvent
from astock_lens.data.dividends.normalize import normalize_dividend_events
from astock_lens.data.health import raw_datasets
from astock_lens.data.industry import (
    WestockSectorSource,
    build_industry_map,
    load_supplemental_industry_memberships,
)
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.providers.neodata import NeodataProvider
from astock_lens.data.providers.westock import FINANCIAL_DATASETS, WestockCliProvider
from astock_lens.data.storage.paths import resolve_storage_paths
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
    read_universe_symbols,
)
from astock_lens.domain.enums import SnapshotKind
from astock_lens.factors.contracts import FactorResult
from astock_lens.jobs.models import StageOutcome
from astock_lens.pipelines import stages
from astock_lens.pipelines.analysis import (
    compute_research_universe,
    run_research_analysis,
)
from astock_lens.pipelines.daily import DailyRunResult, run_daily
from astock_lens.qualifications import (
    QualificationRuleNotConfigured,
    load_canonical_qualifiers,
)
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
from astock_lens.universe.prefilter import prefilter_listing

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


class _HeartbeatSink:
    """把进度快照打成一行。

    冷启动命令自己输出进度（设计文档 §3.6）：外部 watcher 只是第二块屏幕上的便利工具，
    不再是判断"还在动"的唯一途径。这一行里的每个数字都来自本次 invocation。

    必须**逐行 flush**：stdout 被重定向到日志文件时是按块缓冲的（8 KB），不 flush 的话
    一行心跳要等几十行之后才落盘——2026-09-18 真实 100 只门禁里实测：日志里 0 行心跳，
    而缓冲区里正躺着刚打印的进度，"进度可见"在 cron/重定向场景下等于没实现。
    """

    def emit(self, progress: BootstrapProgress) -> None:
        typer.echo(render_progress(progress))
        sys.stdout.flush()


def _benchmark_subset(symbols: Sequence[str], *, limit: int) -> tuple[str, ...]:
    """基准/运维专用：从预筛结果里确定性地取 `limit` 只标的。

    **不是产品规则**，因此不进 `configs/`，也不改变 Universe 语义：预筛仍然在全市场列表上
    跑，这里只决定"这次真正去取历史的是哪几只"，用于在跑全市场之前先用小样本验证真实链路。
    抽样等距跨越整份列表，避免"只取代码最小的 100 只"把交易所与板块偏差带进基准；同样的输入
    永远得到同样的子集。
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    ordered = tuple(dict.fromkeys(symbols))
    if limit >= len(ordered):
        return ordered
    stride = len(ordered) // limit
    return tuple(ordered[::stride][:limit])


def _today_close() -> datetime:
    """The A-share close on the current date in Shanghai."""
    today = datetime.now(SHANGHAI).date()
    return datetime(today.year, today.month, today.day, CLOSE_HOUR, tzinfo=SHANGHAI)


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
        paths = resolve_storage_paths(config_path=config_path)
    except (OSError, ValueError, ValidationError) as error:
        typer.echo(f"config {config_path} [failed]", err=True)
        typer.echo(f"  {error}", err=True)
        failures.append(f"configuration could not be loaded from {config_path}")
    else:
        typer.echo(f"config {config_path} [ok]")
        typer.echo(f"app.name: {config.app.name}")
        # Missing paths are reported, not created: bootstrap must not write.
        # 来源（env / config / default）与路径一起打印：一个"生效了但没人知道
        # 它从哪来"的路径，等于没有生效。
        for label, path in (
            ("storage.database", paths.database),
            ("storage.normalized_root", paths.normalized_root),
            ("storage.snapshot_root", paths.snapshot_root),
            ("storage.watchlist_root", paths.watchlist_root),
            ("storage.job_root", paths.job_root),
        ):
            presence = "present" if path.exists() else "absent"
            origin = paths.sources[label.removeprefix("storage.")]
            typer.echo(f"{label}: {path} [{presence}] ({origin})")

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
discovery_commands.register(app)
lifecycle_commands.register_watch(app)


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
    factor_configs = _factor_configs()
    factor_names = frozenset(config.name for config in factor_configs)
    try:
        qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    except QualificationRuleNotConfigured:
        qualifiers = None
    candidate_policy = (
        RepresentativeCandidatePolicy(version="v1") if qualifiers else None
    )
    benchmark_path = _benchmark_bars_path()
    benchmark_bars = read_benchmark_bars(
        path=benchmark_path,
        benchmark_id="000985.CSI",
        as_of=day,
    )
    industry_by_symbol = _production_industry_map(day)
    return run_daily(
        csv_root=_csv_root(),
        as_of=day,
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=factor_configs,
        scanners=scanners,
        strategy_directory=_strategy_dir(),
        store=_store(),
        job_store=_job_store(),
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
        sync=_sync_stage(day) if land else None,
        qualifiers=qualifiers,
        candidate_policy=candidate_policy,
        benchmark_id="000985.CSI",
        benchmark_bars=benchmark_bars,
        industry_by_symbol=industry_by_symbol,
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

calendar_app = typer.Typer(
    no_args_is_help=True,
    help="Trading calendar commands.",
)
app.add_typer(calendar_app, name="calendar")


@calendar_app.command("is-open")
def calendar_is_open(
    date: Annotated[
        str,
        typer.Option(
            "--date",
            help="Target date to inspect, formatted as YYYY-MM-DD.",
        ),
    ],
) -> None:
    """Check if a date is an active A-Share trading day."""
    day = _as_of(date)
    cal = get_calendar()
    is_open = cal.is_trade_date(day.date())
    if is_open:
        typer.echo(f"{day.date().isoformat()} is OPEN (trading day)")
    else:
        typer.echo(
            f"{day.date().isoformat()} is CLOSED (non-trading day / weekend / holiday)"
        )


@calendar_app.command("latest")
def calendar_latest(
    date: Annotated[
        str,
        typer.Option(
            "--date",
            help="Reference date, formatted as YYYY-MM-DD.",
        ),
    ],
) -> None:
    """Find the latest effective trade date on or before the target date."""
    day = _as_of(date)
    cal = get_calendar()
    latest = cal.get_latest_trade_date(day.date())
    typer.echo(f"latest trade date: {latest.isoformat()}")


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

    supplements = load_supplemental_industry_memberships(as_of=day)
    mapping = build_industry_map((*memberships, *supplements), as_of=day)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("symbol", "industry"))
        for symbol in sorted(mapping):
            writer.writerow((symbol, mapping[symbol]))
    typer.echo(f"industry map: {len(mapping)} symbols written to {output}")


def _latest_industry_file(day: datetime, root: Path | None = None) -> Path:
    """按时点查找不晚于该日期的最新申万行业 CSV 文件。"""
    directory = (root or _csv_root()) / "westock" / "industry"
    target_date = day.date()
    eligible: list[tuple[date, Path]] = []
    if directory.is_dir():
        for file in directory.glob("*.csv"):
            try:
                file_date = date.fromisoformat(file.stem)
            except ValueError:
                continue
            if file_date <= target_date:
                eligible.append((file_date, file))
    if not eligible:
        raise FileNotFoundError(
            f"No eligible industry file found in {directory} for date {day.date().isoformat()}"
        )
    eligible.sort(key=lambda item: item[0])
    return eligible[-1][1]


def _production_industry_map(day: datetime, root: Path | None = None) -> dict[str, str]:
    """按时点加载生产申万二级行业映射（含权威静态补充）。"""
    from astock_lens.data.industry import load_production_industry_map

    return load_production_industry_map(day, root or _csv_root())


def _valuation_strategy_configs() -> tuple[StrategyConfig, ...]:
    """读策略目录里的全部策略配置；覆盖报告按 `required_factors` 判定，不认策略名。"""
    return tuple(
        load_strategy_config(path) for path in sorted(_strategy_dir().glob("*.yaml"))
    )


def _covered_valuation_symbols(day: datetime) -> frozenset[str]:
    """当前落地的估值里，真正带值的标的（缺值是缺值，不是 0）。"""
    inputs = stages.valuation_inputs(_csv_root(), as_of=day)
    return frozenset(
        item.symbol for item in inputs.observations if item.value is not None
    )


@app.command("valuation-coverage")
def valuation_coverage_command(
    as_of: Annotated[str, AS_OF_OPTION],
    universe: Annotated[
        Path,
        typer.Option(
            "--universe",
            help="研究池名单：JSON 的 research_symbols，或 CSV 的 symbol 列。",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="把完整报告写成 JSON；不写则只打印摘要。"),
    ] = None,
) -> None:
    """核对估值字段与策略估值侧因子在研究池上的覆盖（只读）。

    分母是 `--universe` 给出的研究池名单。缺名单直接报错：拿"已落地的标的"
    当分母会把覆盖率算成 100%，那正是这份报告要防的错觉。
    """
    day = _as_of(as_of)
    try:
        symbols = read_universe_symbols(universe)
    except (OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    inputs = stages.valuation_inputs(_csv_root(), as_of=day)
    try:
        report = valuation_coverage(
            inputs.observations,
            as_of=day,
            universe=symbols,
            strategy_configs=_valuation_strategy_configs(),
            factor_configs=_factor_configs(),
        )
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"as_of: {day.isoformat()}")
    typer.echo(
        f"source: {inputs.source_file if inputs.source_file else '未落地任何估值数据'}"
    )
    typer.echo(f"研究池: {report.universe_size} 只")
    typer.echo(
        f"有任意估值: {len(report.covered_symbols)} / {report.universe_size}"
        f"（缺口 {len(report.uncovered_symbols)} 只）"
    )
    for metric in report.metrics:
        typer.echo(
            f"  字段 {metric.metric}: {len(metric.symbols_with_value)} 只"
            f"（{metric.ratio:.4f}）"
        )
    for factor in report.factors:
        typer.echo(
            f"  因子 {factor.factor}: {len(factor.symbols_with_value)} 只"
            f"（{factor.ratio:.4f}）"
        )
    for strategy in report.strategies:
        if not strategy.valuation_factors:
            continue
        blocking = "、".join(
            f"{name} 缺 {count}" for name, count in strategy.blocking_factors
        )
        typer.echo(
            f"  策略 {strategy.strategy_id}: 估值侧可打分 {len(strategy.scoreable_symbols)}"
            f" / {report.universe_size}；缺口按因子：{blocking}"
        )

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report.to_payload(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"report: {output}")


@app.command("sync-valuation")
def sync_valuation(
    as_of: Annotated[str, AS_OF_OPTION],
    universe: Annotated[
        Path,
        typer.Option(
            "--universe",
            help="研究池名单：JSON 的 research_symbols，或 CSV 的 symbol 列。",
        ),
    ],
    max_rounds: Annotated[
        int,
        typer.Option(
            "--max-rounds",
            help="最多补抓几轮；每轮只请求仍然缺的标的。技术上限，不是产品阈值。",
        ),
    ] = 2,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            help=(
                "一次请求最多带几只标的。实测源的响应被截到 1–2 个内容块，"
                "因此带多带少不改变每次回几块；默认 5（实测每次命中最高）。"
            ),
        ),
    ] = 5,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="只处理名单前 N 只，用于小规模探针。"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="把本轮清单写成 JSON（含剩余缺口）。"),
    ] = None,
) -> None:
    """按缺口批量补抓估值：多轮、可重跑、缺口显式。

    实测源端一批只回 1–2 只，因此补齐必须分多轮。三条纪律写在这里：

    - 每轮只请求"仍缺"的标的，已覆盖的不会重复问；
    - 落地按块身份合并，后一轮不会冲掉前一轮（见 `land_neodata_blocks`）；
    - 一轮没有带来任何新标的就停下，并把剩余缺口原样报出——缺口不是成功。
    """
    day = _as_of(as_of)
    if max_rounds <= 0:
        raise typer.BadParameter("--max-rounds 必须为正")
    if batch_size <= 0:
        raise typer.BadParameter("--batch-size 必须为正")
    if limit is not None and limit <= 0:
        raise typer.BadParameter("--limit 必须为正")

    try:
        wanted = read_universe_symbols(universe)
    except (OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    if limit is not None:
        wanted = wanted[:limit]

    provider = _neodata_provider(batch_size=batch_size)
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    typer.echo(f"研究池: {len(wanted)} 只（as_of {day.date().isoformat()}）")
    rounds: list[dict[str, object]] = []
    stopped = "max_rounds"
    for index in range(1, max_rounds + 1):
        covered = _covered_valuation_symbols(day)
        missing = tuple(symbol for symbol in wanted if symbol not in covered)
        if not missing:
            stopped = "covered"
            typer.echo(f"round {index}: 已全覆盖，无需请求")
            break

        landing = land_neodata_blocks(
            provider=provider,
            root=_csv_root(),
            dataset="valuation",
            values=missing,
            as_of=day,
        )
        after = _covered_valuation_symbols(day)
        landed = tuple(symbol for symbol in missing if symbol in after)
        still_missing = tuple(symbol for symbol in wanted if symbol not in after)
        rounds.append(
            {
                "round": index,
                "requested": len(missing),
                "landed": len(landed),
                "missing": len(still_missing),
                "status": landing.status.value,
                "note": landing.note,
            }
        )
        typer.echo(
            f"round {index}: 请求 {len(missing)} 只，落地 {len(landed)} 只，"
            f"仍缺 {len(still_missing)} 只（{landing.status.value}）"
        )
        if landing.note:
            typer.echo(f"  note: {landing.note}", err=True)
        if not landed:
            stopped = "no_progress"
            typer.echo("本轮没有带来任何新标的，停止继续请求", err=True)
            break
    else:
        stopped = "max_rounds"

    covered = _covered_valuation_symbols(day)
    missing_symbols = tuple(symbol for symbol in wanted if symbol not in covered)
    typer.echo(
        f"覆盖: {len(wanted) - len(missing_symbols)} / {len(wanted)}；"
        f"缺口 {len(missing_symbols)} 只；停止原因 {stopped}"
    )

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "dataset": "valuation",
                    "as_of": day.isoformat(),
                    "requested_symbols": list(wanted),
                    "covered_symbols": [
                        symbol
                        for symbol in wanted
                        if symbol not in set(missing_symbols)
                    ],
                    "missing_symbols": list(missing_symbols),
                    "stop_reason": stopped,
                    "rounds": rounds,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        typer.echo(f"report: {output}")

    if missing_symbols:
        raise typer.Exit(code=1)


def _covered_dividend_symbols(
    day: datetime, root: Path | None = None
) -> frozenset[str]:
    """当前落地的分红事件数据里，真正出现的标的代码。"""
    csv_root = root if root is not None else _csv_root()
    path = csv_root / "neodata" / "dividend_history" / f"{day.date().isoformat()}.csv"
    if not path.is_file():
        return frozenset()
    _, rows = read_raw_rows(path)
    symbols: set[str] = set()
    for row in rows:
        if len(row) >= 3:
            content = row[2]
            for m in re.finditer(r"([0-9]{6}\.[A-Z]{2})", content):
                symbols.add(m.group(1))
    return frozenset(symbols)


@app.command("sync-dividends")
def sync_dividends(
    as_of: Annotated[str, AS_OF_OPTION],
    universe: Annotated[
        Path,
        typer.Option(
            "--universe",
            help="研究池名单：JSON 的 research_symbols，或 CSV 的 symbol 列。",
        ),
    ],
    max_rounds: Annotated[
        int,
        typer.Option(
            "--max-rounds",
            help="最多补抓几轮；每轮只请求仍然缺的标的。技术上限，不是产品阈值。",
        ),
    ] = 2,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            help="一次请求最多带几只标的；默认 5。",
        ),
    ] = 5,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="只处理名单前 N 只，用于小规模探针。"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="把本轮清单写成 JSON（含剩余缺口）。"),
    ] = None,
) -> None:
    """按缺口批量补抓分红派息事件历史：多轮、可重跑、缺口显式。

    落盘目标严格为 data/raw/neodata/dividend_history/YYYY-MM-DD.csv。
    落地按块身份合并，后一轮不会冲掉前一轮。
    一轮没有带来任何新标的就停下，并把剩余缺口原样报出。
    """
    day = _as_of(as_of)
    if max_rounds <= 0:
        raise typer.BadParameter("--max-rounds 必须为正")
    if batch_size <= 0:
        raise typer.BadParameter("--batch-size 必须为正")
    if limit is not None and limit <= 0:
        raise typer.BadParameter("--limit 必须为正")

    try:
        wanted = read_universe_symbols(universe)
    except (OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    if limit is not None:
        wanted = wanted[:limit]

    provider = _neodata_provider(batch_size=batch_size)
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    typer.echo(f"分红同步研究池: {len(wanted)} 只（as_of {day.date().isoformat()}）")
    rounds: list[dict[str, object]] = []
    stopped = "max_rounds"
    for index in range(1, max_rounds + 1):
        covered = _covered_dividend_symbols(day)
        missing = tuple(symbol for symbol in wanted if symbol not in covered)
        if not missing:
            stopped = "covered"
            typer.echo(f"round {index}: 已全覆盖，无需请求")
            break

        landing = land_neodata_blocks(
            provider=provider,
            root=_csv_root(),
            dataset="dividend_history",
            values=missing,
            as_of=day,
        )
        after = _covered_dividend_symbols(day)
        landed = tuple(symbol for symbol in missing if symbol in after)
        still_missing = tuple(symbol for symbol in wanted if symbol not in after)
        rounds.append(
            {
                "round": index,
                "requested": len(missing),
                "landed": len(landed),
                "missing": len(still_missing),
                "status": landing.status.value,
                "note": landing.note,
            }
        )
        typer.echo(
            f"round {index}: 请求 {len(missing)} 只，落地 {len(landed)} 只，"
            f"仍缺 {len(still_missing)} 只（{landing.status.value}）"
        )
        if landing.note:
            typer.echo(f"  note: {landing.note}", err=True)
        if not landed:
            stopped = "no_progress"
            typer.echo("本轮没有带来任何新标的，停止继续请求", err=True)
            break
    else:
        stopped = "max_rounds"

    covered = _covered_dividend_symbols(day)
    missing_symbols = tuple(symbol for symbol in wanted if symbol not in covered)
    typer.echo(
        f"分红覆盖: {len(wanted) - len(missing_symbols)} / {len(wanted)}；"
        f"缺口 {len(missing_symbols)} 只；停止原因 {stopped}"
    )
    if missing_symbols:
        typer.echo(f"剩余缺口: {', '.join(missing_symbols[:20])}")
        if len(missing_symbols) > 20:
            typer.echo(f"  … 及其余 {len(missing_symbols) - 20} 只")

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "dataset": "dividend_history",
                    "as_of": day.isoformat(),
                    "requested_symbols": list(wanted),
                    "covered_symbols": [
                        symbol
                        for symbol in wanted
                        if symbol not in set(missing_symbols)
                    ],
                    "missing_symbols": list(missing_symbols),
                    "stop_reason": stopped,
                    "rounds": rounds,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        typer.echo(f"report: {output}")

    if missing_symbols:
        raise typer.Exit(code=1)


def _load_dividend_events(
    day: datetime, root: Path | None = None
) -> tuple[DividendEvent, ...]:
    """读取已落地的分红历史原始数据并归一化为分红事件列表。"""
    csv_root = root if root is not None else _csv_root()
    path = csv_root / "neodata" / "dividend_history" / f"{day.date().isoformat()}.csv"
    if not path.is_file():
        return ()
    _, rows = read_raw_rows(path)
    events: list[DividendEvent] = []
    for row in rows:
        if len(row) >= 3:
            events.extend(normalize_dividend_events(row[2], default_as_of=day))
    return tuple(events)


@app.command("dividend-coverage")
def dividend_coverage_command(
    as_of: Annotated[str, AS_OF_OPTION],
    universe: Annotated[
        Path,
        typer.Option(
            "--universe",
            help="研究池名单：JSON 的 research_symbols，或 CSV 的 symbol 列。",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", help="把报告写入文件（.json 为 JSON，其它为 Markdown）。"
        ),
    ] = None,
) -> None:
    """核对分红事件在研究池上的覆盖情况（只读）。

    分母是 `--universe` 给出的研究池名单。缺名单直接报错：拿'已有分红事件的标的'
    当分母会把覆盖率算成 100%，那是假全覆盖。
    """
    day = _as_of(as_of)
    try:
        symbols = read_universe_symbols(universe)
    except (OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    events = _load_dividend_events(day)
    try:
        report = audit_dividend_coverage(events, symbols, day)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"as_of: {day.isoformat()}")
    typer.echo(f"研究池: {report.universe_size} 只")
    typer.echo(
        f"有任意分红事件: {report.symbols_with_any_event} / {report.universe_size}"
        f"（缺口 {len(report.missing_symbols)} 只）"
    )
    typer.echo(
        f"有已实施现金分红: {report.symbols_with_implemented_cash_event} / {report.universe_size}"
    )
    typer.echo(
        f"具备除权除息日: {report.symbols_with_ex_date} / {report.universe_size}"
    )
    typer.echo(
        f"具备股权登记日: {report.symbols_with_registration_date} / {report.universe_size}"
    )
    typer.echo(
        f"事件分布: 有效总计 {report.event_count} 条，"
        f"实施 {report.implemented_count} 条，预案 {report.proposal_count} 条"
    )

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix.lower() == ".json":
            content = render_dividend_coverage_json(report)
        else:
            content = render_dividend_coverage_markdown(report)
        output.write_text(content, encoding="utf-8")
        typer.echo(f"report: {output}")


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
    cal = get_calendar()
    if not cal.is_trade_date(day.date()):
        typer.echo(
            f"{day.date().isoformat()} is a non-trading day (weekend/holiday). Skipping market data sync."
        )
        if not financials:
            return

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
        progress=_HeartbeatSink(),
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
    limit_symbols: Annotated[
        int | None,
        typer.Option(
            "--limit-symbols",
            help=(
                "基准/运维专用：只对确定性抽样后的前 N 只标的取历史。默认不限制；"
                "它不改变产品 Universe 语义，也不是产品阈值。"
            ),
        ),
    ] = None,
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

    population = prefiltered.included
    if limit_symbols is not None:
        population = _benchmark_subset(population, limit=limit_symbols)
        typer.echo(
            f"benchmark subset: {len(population)} of {len(prefiltered.included)} "
            "prefiltered symbols (operator-only; product Universe unchanged)"
        )

    result = bootstrap_liquidity_history(
        # 同上：批量来源没有证据背书，接线为 None，补缺逐标的进行。
        batch_source=None,
        fallback_source=_symbol_bar_provider(provider),
        root=root,
        as_of=day,
        symbols=population,
        requirement=requirement,
        end_date=day.date(),
        batch_size=batch_size,
        max_inflight=workers,
        progress=_HeartbeatSink(),
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


def _file_sha256(path: Path) -> str:
    """一份映射文件的摘要：让报告里的"用的是哪份文件"可以被复算。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _declared_mapping_as_of(value: str | None) -> datetime | None:
    """把命令行声明的映射日期解析成带时区的时间；没给就是 `None`。

    裸时间不是事实：没有时区的 ISO 串被拒绝，而不是被悄悄补上本机时区。缺省
    留 `None` 也不许拿文件 mtime 顶替——mtime 是文件系统的噪声，不是映射的时点。
    """
    if value is None:
        return None
    try:
        declared = datetime.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(
            f"--industry-map-as-of must be an ISO-8601 datetime, got {value!r}"
        ) from error
    if declared.tzinfo is None or declared.tzinfo.utcoffset(declared) is None:
        raise typer.BadParameter(
            "--industry-map-as-of needs a timezone offset (e.g. "
            f"2026-09-17T15:00:00+08:00); a bare time is not a fact, got {value!r}"
        )
    return declared


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


lifecycle_commands.register_research(app)


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
    industry_map_as_of: Annotated[
        str | None,
        typer.Option(
            "--industry-map-as-of",
            help=(
                "外部映射自己的时点（带时区 ISO 时间，如 2026-09-17T15:00:00+08:00）。"
                "只描述 --industry-map；不给就记为未知，绝不用文件 mtime 顶替。"
            ),
        ),
    ] = None,
) -> None:
    """Generate cross-sectional candidate calibration report without mutating state."""
    if industry_map_as_of is not None and industry_map is None:
        raise typer.BadParameter(
            "--industry-map-as-of describes a --industry-map file; pass "
            "--industry-map too, or drop the date (the canonical mapping dates "
            "itself from the membership records it was built from)"
        )
    declared_as_of = _declared_mapping_as_of(industry_map_as_of)

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

    # 本阶段所有校准报告都是诊断材料；来源与日期必须如实标注，不许含混。
    evidence = IndustryEvidence(origin="unspecified", diagnostic_only=True)
    if industry_map is not None:
        mapping = _load_industry_map(industry_map)
        requires_full_coverage = False
        evidence = IndustryEvidence(
            origin="external",
            source_ref=str(industry_map),
            source_sha256=_file_sha256(industry_map),
            mapping_as_of=declared_as_of,
            diagnostic_only=True,
        )
    else:
        canonical_path = _csv_root() / INDUSTRY_ROOT / f"{day.date().isoformat()}.csv"
        canonical = read_industry_memberships(canonical_path)
        if not canonical:
            typer.echo(
                "no canonical industry mapping for this date: run "
                "`astock sync-industry --as-of "
                f"{day.date().isoformat()}` or pass --industry-map for "
                "externally mapped evidence",
                err=True,
            )
            raise typer.Exit(code=1)
        supplements = load_supplemental_industry_memberships(as_of=day)
        all_canonical = (*canonical, *supplements)
        mapping = build_industry_map(all_canonical, as_of=day)
        requires_full_coverage = True
        # 日期取**可见**成员自己声明的取数时点：晚于分析时点的记录已经被
        # `build_industry_map` 过滤掉，所以这里不可能把一个未来日期当成历史口径。
        visible_dates = [
            membership.as_of for membership in all_canonical if membership.as_of <= day
        ]
        evidence = IndustryEvidence(
            origin="canonical",
            source_ref=str(canonical_path),
            source_sha256=_file_sha256(canonical_path),
            mapping_as_of=max(visible_dates, default=None),
            diagnostic_only=True,
        )

    report = generate_calibration_report(
        strategy_results=analysis.strategy_results,
        factor_results=analysis.factor_results,
        industry_map=mapping,
        as_of=analysis.as_of,
        industry_evidence=evidence,
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


@calibrate_app.command("qualification-impact")
def calibrate_qualification_impact(
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
            help="Directory where the qualification impact audit will be written.",
        ),
    ],
) -> None:
    """Audit the six production qualification rules against stored snapshots.

    This command is strictly read-only:

    - reads the stored FACTOR and STRATEGY snapshots;
    - loads the strict canonical qualifiers;
    - never calls a provider, never recomputes factors/strategies, and never
      writes a Snapshot / Watchlist / Job / Candidate record.

    It writes only ``qualification-impact-YYYY-MM-DD.json`` and
    ``qualification-impact-YYYY-MM-DD.md`` under ``--output-dir``. A missing
    snapshot fails loudly instead of producing an empty report.
    """
    day = _as_of(as_of)
    factor_results = _snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
    strategy_results = _snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)

    if not factor_results:
        typer.echo(
            f"no FACTOR snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)
    if not strategy_results:
        typer.echo(
            f"no STRATEGY snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)

    factor_names = frozenset(config.name for config in _factor_configs())
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    report = build_qualification_impact(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers=qualifiers,
        as_of=day,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = day.strftime("%Y-%m-%d")
    json_path = output_dir / f"qualification-impact-{date_str}.json"
    md_path = output_dir / f"qualification-impact-{date_str}.md"

    json_path.write_text(render_impact_json(report), encoding="utf-8")
    md_path.write_text(render_impact_markdown(report), encoding="utf-8")

    typer.echo("Qualification impact audit written:")
    typer.echo(f"  {json_path}")
    typer.echo(f"  {md_path}")


from astock_lens.cli.trade import trade_app

app.add_typer(trade_app, name="trade")


@calibrate_app.command("market-signal-readiness")
def calibrate_market_signal_readiness(
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
            help="Directory where the market signal readiness report will be written.",
        ),
    ],
) -> None:
    """Audit market regime and signal readiness against stored snapshots.

    Strictly read-only:
    - reads stored FACTOR and STRATEGY snapshots;
    - evaluates dual qualification using canonical approved qualifiers;
    - calculates technical metric distributions for qualified stocks;
    - writes market-signal-readiness-YYYY-MM-DD.json and .md under output_dir.
    """
    day = _as_of(as_of)
    factor_results = _snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
    strategy_results = _snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)

    if not factor_results:
        typer.echo(
            f"no FACTOR snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)
    if not strategy_results:
        typer.echo(
            f"no STRATEGY snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)

    factor_names = frozenset(config.name for config in _factor_configs())
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    qualifications = compute_strategy_qualifications(
        strategy_results=strategy_results,
        factor_results=factor_results,
        qualifiers=qualifiers,
    )

    report = build_market_signal_readiness(
        as_of=day,
        qualifications=qualifications,
        factor_results=factor_results,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = day.strftime("%Y-%m-%d")
    json_path = output_dir / f"market-signal-readiness-{date_str}.json"
    md_path = output_dir / f"market-signal-readiness-{date_str}.md"

    json_path.write_text(render_readiness_json(report), encoding="utf-8")
    md_path.write_text(render_readiness_markdown(report), encoding="utf-8")

    typer.echo("Market & signal readiness report written:")
    typer.echo(f"  {json_path}")
    typer.echo(f"  {md_path}")


@calibrate_app.command("candidate-v2-impact")
def calibrate_candidate_v2_impact_cmd(
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
            help="Directory where the candidate v2 impact audit report will be written.",
        ),
    ],
) -> None:
    """Audit Candidate v2 5D market evidence and signal impact on qualified candidates.

    Strictly read-only:
    - reads stored FACTOR and STRATEGY snapshots;
    - reads normalized bars and industry landing files if present;
    - audits 5D evidence availability and signal breakdown distributions;
    - writes candidate-v2-impact-YYYY-MM-DD.json and .md under output_dir.
    """
    from astock_lens.calibration.candidate_v2_impact import (
        compute_candidate_v2_impact,
        render_candidate_v2_impact_markdown,
    )

    day = _as_of(as_of)
    factor_results = _snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
    strategy_results = _snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)

    if not factor_results:
        typer.echo(
            f"no FACTOR snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)
    if not strategy_results:
        typer.echo(
            f"no STRATEGY snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)

    factor_names = frozenset(config.name for config in _factor_configs())
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    qualifications = compute_strategy_qualifications(
        strategy_results=strategy_results,
        factor_results=factor_results,
        qualifiers=qualifiers,
    )

    outcome = stages.normalize_stage(
        csv_root=_csv_root(),
        as_of=day,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )
    bars = outcome.bars.daily_bars

    industry_file = _csv_root() / "industry" / f"{day.date().isoformat()}.csv"
    mapped_symbols: set[str] = set()
    if industry_file.is_file():
        from astock_lens.data.sync import read_industry_memberships

        try:
            memberships = read_industry_memberships(industry_file)
            mapped_symbols = {m.symbol for m in memberships}
        except (OSError, ValueError):
            mapped_symbols = set()

    benchmark_available = False

    report = compute_candidate_v2_impact(
        qualifications=qualifications,
        factors=factor_results,
        bars=bars,
        industry_mapped_symbols=mapped_symbols,
        benchmark_available=benchmark_available,
        as_of=day,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = day.strftime("%Y-%m-%d")
    json_path = output_dir / f"candidate-v2-impact-{date_str}.json"
    md_path = output_dir / f"candidate-v2-impact-{date_str}.md"

    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(
        render_candidate_v2_impact_markdown(report),
        encoding="utf-8",
    )

    typer.echo("Candidate v2 impact audit report written:")
    typer.echo(f"  {json_path}")
    typer.echo(f"  {md_path}")
