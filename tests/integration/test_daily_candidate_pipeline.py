"""Integration test verifying full daily pipeline execution through candidate stage."""

from datetime import UTC, datetime
from pathlib import Path

from astock_lens.candidates.policy import RepresentativeCandidatePolicy
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import JobStage
from astock_lens.factors.config import load_factor_config
from astock_lens.jobs.models import JobStatus
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines.daily import run_daily
from astock_lens.qualifications.registry import load_canonical_qualifiers
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LONG_DATASET = "daily_bars_long"


def test_daily_pipeline_executes_regime_validation_signal_and_candidates(
    local_tmp: Path,
) -> None:
    """测试日常管线在配置资格与候选政策后，顺畅执行市场环境、市场验证、信号与候选发布。"""
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    policy = RepresentativeCandidatePolicy(
        version="v1", soft_reserve_per_strategy=3, max_candidates=50
    )

    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    result = run_daily(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset=LONG_DATASET,
        qualifiers=qualifiers,
        candidate_policy=policy,
    )

    # 验证各阶段执行状态
    runs_by_type = {run.job_type: run for run in result.runs}
    assert runs_by_type[JobStage.DETECT_REGIME].status == JobStatus.SUCCEEDED
    assert runs_by_type[JobStage.MARKET_VALIDATE].status == JobStatus.SUCCEEDED
    assert runs_by_type[JobStage.RUN_SIGNALS].status == JobStatus.SUCCEEDED
    assert runs_by_type[JobStage.BUILD_CANDIDATES].status == JobStatus.SUCCEEDED

    # 验证 CANDIDATE 快照成功落盘
    assert (local_tmp / "snapshots" / "CANDIDATE" / "2026-09-04.json").is_file()
