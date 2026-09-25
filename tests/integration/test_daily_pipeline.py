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
from astock_lens.pipelines.daily import EXECUTION_ORDER, DailyRunResult, run_daily
from astock_lens.qualifications.registry import load_canonical_qualifiers
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
    JobStage.COMPUTE_FACTORS,
    JobStage.BUILD_UNIVERSE,
    JobStage.RUN_STRATEGIES,
    JobStage.DETECT_REGIME,
    JobStage.MARKET_VALIDATE,
    JobStage.RUN_SIGNALS,
    JobStage.GENERATE_DAILY_SNAPSHOT,
)

# The stages the design requires and this slice cannot run without explicit policy
# configuration.
BLOCKED = (
    JobStage.BUILD_CANDIDATES,
    JobStage.UPDATE_WATCHLIST,
)

# The order the domain requires: a Candidate is the object the market and signal
# layers have already spoken about, so building candidates before them would
# publish a partial result under a name that promises a complete one.
# `COMPUTE_FACTORS → BUILD_UNIVERSE` is the one reviewed deviation: the
# Universe's liquidity rule consumes the `avg_amount_20d` factor.
CANONICAL_ORDER = (
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


_DEFAULT_QUALIFIERS = object()


def _run(
    local_tmp: Path,
    *,
    sync: Callable[[], StageOutcome] | None = None,
    dataset: str = LONG_DATASET,
    qualifiers: object = _DEFAULT_QUALIFIERS,
) -> DailyRunResult:
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    if qualifiers is _DEFAULT_QUALIFIERS:
        factor_names = frozenset(c.name for c in factor_configs)
        active_qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    else:
        active_qualifiers = qualifiers  # type: ignore[assignment]

    return run_daily(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=JsonSnapshotStore(local_tmp / "snapshots"),
        job_store=JsonJobStore(local_tmp / "jobs"),
        dataset=dataset,
        sync=sync,
        qualifiers=active_qualifiers,
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


def test_execution_order_puts_candidates_after_market_and_signals() -> None:
    """Candidate 必须排在 Market Regime / Market Validation / Signal 之后。"""
    assert EXECUTION_ORDER == CANONICAL_ORDER


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
    assert by_stage[JobStage.BUILD_UNIVERSE].rows_out == 6
    assert by_stage[JobStage.RUN_STRATEGIES].rows_in == 6


# 「BUILD_CANDIDATES 被阻断」两行：行序与原用例一致，label 兼作运行根目录名，
# 行与行不共享现场（原用例各自拿一份新的 `local_tmp`）。
# 列 = label, qualifiers, expected_errors, no_candidates：
#   - `layers-missing` 是原
#     test_the_candidate_stage_is_blocked_while_its_layers_are_missing：
#     两层齐缺（资格规则与候选政策都没装配），两条 error 文案都要点名，
#     且没有任何候选被写出来冒充完整结果；
#   - `policy-deferred` 是原 test_the_blocked_candidate_stage_names_the_deferred_policy：
#     生产资格规则已装配、只有候选政策 Deferred；该行原本只断言阻断与文案，
#     所以 `no_candidates` 为 False，不额外加强。
BLOCKED_CANDIDATE_CASES = (
    # 原 docstring：未配置资格门槛与候选政策时，BUILD_CANDIDATES 安全阻断。
    (
        "layers-missing",
        None,
        (
            "strategy qualification rules are not configured",
            "candidate qualification policy is Deferred",
        ),
        True,
    ),
    # 原 docstring：入选规则未批准时，阶段必须点名 Deferred，而不是退回某个默认规则。
    (
        "policy-deferred",
        _DEFAULT_QUALIFIERS,
        ("candidate qualification policy is Deferred",),
        False,
    ),
)


def test_the_candidate_stage_is_blocked_while_its_layers_are_missing(
    local_tmp: Path,
) -> None:
    """未配置资格门槛与候选政策时，BUILD_CANDIDATES 安全阻断。

    原 2 条阻断用例逐条成行；循环只收集，断言在表外一次完成，
    失败消息点名行 label 与该行的实际值。
    """
    wrong = []
    for label, qualifiers, expected_errors, no_candidates in BLOCKED_CANDIDATE_CASES:
        result = _run(local_tmp / label, qualifiers=qualifiers)
        run = next(
            item for item in result.runs if item.job_type is JobStage.BUILD_CANDIDATES
        )
        if run.status is not JobStatus.BLOCKED:
            wrong.append(f"{label}: status 为 {run.status}，期望 BLOCKED")
        if run.error is None:
            wrong.append(f"{label}: run.error 为 None")
        else:
            for expected in expected_errors:
                if expected not in run.error:
                    wrong.append(f"{label}: error={run.error!r} 不含 {expected!r}")
        if no_candidates and result.candidates != ():
            wrong.append(f"{label}: candidates={result.candidates!r}，期望 ()")
    assert not wrong, "BUILD_CANDIDATES 未被安全阻断:\n" + "\n".join(wrong)


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


def test_the_snapshots_the_pipeline_can_produce_are_written(local_tmp: Path) -> None:
    result = _run(local_tmp)

    for kind in (
        SnapshotKind.UNIVERSE,
        SnapshotKind.FACTOR,
        SnapshotKind.STRATEGY,
        SnapshotKind.MARKET_REGIME,
    ):
        assert (local_tmp / "snapshots" / kind.value / "2026-09-04.json").is_file(), (
            kind
        )

    # CANDIDATE 不在其中：Business 层被 BLOCKED，所以它没有生产者。
    assert not (local_tmp / "snapshots" / "CANDIDATE" / "2026-09-04.json").exists()
    assert result.snapshot_paths


def test_the_missing_candidate_snapshot_is_reported_not_invented(
    local_tmp: Path,
) -> None:
    """No approved candidate policy means no candidates: the gap is named, not filled."""
    result = _run(local_tmp)

    final = next(
        run for run in result.runs if run.job_type is JobStage.GENERATE_DAILY_SNAPSHOT
    )
    assert final.status is JobStatus.SUCCEEDED
    assert final.note is not None
    assert SnapshotKind.MARKET_REGIME.value in final.note
    # 最后一阶段必须同时说清"写了哪些"和"哪些没有生产者"。
    assert "snapshots written:" in final.note
    assert "blocked business stages:" in final.note
    assert JobStage.BUILD_CANDIDATES.value in final.note
    assert result.missing_snapshot_kinds == (SnapshotKind.CANDIDATE,)


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


def test_a_snapshot_conflict_fails_the_stage_and_stops_the_pipeline(
    local_tmp: Path,
) -> None:
    """同一天已经有不同内容的正式快照：不许覆盖，也不许继续往下跑。"""
    JsonSnapshotStore(local_tmp / "snapshots").write(SnapshotKind.FACTOR, AS_OF, ())

    result = _run(local_tmp)

    failed = next(
        run for run in result.runs if run.job_type is JobStage.COMPUTE_FACTORS
    )
    assert failed.status is JobStatus.FAILED
    assert failed.error is not None
    # 冲突必须点名 kind 与日期，否则 Job Manifest 里只剩一句无用的话。
    assert SnapshotKind.FACTOR.value in failed.error
    assert AS_OF.date().isoformat() in failed.error
    # 下游任何阶段都没有跑：在冲突的当天继续算，只会产生更多垃圾。
    assert [run.job_type for run in result.runs] == [
        JobStage.SYNC_DATA,
        JobStage.NORMALIZE,
        JobStage.COMPUTE_FACTORS,
    ]


def test_a_snapshot_conflict_is_recorded_in_the_job_manifest(
    local_tmp: Path,
) -> None:
    JsonSnapshotStore(local_tmp / "snapshots").write(SnapshotKind.FACTOR, AS_OF, ())

    _run(local_tmp)
    stored = JsonJobStore(local_tmp / "jobs").runs(AS_OF)

    factors = next(run for run in stored if run.job_type is JobStage.COMPUTE_FACTORS)
    assert factors.status is JobStatus.FAILED
    assert factors.error is not None
    assert SnapshotKind.FACTOR.value in factors.error


def test_the_pipeline_reports_the_scan_it_produced(local_tmp: Path) -> None:
    result = _run(local_tmp)

    assert result.universe is not None
    assert len(result.universe.included) == 6
    # One result per admitted symbol per scanner that ran. The fixture has no
    # landed statements, so the fundamental scanners report ineligible — a
    # verdict, not a missing row.
    scanners = len(load_scanners(CONFIGS / "strategies"))
    assert scanners >= 2
    assert len(result.strategy_results) == 6 * scanners
    # 候选资格没有批准的规则，所以这里一个候选都不该出现。
    assert result.candidates == ()


def test_the_fundamental_scanners_report_ineligibility_with_a_reason(
    local_tmp: Path,
) -> None:
    """No landed statements means no evidence — said out loud, not scored."""
    result = _run(local_tmp)

    quality = [
        item for item in result.strategy_results if item.strategy_id == "quality"
    ]

    assert len(quality) == 6
    assert all(item.eligible is False for item in quality)
    assert all(item.score is None for item in quality)
    assert all(item.risks for item in quality)


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
