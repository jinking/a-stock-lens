"""因子、Universe、Strategy 与 Daily 管线命令。"""

import json
from collections import Counter
from typing import Annotated

import typer

from astock_lens.data.bootstrap import liquidity_bootstrap_requirement
from astock_lens.pipelines import stages
from astock_lens.pipelines.analysis import compute_research_universe
from astock_lens.strategies.registry import (
    RegisteredStrategy,
    StrategyNotImplementedError,
    build_scanner,
)
from astock_lens.universe.config import load_universe_config

from .runtime import (
    AS_OF_OPTION,
    _as_of,
    _csv_root,
    _dataset,
    _factor_configs,
    _factor_state,
    _job_store,
    _preview_state,
    _ranked,
    _run_daily,
    _securities_dataset,
    _strategy_config,
    _universe_config_path,
    _universe_state,
)


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


def register_early(
    app: typer.Typer,
    factors_app: typer.Typer,
    universe_app: typer.Typer,
    strategy_app: typer.Typer,
) -> None:
    factors_app.command("compute")(factors_compute)
    universe_app.command("research")(universe_research)
    universe_app.command("bootstrap-requirement")(universe_bootstrap_requirement)
    universe_app.command("build")(universe_build)
    app.command()(scan)
    strategy_app.command("run")(strategy_run)


def register_daily(app: typer.Typer) -> None:
    app.command()(daily)
