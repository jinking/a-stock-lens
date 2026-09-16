"""The daily pipeline, stage by stage.

`spec §15` names eleven stages and requires every one of them to be
independently restartable; `ARCHITECTURE.md` §17 requires a job record per run.
This module is where those two requirements meet: each stage is executed in
turn, timed, counted, given a verdict, and written to the job store.

Two kinds of incompleteness are reported rather than smoothed over:

- a stage that **cannot run** is recorded `BLOCKED` with the decision it waits
  for. Four stages are in that state today: no Market Regime, Market
  Validation or Signal detector exists, and the design fixes their
  vocabularies while leaving every threshold deferred; UPDATE_WATCHLIST has no
  confirmed rule that changes a state on its own.
- a stage that **produced nothing** reports its real counts. An empty universe
  stays an empty universe; it does not become a success with a comforting
  number attached.

A failing stage stops the pipeline, because every later stage consumes what it
produced. A scan continued on missing data would be a scan of nothing.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from astock_lens.candidates.models import Candidate
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.domain.enums import JobStage, SnapshotKind
from astock_lens.domain.models import DomainRecord
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorResult
from astock_lens.jobs.models import JobRun, JobStatus, StageOutcome
from astock_lens.jobs.store import JobStore
from astock_lens.pipelines import stages
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.registry import RegisteredStrategy, unimplemented_scanners
from astock_lens.universe.config import UniverseConfig
from astock_lens.universe.models import UniverseSnapshot

SYNC_SKIPPED = (
    "no sync stage was configured: raw data is expected to be landed already. "
    "Pass a sync callable (or run `astock sync`) to land it first"
)

# The design lists BUILD_UNIVERSE before COMPUTE_FACTORS. This implementation
# computes factors first because the Universe's liquidity rule consumes the
# `avg_amount_20d` factor: measuring it twice would give the same quantity two
# definitions. The deviation is deliberate and recorded in REVIEW_NOTES.md.
EXECUTION_ORDER: tuple[JobStage, ...] = (
    JobStage.SYNC_DATA,
    JobStage.NORMALIZE,
    JobStage.COMPUTE_FACTORS,
    JobStage.BUILD_UNIVERSE,
    JobStage.RUN_STRATEGIES,
    JobStage.BUILD_CANDIDATES,
    JobStage.DETECT_REGIME,
    JobStage.MARKET_VALIDATE,
    JobStage.RUN_SIGNALS,
    JobStage.UPDATE_WATCHLIST,
    JobStage.GENERATE_DAILY_SNAPSHOT,
)

# Why each blocked stage cannot run. Every reason names a decision the design
# has not made, so nobody can read a blocked stage as a data outage.
BLOCKED_REASONS: dict[JobStage, str] = {
    JobStage.DETECT_REGIME: (
        "no market regime detector exists: the design fixes the five regime "
        "states but no input thresholds, and AGENTS.md forbids inventing them"
    ),
    JobStage.MARKET_VALIDATE: (
        "no market validation detector exists: the design fixes "
        "CONFIRMED/NEUTRAL/CONTRADICTED but no thresholds for the trend, "
        "relative-strength, volume or liquidity inputs"
    ),
    JobStage.RUN_SIGNALS: (
        "no signal detector exists: the design fixes the signal vocabulary but "
        "no detection thresholds, so a signal could only be invented"
    ),
    JobStage.UPDATE_WATCHLIST: (
        "no confirmed rule changes a watchlist state on its own; V1 transitions "
        "are user-driven and validated by the state machine (spec §13)"
    ),
}

MISSING_SNAPSHOT_REASON = (
    "it has no producer: DETECT_REGIME is blocked, and a regime snapshot "
    "without a detector would be a fabricated verdict"
)


class DailyRunResult(DomainRecord):
    """Everything the daily pipeline did for one date."""

    as_of: datetime
    runs: tuple[JobRun, ...] = ()
    universe: UniverseSnapshot | None = None
    factor_results: tuple[FactorResult, ...] = ()
    strategy_results: tuple[StrategyResult, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    snapshot_paths: tuple[tuple[SnapshotKind, Path], ...] = ()
    missing_snapshot_kinds: tuple[SnapshotKind, ...] = ()

    @property
    def blocked_stages(self) -> tuple[JobStage, ...]:
        """The stages that could not run, in pipeline order."""
        return self._stages_with(JobStatus.BLOCKED)

    @property
    def failed_stages(self) -> tuple[JobStage, ...]:
        """The stages that raised, in pipeline order."""
        return self._stages_with(JobStatus.FAILED)

    @property
    def is_complete(self) -> bool:
        """Whether every stage in the design's pipeline actually ran."""
        return not self.blocked_stages and not self.failed_stages

    def _stages_with(self, status: JobStatus) -> tuple[JobStage, ...]:
        return tuple(run.job_type for run in self.runs if run.status is status)


def run_daily(
    *,
    csv_root: Path,
    as_of: datetime,
    universe_config: UniverseConfig,
    factor_configs: tuple[FactorConfig, ...],
    scanners: tuple[RegisteredStrategy, ...],
    strategy_directory: Path,
    store: SnapshotStore,
    job_store: JobStore,
    dataset: str = stages.DEFAULT_DATASET,
    securities_dataset: str = stages.DEFAULT_SECURITIES_DATASET,
    sync: Callable[[], StageOutcome] | None = None,
) -> DailyRunResult:
    """Run every stage of the daily pipeline once for one point in time.

    Configuration is passed in rather than discovered here, so a caller can see
    exactly which thresholds, factor windows and scanner versions a run used.
    """
    context = _Context(
        csv_root=csv_root,
        as_of=as_of,
        dataset=dataset,
        securities_dataset=securities_dataset,
        universe_config=universe_config,
        factor_configs=factor_configs,
        scanners=scanners,
        strategy_directory=strategy_directory,
        store=store,
        sync=sync,
    )
    state = _State()

    runs: list[JobRun] = []
    for stage in EXECUTION_ORDER:
        run = _execute(stage, context=context, state=state)
        runs.append(run)
        job_store.record(run)
        if run.status is JobStatus.FAILED:
            break

    written = [kind for kind, _ in state.snapshot_paths]
    return DailyRunResult(
        as_of=as_of,
        runs=tuple(runs),
        universe=state.universe,
        factor_results=state.factor_results,
        strategy_results=state.strategy_results,
        candidates=state.candidates,
        snapshot_paths=tuple(state.snapshot_paths),
        missing_snapshot_kinds=tuple(
            kind for kind in SnapshotKind if kind not in written
        ),
    )


@dataclass(frozen=True)
class _Context:
    """Everything a stage may read; nothing a stage may change."""

    csv_root: Path
    as_of: datetime
    dataset: str
    securities_dataset: str
    universe_config: UniverseConfig
    factor_configs: tuple[FactorConfig, ...]
    scanners: tuple[RegisteredStrategy, ...]
    strategy_directory: Path
    store: SnapshotStore
    sync: Callable[[], StageOutcome] | None


@dataclass
class _State:
    """What the run has produced so far, for the stages that follow."""

    outcome: stages.NormalizeOutcome | None = None
    universe: UniverseSnapshot | None = None
    factor_results: tuple[FactorResult, ...] = ()
    strategy_results: tuple[StrategyResult, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    snapshot_paths: list[tuple[SnapshotKind, Path]] = field(default_factory=list)


def _execute(stage: JobStage, *, context: _Context, state: _State) -> JobRun:
    """Run one stage and return its verdict, never raising out of the pipeline."""
    started_at = datetime.now(UTC)

    if stage is JobStage.SYNC_DATA and context.sync is None:
        return _run(
            stage,
            context,
            status=JobStatus.SKIPPED,
            started_at=started_at,
            note=SYNC_SKIPPED,
        )

    reason = BLOCKED_REASONS.get(stage)
    if reason is not None:
        return _run(
            stage,
            context,
            status=JobStatus.BLOCKED,
            started_at=started_at,
            error=reason,
        )

    handler = _HANDLERS[stage]
    try:
        outcome = handler(context, state)
    except Exception as error:  # noqa: BLE001 - recorded, not swallowed
        return _run(
            stage,
            context,
            status=JobStatus.FAILED,
            started_at=started_at,
            error=f"{type(error).__name__}: {error}",
        )

    return _run(
        stage,
        context,
        status=JobStatus.SUCCEEDED,
        started_at=started_at,
        rows_in=outcome.rows_in,
        rows_out=outcome.rows_out,
        note=outcome.note,
    )


def _run(
    stage: JobStage,
    context: _Context,
    *,
    status: JobStatus,
    started_at: datetime,
    rows_in: int | None = None,
    rows_out: int | None = None,
    error: str | None = None,
    note: str | None = None,
) -> JobRun:
    return JobRun(
        job_type=stage,
        as_of=context.as_of,
        status=status,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        rows_in=rows_in,
        rows_out=rows_out,
        error=error,
        note=note,
    )


def _sync(context: _Context, state: _State) -> StageOutcome:
    """Land raw data before anything reads it."""
    del state
    if context.sync is None:  # pragma: no cover - guarded by `_execute`
        raise RuntimeError(SYNC_SKIPPED)
    return context.sync()


def _normalize(context: _Context, state: _State) -> StageOutcome:
    state.outcome = stages.normalize_stage(
        csv_root=context.csv_root,
        as_of=context.as_of,
        dataset=context.dataset,
        securities_dataset=context.securities_dataset,
    )
    return StageOutcome(
        rows_in=state.outcome.raw_bars.row_count,
        rows_out=len(state.outcome.bars.daily_bars),
    )


def _compute_factors(context: _Context, state: _State) -> StageOutcome:
    outcome = _required(state.outcome, stage=JobStage.COMPUTE_FACTORS, name="NORMALIZE")
    state.factor_results = stages.factor_stage(
        outcome=outcome, factor_configs=context.factor_configs, as_of=context.as_of
    )
    _record(state, SnapshotKind.FACTOR, context.store, context.as_of)
    return StageOutcome(
        rows_in=len(stages.symbols_of(outcome.bars)),
        rows_out=len(state.factor_results),
    )


def _build_universe(context: _Context, state: _State) -> StageOutcome:
    outcome = _required(state.outcome, stage=JobStage.BUILD_UNIVERSE, name="NORMALIZE")
    state.universe = stages.universe_stage(
        outcome=outcome,
        factor_results=state.factor_results,
        config=context.universe_config,
        as_of=context.as_of,
    )
    _record(state, SnapshotKind.UNIVERSE, context.store, context.as_of)
    return StageOutcome(
        rows_in=len(outcome.securities), rows_out=len(state.universe.included)
    )


def _run_strategies(context: _Context, state: _State) -> StageOutcome:
    universe = _required(
        state.universe, stage=JobStage.RUN_STRATEGIES, name="BUILD_UNIVERSE"
    )
    state.strategy_results = stages.strategy_stage(
        scanners=context.scanners,
        universe=universe,
        factor_results=state.factor_results,
        as_of=context.as_of,
    )
    _record(state, SnapshotKind.STRATEGY, context.store, context.as_of)

    missing = unimplemented_scanners(context.strategy_directory)
    note = (
        f"{len(missing)} configured scanners have no implementation yet: "
        f"{', '.join(missing)}"
        if missing
        else None
    )
    return StageOutcome(
        rows_in=len(universe.included),
        rows_out=len(state.strategy_results),
        note=note,
    )


def _build_candidates(context: _Context, state: _State) -> StageOutcome:
    universe = _required(
        state.universe, stage=JobStage.BUILD_CANDIDATES, name="BUILD_UNIVERSE"
    )
    state.candidates = stages.candidate_stage(
        strategy_results=state.strategy_results,
        lineage=stages.lineage_for(
            universe=universe,
            factor_configs=context.factor_configs,
            scanners=context.scanners,
        ),
        as_of=context.as_of,
    )
    _record(state, SnapshotKind.CANDIDATE, context.store, context.as_of)
    return StageOutcome(
        rows_in=len(state.strategy_results), rows_out=len(state.candidates)
    )


def _generate_daily_snapshot(context: _Context, state: _State) -> StageOutcome:
    """Report the snapshot set this run wrote, and name what is missing."""
    del context
    written = [kind for kind, path in state.snapshot_paths if path.is_file()]
    missing = [kind for kind in SnapshotKind if kind not in written]
    note = (
        f"snapshots written: {', '.join(kind.value for kind in written)}; "
        f"missing: {', '.join(kind.value for kind in missing)} "
        f"({MISSING_SNAPSHOT_REASON})"
    )
    return StageOutcome(rows_out=len(written), note=note)


def _record(
    state: _State,
    kind: SnapshotKind,
    store: SnapshotStore,
    as_of: datetime,
) -> None:
    """Write one snapshot and remember where it landed."""
    records: tuple[BaseModel, ...]
    if kind is SnapshotKind.UNIVERSE:
        records = (state.universe,) if state.universe is not None else ()
    elif kind is SnapshotKind.FACTOR:
        records = state.factor_results
    elif kind is SnapshotKind.STRATEGY:
        records = state.strategy_results
    else:
        records = state.candidates

    state.snapshot_paths.append((kind, store.write(kind, as_of, records)))


def _required[T](value: T | None, *, stage: JobStage, name: str) -> T:
    """Return a stage's input, or say which stage should have produced it."""
    if value is None:
        raise RuntimeError(f"{stage} ran before {name} produced anything")
    return value


_HANDLERS: dict[JobStage, Callable[[_Context, _State], StageOutcome]] = {
    JobStage.SYNC_DATA: _sync,
    JobStage.NORMALIZE: _normalize,
    JobStage.COMPUTE_FACTORS: _compute_factors,
    JobStage.BUILD_UNIVERSE: _build_universe,
    JobStage.RUN_STRATEGIES: _run_strategies,
    JobStage.BUILD_CANDIDATES: _build_candidates,
    JobStage.GENERATE_DAILY_SNAPSHOT: _generate_daily_snapshot,
}
