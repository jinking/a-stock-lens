"""End-to-end test for the daily pipeline.

`spec §15` names eleven stages and requires every one of them to be a job that
can be restarted on its own. Six of them are implemented today; the rest are
blocked on decisions the design defers (no regime, validation or signal
thresholds exist) — so this test pins the rule that matters: the pipeline
reports what it did, reports what it did not do, and never fills the gap with a
plausible-looking result.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import JobStage, SnapshotKind
from astock_lens.factors.config import load_factor_config
from astock_lens.jobs.models import JobStatus, StageOutcome
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines.daily import DailyRunResult, run_daily
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LONG_DATASET = "daily_bars_long"

# The stages this slice can actually run, in the design's order.
IMPLEMENTED = (
    JobStage.NORMALIZE,
    JobStage.BUILD_UNIVERSE,
    JobStage.COMPUTE_FACTORS,
    JobStage.RUN_STRATEGIES,
    JobStage.BUILD_CANDIDATES,
    JobStage.GENERATE_DAILY_SNAPSHOT,
)

# The stages the design requires and this slice cannot run, because the
# thresholds they need are deferred rather than decided.
BLOCKED = (
    JobStage.DETECT_REGIME,
    JobStage.MARKET_VALIDATE,
    JobStage.RUN_SIGNALS,
    JobStage.UPDATE_WATCHLIST,
)


def _run(
    local_tmp: Path,
    *,
    sync: Callable[[], StageOutcome] | None = None,
    dataset: str = LONG_DATASET,
) -> DailyRunResult:
    return run_daily(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=tuple(
            load_factor_config(path)
            for path in sorted((CONFIGS / "factors").glob("*.yaml"))
        ),
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=JsonSnapshotStore(local_tmp / "snapshots"),
        job_store=JsonJobStore(local_tmp / "jobs"),
        dataset=dataset,
        sync=sync,
    )


def _status(result: DailyRunResult, stage: JobStage) -> JobStatus:
    run = next(run for run in result.runs if run.job_type is stage)
    return run.status


def test_every_named_stage_gets_a_job_run(local_tmp: Path) -> None:
    result = _run(local_tmp)

    assert {run.job_type for run in result.runs} == set(JobStage)
    # The runs are recorded in the order the stages were executed.
    assert [run.job_type for run in result.runs][:5] == [
        JobStage.SYNC_DATA,
        JobStage.NORMALIZE,
        JobStage.COMPUTE_FACTORS,
        JobStage.BUILD_UNIVERSE,
        JobStage.RUN_STRATEGIES,
    ]


def test_the_implemented_stages_succeed_and_count_their_rows(local_tmp: Path) -> None:
    result = _run(local_tmp)

    for stage in IMPLEMENTED:
        assert _status(result, stage) is JobStatus.SUCCEEDED, stage

    by_stage = {run.job_type: run for run in result.runs}
    factors = by_stage[JobStage.COMPUTE_FACTORS]
    # Factors are measured for every symbol with usable bars (11 in the long
    # fixture), because the Universe's liquidity rule consumes one of them;
    # only the 7 the Universe admits then reach the scanners.
    configured = len(list((CONFIGS / "factors").glob("*.yaml")))
    assert factors.rows_in == 11
    assert factors.rows_out == 11 * configured
    assert by_stage[JobStage.BUILD_UNIVERSE].rows_out == 7
    assert by_stage[JobStage.RUN_STRATEGIES].rows_in == 7
    assert by_stage[JobStage.BUILD_CANDIDATES].rows_out == 7


def test_the_blocked_stages_name_the_decision_they_wait_for(local_tmp: Path) -> None:
    result = _run(local_tmp)

    for stage in BLOCKED:
        assert _status(result, stage) is JobStatus.BLOCKED, stage
        run = next(run for run in result.runs if run.job_type is stage)
        assert run.error is not None
        assert run.error.strip()

    assert result.blocked_stages == BLOCKED
    assert not result.is_complete


def test_an_unconfigured_sync_is_skipped_not_faked(local_tmp: Path) -> None:
    result = _run(local_tmp)

    assert _status(result, JobStage.SYNC_DATA) is JobStatus.SKIPPED
    sync = next(run for run in result.runs if run.job_type is JobStage.SYNC_DATA)
    assert sync.rows_in is None
    assert sync.note is not None


def test_a_configured_sync_stage_runs_first(local_tmp: Path) -> None:
    calls: list[str] = []

    def sync() -> StageOutcome:
        calls.append("sync")
        return StageOutcome(rows_in=11, rows_out=11, note="landed raw datasets")

    result = _run(local_tmp, sync=sync)

    assert calls == ["sync"]
    sync_run = next(run for run in result.runs if run.job_type is JobStage.SYNC_DATA)
    assert sync_run.status is JobStatus.SUCCEEDED
    assert sync_run.rows_out == 11
    assert result.universe is not None


def test_a_failing_stage_is_recorded_and_stops_the_pipeline(local_tmp: Path) -> None:
    def sync() -> StageOutcome:
        raise RuntimeError("provider unreachable")

    result = _run(local_tmp, sync=sync)

    sync_run = next(run for run in result.runs if run.job_type is JobStage.SYNC_DATA)
    assert sync_run.status is JobStatus.FAILED
    assert sync_run.error is not None
    assert "provider unreachable" in sync_run.error
    assert sync_run.finished_at is not None
    # Nothing downstream of a failed stage ran: a scan on missing data would
    # be a scan of nothing.
    assert [run.job_type for run in result.runs] == [JobStage.SYNC_DATA]
    assert result.universe is None


def test_the_four_available_snapshots_are_written(local_tmp: Path) -> None:
    result = _run(local_tmp)

    for kind in (
        SnapshotKind.UNIVERSE,
        SnapshotKind.FACTOR,
        SnapshotKind.STRATEGY,
        SnapshotKind.CANDIDATE,
    ):
        assert (local_tmp / "snapshots" / kind.value / "2026-09-04.json").is_file(), (
            kind
        )

    assert result.snapshot_paths


def test_the_missing_market_regime_snapshot_is_reported_not_invented(
    local_tmp: Path,
) -> None:
    """No detector means no regime: the gap is named, not filled."""
    result = _run(local_tmp)

    final = next(
        run for run in result.runs if run.job_type is JobStage.GENERATE_DAILY_SNAPSHOT
    )
    assert final.status is JobStatus.SUCCEEDED
    assert final.note is not None
    assert SnapshotKind.MARKET_REGIME.value in final.note
    assert result.missing_snapshot_kinds == (SnapshotKind.MARKET_REGIME,)


def test_job_runs_are_persisted_for_the_date(local_tmp: Path) -> None:
    result = _run(local_tmp)

    stored = JsonJobStore(local_tmp / "jobs").runs(AS_OF)

    assert [run.job_type for run in stored] == [run.job_type for run in result.runs]
    assert stored[0].status is JobStatus.SKIPPED


def test_a_stage_can_be_restarted_on_its_own(local_tmp: Path) -> None:
    """Re-running one stage leaves one verdict per stage, not two."""
    first = _run(local_tmp)
    second = _run(local_tmp)

    stored = JsonJobStore(local_tmp / "jobs").runs(AS_OF)

    assert len(stored) == len(JobStage)
    assert [run.job_type for run in stored] == [run.job_type for run in first.runs]
    assert first.candidates == second.candidates


def test_the_pipeline_reports_the_scan_it_produced(local_tmp: Path) -> None:
    result = _run(local_tmp)

    assert result.universe is not None
    assert len(result.universe.included) == 7
    assert len(result.strategy_results) == 7
    assert len(result.candidates) == 7
    assert all(
        candidate.next_action.value == "WATCH" for candidate in result.candidates
    )


def test_a_stage_that_produced_nothing_is_not_a_success_with_a_zero(
    local_tmp: Path,
) -> None:
    """An empty raw root yields no bars, and the pipeline says so."""
    empty = local_tmp / "empty"
    empty.mkdir()
    (empty / "daily_bars_long.csv").write_text("symbol,trade_date\n", encoding="utf-8")
    (empty / "securities.csv").write_text("symbol,name\n", encoding="utf-8")

    result = run_daily(
        csv_root=empty,
        as_of=AS_OF + timedelta(days=1),
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=tuple(
            load_factor_config(path)
            for path in sorted((CONFIGS / "factors").glob("*.yaml"))
        ),
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=JsonSnapshotStore(local_tmp / "snapshots"),
        job_store=JsonJobStore(local_tmp / "jobs"),
        dataset=LONG_DATASET,
    )

    assert result.universe is not None
    assert result.universe.included == ()
    assert result.candidates == ()
    assert result.factor_results == ()
    assert _status(result, JobStage.COMPUTE_FACTORS) is JobStatus.SUCCEEDED
