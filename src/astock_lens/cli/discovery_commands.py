"""Stock Discovery 查询命令。"""

from typing import Annotated

import typer

from astock_lens.candidates.models import Candidate
from astock_lens.discovery import (
    QualifiedScreenQuery,
    StrategyScreenQuery,
    screen_qualified,
    screen_strategy,
)
from astock_lens.discovery.candidates import screen_candidates
from astock_lens.discovery.today import build_today_overview
from astock_lens.domain.enums import MarketRegime, SnapshotKind
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications import (
    QualificationConfigInvalid,
    QualificationRuleNotConfigured,
    load_canonical_qualifiers,
)
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.universe.models import UniverseSnapshot

from . import runtime as rt

LOW_COVERAGE_WARNING_RATIO = 0.90


def stock(symbol: str, as_of: Annotated[str, rt.AS_OF_OPTION]) -> None:
    """Show everything the stored snapshots say about one symbol.

    This is the Stock Profile in the terminal (`spec §12.4`): what the Universe
    decided, which factors were measured, how each scanner scored it, what the
    candidate says, and what the watchlist records. Nothing is recomputed —
    every line comes from the snapshots a scan already wrote.
    """
    day = rt._as_of(as_of)
    universes = rt._snapshot_records(SnapshotKind.UNIVERSE, day, UniverseSnapshot)
    if not universes:
        typer.echo(
            f"no UNIVERSE snapshot for {as_of}; run the formal pipeline `astock daily --as-of {as_of} --allow-incomplete` first",
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
        typer.echo(
            f"  universe: excluded by {', '.join(rules) if rules else 'no recorded rule'}"
        )
    factors = [
        item
        for item in rt._snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
        if item.symbol == symbol
    ]
    typer.echo("  factors:" if factors else "  factors: none stored for this symbol")
    for factor in factors:
        typer.echo(
            f"    {factor.factor} {factor.factor_version}: {rt._value_text(factor.raw_value, factor.status)}"
        )
    strategies = [
        item
        for item in rt._snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)
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
            f"    {result.strategy_id} {result.strategy_version}: {score} {rank} eligible={result.eligible}"
        )
        for reason in result.reasons:
            typer.echo(f"      {reason}")
    store = rt._store()
    published = day.date().isoformat() in store.dates(SnapshotKind.CANDIDATE)
    candidates = [
        item
        for item in rt._snapshot_records(SnapshotKind.CANDIDATE, day, Candidate)
        if item.symbol == symbol
    ]
    if candidates:
        candidate = candidates[0]
        typer.echo(f"  candidate: {candidate.next_action.value} (published)")
        if candidate.primary_strategy_id:
            typer.echo(f"    primary_strategy: {candidate.primary_strategy_id}")
        qualified_ids = [
            q.strategy_id for q in candidate.strategy_qualifications if q.qualified
        ]
        if not qualified_ids:
            qualified_ids = [
                r.strategy_id
                for r in candidate.strategy_results
                if r.rank_percentile is not None and r.rank_percentile >= 0.90
            ]
        if qualified_ids:
            typer.echo(f"    qualified_strategies: {', '.join(qualified_ids)}")
        if candidate.market_validation is not None:
            typer.echo(f"    market_validation: {candidate.market_validation.value}")
        if candidate.signal is not None:
            typer.echo(f"    signal: {candidate.signal.value}")
        for reason in candidate.reasons:
            typer.echo(f"    reason: {reason}")
        for risk in candidate.risks:
            typer.echo(f"    risk: {risk}")
        lineage = candidate.lineage
    elif published:
        typer.echo("  candidate: not selected for this date")
        lineage = strategies[0].lineage if strategies else universe.lineage
    elif strategies:
        typer.echo("  candidate: not published for this date")
        lineage = strategies[0].lineage
    else:
        lineage = universe.lineage
    lineage_parts = [
        f"universe={lineage.universe_snapshot}",
        f"factor={lineage.factor_version}",
        f"strategy={lineage.strategy_version}",
    ]
    if lineage.qualification_version:
        lineage_parts.append(f"qualification={lineage.qualification_version}")
    if lineage.regime_version:
        lineage_parts.append(f"regime={lineage.regime_version}")
    if lineage.market_validation_version:
        lineage_parts.append(f"validation={lineage.market_validation_version}")
    if lineage.signal_version:
        lineage_parts.append(f"signal={lineage.signal_version}")
    typer.echo(f"  lineage: {' '.join(lineage_parts)}")
    entry = rt._watchlist_store().read(symbol)
    if entry is not None:
        from .lifecycle_commands import _echo_entry

        _echo_entry(entry)


def screen(
    strategy: Annotated[str, typer.Argument(help="Strategy id to screen.")],
    as_of: Annotated[str, rt.AS_OF_OPTION],
    top: Annotated[
        int, typer.Option("--top", help="Maximum number of strategy results to show.")
    ] = 20,
    min_percentile: Annotated[
        float | None,
        typer.Option(
            "--min-percentile", help="Minimum percentile threshold [0.0, 1.0]."
        ),
    ] = None,
    all_results: Annotated[
        bool, typer.Option("--all-results", help="Include non-eligible symbols.")
    ] = False,
) -> None:
    """Screen stored strategy evaluation results.

    Only reads SnapshotKind.STRATEGY from the snapshot store.
    No provider access, no factor or scanner recomputation, and no snapshot writing.
    """
    day = rt._as_of(as_of)
    records = rt._snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)
    if not records:
        typer.echo(
            f"no STRATEGY snapshot for {as_of}\nrun `astock daily --as-of {as_of} --allow-incomplete` first",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        screened = screen_strategy(
            records,
            StrategyScreenQuery(
                strategy_id=strategy,
                limit=top,
                eligible_only=not all_results,
                min_percentile=min_percentile,
            ),
        )
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    if screened.coverage.total_count == 0:
        typer.echo(f"strategy '{strategy}' has no stored results for {as_of}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"{strategy} — {as_of}")
    coverage = screened.coverage
    typer.echo(
        f"coverage: total={coverage.total_count} eligible={coverage.eligible_count} scored={coverage.scored_count} ranked={coverage.ranked_count}"
    )
    if (
        coverage.total_count > 0
        and coverage.scored_count / coverage.total_count < LOW_COVERAGE_WARNING_RATIO
    ):
        typer.echo(
            f"coverage warning: only {coverage.scored_count}/{coverage.total_count} stored results have a score; ranking reflects available data"
        )
    typer.echo(f"showing: {len(screened.items)}")
    for item in screened.items:
        score = f"{item.score:.2f}" if item.score is not None else "None"
        percentile = (
            f"{item.rank_percentile:.4f}"
            if item.rank_percentile is not None
            else "None"
        )
        typer.echo(
            f"  {item.rank}  {item.symbol}  score={score}  percentile={percentile}"
        )


def qualified(
    strategy: Annotated[str, typer.Argument(help="Strategy id to qualify.")],
    as_of: Annotated[str, rt.AS_OF_OPTION],
    top: Annotated[
        int, typer.Option("--top", help="Maximum number of strategy results to show.")
    ] = 20,
) -> None:
    """双门槛合格股票查询（严格只读）。

    只读取已存储的 FACTOR / STRATEGY 快照，严格加载已批准的资格配置
    （目录可被 ``ASTOCK_QUALIFICATION_DIR`` 覆盖），把两者交给纯查询服务
    ``screen_qualified`` 做「Top10% + 绝对门槛」双通过判定并展示结果。

    不调用 Provider，不重算因子或策略，不写任何 Snapshot / Watchlist / Job
    记录。资格配置缺失或非法时 fail-closed 报错退出，绝不降级为零合格
    正常屏；零合格时展示服务给出的数据健康 warning。
    """
    day = rt._as_of(as_of)
    factors = rt._snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
    strategies = rt._snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)
    if not factors:
        typer.echo(
            f"no FACTOR snapshot for {as_of}\nrun `astock daily --as-of {as_of} --allow-incomplete` first",
            err=True,
        )
        raise typer.Exit(code=1)
    if not strategies:
        typer.echo(
            f"no STRATEGY snapshot for {as_of}\nrun `astock daily --as-of {as_of} --allow-incomplete` first",
            err=True,
        )
        raise typer.Exit(code=1)
    factor_names = frozenset(config.name for config in rt._factor_configs())
    try:
        qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    except (QualificationRuleNotConfigured, QualificationConfigInvalid) as error:
        typer.echo(f"qualification configuration is invalid: {error}", err=True)
        raise typer.Exit(code=1) from error
    try:
        screened = screen_qualified(
            factor_results=factors,
            strategy_results=strategies,
            qualifiers=qualifiers,
            query=QualifiedScreenQuery(strategy_id=strategy, limit=top),
        )
    except KeyError as error:
        typer.echo(
            f"strategy {strategy!r} has no approved qualification rule; approved strategies are {', '.join(sorted(qualifiers))}",
            err=True,
        )
        raise typer.Exit(code=1) from error
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"{strategy} — {as_of}")
    coverage = screened.coverage
    typer.echo(
        f"coverage: eligible={coverage.strategy_eligible_count} ranked={coverage.ranked_count} percentile_pass={coverage.percentile_pass_count} absolute_pass={coverage.absolute_pass_count} qualified={coverage.qualified_count}"
    )
    typer.echo(f"qualified: {coverage.qualified_count}")
    for warning in screened.warnings:
        typer.echo(f"warning: {warning}")
    typer.echo(f"showing: {len(screened.items)}")
    for item in screened.items:
        score = f"{item.score:.2f}" if item.score is not None else "None"
        typer.echo(
            f"  {item.rank}  {item.symbol}  score={score}  percentile={item.rank_percentile:.4f}"
        )


def candidates(
    as_of: Annotated[str, rt.AS_OF_OPTION],
    top: Annotated[
        int, typer.Option("--top", help="Maximum number of candidates to show.")
    ] = 20,
) -> None:
    """正式候选股票列表查询（严格只读）。

    只读取已存储的 CANDIDATE 快照，按权威顺序展示候选标的。
    不调用 Provider，不重算任何因子/策略/验证/信号，不写任何记录。
    """
    day = rt._as_of(as_of)
    date_str = day.date().isoformat()
    store = rt._store()
    if date_str not in store.dates(SnapshotKind.CANDIDATE):
        typer.echo(
            f"no CANDIDATE snapshot for {as_of}\nrun `astock daily --as-of {as_of} --allow-incomplete` first",
            err=True,
        )
        raise typer.Exit(code=1)
    candidate_records = rt._snapshot_records(SnapshotKind.CANDIDATE, day, Candidate)
    if not candidate_records:
        typer.echo("candidates: 0")
        return
    result = screen_candidates(candidate_records, as_of=day, limit=top)
    typer.echo(f"candidates: {result.total_count} (showing: {len(result.items)})")
    header = f"{'rank':<4} | {'symbol':<9} | {'primary strategy':<16} | {'qualified strategies':<20} | {'market validation':<17} | {'signal':<15} | {'next action':<11}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for item in result.items:
        mv = item.market_validation.value if item.market_validation else "NONE"
        sig = item.signal.value if item.signal else "NO_SIGNAL"
        qual = ",".join(item.qualified_strategy_ids)
        typer.echo(
            f"{item.rank:<4} | {item.symbol:<9} | {item.primary_strategy_id:<16} | {qual:<20} | {mv:<17} | {sig:<15} | {item.next_action.value:<11}"
        )


def today(
    as_of: Annotated[str, rt.AS_OF_OPTION],
    top: Annotated[
        int, typer.Option("--top", help="Number of top candidates to preview.")
    ] = 10,
) -> None:
    """今日盘后候选研究概览（严格只读）。

    聚合展示当天候选股票的整体情况、策略分布、市场验证与信号分布，
    并展示权威候选顺序的前 N 只核心标的。
    """
    day = rt._as_of(as_of)
    date_str = day.date().isoformat()
    store = rt._store()
    if date_str not in store.dates(SnapshotKind.CANDIDATE):
        typer.echo(
            f"no CANDIDATE snapshot for {as_of}\nrun `astock daily --as-of {as_of} --allow-incomplete` first",
            err=True,
        )
        raise typer.Exit(code=1)
    candidate_records = rt._snapshot_records(SnapshotKind.CANDIDATE, day, Candidate)
    if not candidate_records:
        typer.echo(f"as_of: {date_str}\ncandidates: 0")
        return
    regime: MarketRegime | None = None
    records = store.read(SnapshotKind.MARKET_REGIME, day)
    regime_value = (
        records[0].get("regime") if records and isinstance(records[0], dict) else None
    )
    if isinstance(regime_value, str):
        try:
            regime = MarketRegime(regime_value)
        except ValueError:
            pass
    overview = build_today_overview(
        candidate_records, as_of=day, market_regime=regime, top_limit=top
    )
    typer.echo(f"as_of: {date_str}")
    typer.echo(f"candidates: {overview.candidate_count}")
    if overview.market_regime is not None:
        typer.echo(f"market_regime: {overview.market_regime.value}")
    for title, values in (
        ("counts by primary strategy:", overview.counts_by_primary_strategy),
        ("counts by market validation:", overview.counts_by_market_validation),
        ("counts by signal:", overview.counts_by_signal),
    ):
        typer.echo(title)
        for key, count in sorted(values.items()):
            typer.echo(f"  {key}: {count}")
    typer.echo(f"\ntop {len(overview.top_candidates)} candidates:")
    header = f"{'rank':<4} | {'symbol':<9} | {'primary strategy':<16} | {'qualified strategies':<20} | {'market validation':<17} | {'signal':<15} | {'next action':<11}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for item in overview.top_candidates:
        mv = item.market_validation.value if item.market_validation else "NONE"
        sig = item.signal.value if item.signal else "NO_SIGNAL"
        qual = ",".join(item.qualified_strategy_ids)
        typer.echo(
            f"{item.rank:<4} | {item.symbol:<9} | {item.primary_strategy_id:<16} | {qual:<20} | {mv:<17} | {sig:<15} | {item.next_action.value:<11}"
        )


def register(app: typer.Typer) -> None:
    app.command()(stock)
    app.command()(screen)
    app.command()(qualified)
    app.command()(candidates)
    app.command()(today)
