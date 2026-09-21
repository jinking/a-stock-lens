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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from astock_lens.candidates.context import primary_qualified_strategy
from astock_lens.candidates.models import Candidate
from astock_lens.candidates.policy import (
    CANDIDATE_POLICY_DEFERRED,
    CandidatePolicy,
)
from astock_lens.data.repository.contracts import NormalizedRepository
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.domain.enums import (
    JobStage,
    MarketValidation,
    Signal,
    SnapshotKind,
)
from astock_lens.domain.models import DailyBar, DomainRecord
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorResult
from astock_lens.jobs.models import JobRun, JobStatus, StageOutcome
from astock_lens.jobs.store import JobStore
from astock_lens.market.regime import (
    MarketRegimeEvidenceIncomplete,
    MarketRegimeResult,
)
from astock_lens.market.validation import MarketValidationResult
from astock_lens.pipelines import stages
from astock_lens.qualifications.contracts import (
    QualificationRuleNotConfigured,
    StrategyQualifier,
)
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.signals.contracts import SignalResult
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
#
# BUILD_CANDIDATES comes after the market and signal stages, because a
# Candidate is the object those layers have already spoken about. Building it
# earlier publishes a partial result under a name that promises a complete one.
EXECUTION_ORDER: tuple[JobStage, ...] = (
    JobStage.SYNC_DATA,
    JobStage.NORMALIZE,
    JobStage.COMPUTE_FACTORS,
    JobStage.BUILD_UNIVERSE,
    JobStage.RUN_STRATEGIES,
    JobStage.DETECT_REGIME,
    JobStage.MARKET_VALIDATE,
    JobStage.RUN_SIGNALS,
    JobStage.BUILD_CANDIDATES,
    JobStage.UPDATE_WATCHLIST,
    JobStage.GENERATE_DAILY_SNAPSHOT,
)

# Why each blocked stage cannot run. Every reason names a decision the design
# has not made, so nobody can read a blocked stage as a data outage.
BLOCKED_REASONS: dict[JobStage, str] = {
    JobStage.BUILD_CANDIDATES: (
        "5D market validation evidence (industry excess, relative strength, volume ratio) "
        "and signal candidate publishing semantics have not been completed and approved by owner (spec §5, §6)"
    ),
    JobStage.UPDATE_WATCHLIST: (
        "no confirmed rule changes a watchlist state on its own; V1 transitions "
        "are user-driven and validated by the state machine (spec §13)"
    ),
}

# 缺失的快照不是"今天没数据"：它的生产阶段被上面的 BLOCKED 挡住，而写一份占位
# 快照等于伪造一个没人做过的判定。
MISSING_SNAPSHOT_REASON = (
    "a missing snapshot has no producer: its stage is blocked above, and a "
    "placeholder would be a fabricated verdict"
)

# A stage whose inputs are produced by a stage that has no implementation yet is
# BLOCKED, not FAILED: nothing went wrong in the run, the layer simply does not
# exist. Candidate qualification is defined on top of the market and signal
# verdicts, so with those missing a Candidate can only be a partial result.
_UPSTREAM_DECISIONS: dict[JobStage, tuple[JobStage, ...]] = {
    JobStage.BUILD_CANDIDATES: (
        JobStage.DETECT_REGIME,
        JobStage.MARKET_VALIDATE,
        JobStage.RUN_SIGNALS,
    ),
}


def _missing_upstream(stage: JobStage) -> tuple[JobStage, ...]:
    """The upstream stages this one needs that have no implementation yet."""
    return tuple(
        upstream
        for upstream in _UPSTREAM_DECISIONS.get(stage, ())
        if upstream in BLOCKED_REASONS
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
    candidate_policy: CandidatePolicy | None = None,
    qualifiers: Mapping[str, StrategyQualifier] | None = None,
    repository: NormalizedRepository | None = None,
) -> DailyRunResult:
    """Run every stage of the daily pipeline once for one point in time.

    Configuration is passed in rather than discovered here, so a caller can see
    exactly which thresholds, factor windows and scanner versions a run used.
    The candidate policy is configuration too, and its absence is a decision:
    without one the `BUILD_CANDIDATES` stage is `BLOCKED`, never replaced by a
    default rule.

    `repository` 是归一化读取边界的注入点，与 `run_analysis` 等入口同名同义；
    为 `None` 时 NORMALIZE 阶段走 CSV 回放，与迁移前一致。
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
        candidate_policy=candidate_policy,
        qualifiers=qualifiers,
        repository=repository,
    )
    state = _State()

    runs: list[JobRun] = []
    for stage in EXECUTION_ORDER:
        run = _execute(stage, context=context, state=state)
        runs.append(run)
        job_store.record(run)
        if run.status is JobStatus.BLOCKED:
            state.blocked.append(stage)
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
    candidate_policy: CandidatePolicy | None
    qualifiers: Mapping[str, StrategyQualifier] | None = None
    repository: NormalizedRepository | None = None


def _blocked_reasons(stage: JobStage, context: _Context) -> tuple[str, ...]:
    """这个阶段今天不能跑的**全部**原因，一条都不许省。"""
    reasons: list[str] = []
    base_reason = BLOCKED_REASONS.get(stage)
    if base_reason is not None:
        reasons.append(base_reason)
    missing = _missing_upstream(stage)
    if missing:
        reasons.append(
            "its inputs do not exist yet: "
            f"{', '.join(upstream.value for upstream in missing)} have no "
            "implementation, and a result published without them would read as "
            "a complete one"
        )
    if (
        stage
        in (
            JobStage.MARKET_VALIDATE,
            JobStage.RUN_SIGNALS,
            JobStage.BUILD_CANDIDATES,
        )
        and not context.qualifiers
    ):
        reasons.append(
            "strategy qualification rules are not configured: absolute quality thresholds have not been approved"
        )
    if stage is JobStage.BUILD_CANDIDATES and context.candidate_policy is None:
        reasons.append(CANDIDATE_POLICY_DEFERRED)
    return tuple(reasons)


@dataclass
class _State:
    """What the run has produced so far, for the stages that follow."""

    outcome: stages.NormalizeOutcome | None = None
    universe: UniverseSnapshot | None = None
    factor_results: tuple[FactorResult, ...] = ()
    strategy_results: tuple[StrategyResult, ...] = ()
    regime_result: MarketRegimeResult | None = None
    validation_results: tuple[MarketValidationResult, ...] = ()
    signal_results: tuple[SignalResult, ...] = ()
    market_validation_by_symbol: dict[str, MarketValidation] = field(
        default_factory=dict
    )
    signal_by_symbol: dict[str, Signal] = field(default_factory=dict)
    qualifications: tuple[StrategyQualification, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    snapshot_paths: list[tuple[SnapshotKind, Path]] = field(default_factory=list)
    blocked: list[JobStage] = field(default_factory=list)


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

    blocked = _blocked_reasons(stage, context)
    if blocked:
        return _run(
            stage,
            context,
            status=JobStatus.BLOCKED,
            started_at=started_at,
            error="; ".join(blocked),
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
        repository=context.repository,
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


def _detect_regime(context: _Context, state: _State) -> StageOutcome:
    outcome = _required(state.outcome, stage=JobStage.DETECT_REGIME, name="NORMALIZE")
    breadth_ratio: float | None = None
    daily_bars = outcome.bars.daily_bars
    if daily_bars:
        bars_by_symbol: dict[str, list[DailyBar]] = {}
        for b in daily_bars:
            bars_by_symbol.setdefault(b.symbol, []).append(b)
        above_ma20 = 0
        counted = 0
        for b_list in bars_by_symbol.values():
            if len(b_list) >= 20 and b_list[-1].close is not None:
                closes = [bar.close for bar in b_list[-20:] if bar.close is not None]
                if len(closes) == 20:
                    counted += 1
                    if b_list[-1].close > (sum(closes) / 20.0):
                        above_ma20 += 1
        if counted > 0:
            breadth_ratio = above_ma20 / counted

    if breadth_ratio is None:
        raise MarketRegimeEvidenceIncomplete(
            "Market breadth is unavailable: insufficient daily bars to calculate MA20 breadth"
        )

    regime_res = stages.market_regime_stage(
        as_of=context.as_of,
        breadth_ratio=breadth_ratio,
    )
    state.regime_result = regime_res
    return StageOutcome(
        rows_in=len(daily_bars),
        rows_out=1,
        note=f"Regime: {regime_res.regime.value}",
    )


def _ensure_qualifications(
    context: _Context, state: _State
) -> tuple[StrategyQualification, ...]:
    if state.qualifications:
        return state.qualifications
    if not context.qualifiers:
        raise QualificationRuleNotConfigured(
            "strategy qualification rules are not configured"
        )
    state.qualifications = stages.qualification_stage(
        strategy_results=state.strategy_results,
        factor_results=state.factor_results,
        qualifiers=context.qualifiers,
    )
    return state.qualifications


def _primary_strategy_by_symbol(
    qualifications: Sequence[StrategyQualification],
) -> dict[str, str]:
    by_sym: dict[str, list[StrategyQualification]] = {}
    for q in qualifications:
        if q.qualified:
            by_sym.setdefault(q.symbol, []).append(q)
    return {sym: primary_qualified_strategy(quals) for sym, quals in by_sym.items()}


def _market_validate(context: _Context, state: _State) -> StageOutcome:
    quals = _ensure_qualifications(context, state)
    strat_by_sym = _primary_strategy_by_symbol(quals)
    symbols = sorted(strat_by_sym.keys())
    val_results = stages.market_validation_stage(
        strategy_by_symbol=strat_by_sym,
        factor_results=state.factor_results,
        as_of=context.as_of,
        symbols=symbols,
    )
    state.validation_results = val_results
    state.market_validation_by_symbol = {r.symbol: r.status for r in val_results}
    confirmed_count = sum(
        1 for r in val_results if r.status == MarketValidation.CONFIRMED
    )
    contradicted_count = sum(
        1 for r in val_results if r.status == MarketValidation.CONTRADICTED
    )
    return StageOutcome(
        rows_in=len(symbols),
        rows_out=len(val_results),
        note=f"Confirmed={confirmed_count}, Contradicted={contradicted_count}",
    )


def _run_signals(context: _Context, state: _State) -> StageOutcome:
    quals = _ensure_qualifications(context, state)
    strat_by_sym = _primary_strategy_by_symbol(quals)
    symbols = sorted(strat_by_sym.keys())
    regime = state.regime_result.regime if state.regime_result is not None else None
    sig_results = stages.signal_stage(
        strategy_by_symbol=strat_by_sym,
        factor_results=state.factor_results,
        as_of=context.as_of,
        market_regime=regime,
        symbols=symbols,
    )
    state.signal_results = sig_results
    state.signal_by_symbol = {r.symbol: r.signal for r in sig_results}
    active_count = sum(1 for r in sig_results if r.signal != Signal.NO_SIGNAL)
    return StageOutcome(
        rows_in=len(symbols),
        rows_out=len(sig_results),
        note=f"Signals={len(sig_results)}, Active={active_count}",
    )


def _build_candidates(context: _Context, state: _State) -> StageOutcome:
    universe = _required(
        state.universe, stage=JobStage.BUILD_CANDIDATES, name="BUILD_UNIVERSE"
    )
    quals = _ensure_qualifications(context, state)
    state.candidates = stages.candidate_stage(
        strategy_results=state.strategy_results,
        qualifications=quals,
        market_validation_by_symbol=state.market_validation_by_symbol,
        signal_by_symbol=state.signal_by_symbol,
        lineage=stages.lineage_for(
            universe=universe,
            factor_configs=context.factor_configs,
            scanners=context.scanners,
        ),
        as_of=context.as_of,
        policy=context.candidate_policy,
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
        f"missing: {', '.join(kind.value for kind in missing)}; "
        f"blocked business stages: "
        f"{', '.join(stage.value for stage in state.blocked) or 'none'} "
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
    JobStage.DETECT_REGIME: _detect_regime,
    JobStage.MARKET_VALIDATE: _market_validate,
    JobStage.RUN_SIGNALS: _run_signals,
    JobStage.BUILD_CANDIDATES: _build_candidates,
    JobStage.GENERATE_DAILY_SNAPSHOT: _generate_daily_snapshot,
}
