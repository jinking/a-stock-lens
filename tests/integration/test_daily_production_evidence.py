"""Integration tests verifying benchmark and industry evidence wiring into daily pipeline."""

import csv
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from astock_lens.candidates.policy import RepresentativeCandidatePolicy
from astock_lens.cli.app import _production_industry_map, _run_daily, app
from astock_lens.data.benchmark import (
    BENCHMARK_BARS_ENV,
    read_benchmark_bars,
)
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import JobStage
from astock_lens.domain.models import DailyBar
from astock_lens.factors.config import load_factor_config
from astock_lens.jobs.models import JobStatus
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines.daily import DailyRunResult, run_daily
from astock_lens.qualifications.registry import load_canonical_qualifiers
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CSV = ROOT / "tests" / "fixtures" / "csv"
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
BENCHMARK_ID = "000985.CSI"

BENCHMARK_HEADER = "symbol,trade_date,open,high,low,close,volume,amount\n"


def _write_benchmark_csv(path: Path, count: int = 70) -> Path:
    """写入指定天数的基准指数日线 CSV 文件。"""
    p = FIXTURE_CSV / "daily_bars_long.csv"
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        dates = sorted({date.fromisoformat(row["trade_date"]) for row in reader})
    selected_dates = dates[-count:]

    lines = [BENCHMARK_HEADER]
    for i, d in enumerate(selected_dates):
        lines.append(
            f"{BENCHMARK_ID},{d.isoformat()},3000.0,3050.0,2950.0,{3000.0 + i},100000.0,1000000.0\n"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _write_industry_csv(dir_path: Path, filename: str = "2026-09-04.csv") -> Path:
    """写入包含全部测试标的的申万行业 CSV 文件。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / filename
    rows = [
        ("000001.SZ", "sw2_bank", "银行"),
        ("000002.SZ", "sw2_realestate", "房地产"),
        ("000003.SZ", "sw2_software", "软件开发"),
        ("000004.SZ", "sw2_software", "软件开发"),
        ("000005.SZ", "sw2_env", "环保"),
        ("000006.SZ", "sw2_realestate", "房地产"),
        ("300750.SZ", "sw2_battery", "电池"),
        ("600000.SH", "sw2_bank", "银行"),
        ("600519.SH", "sw2_liquor", "白酒"),
        ("830799.BJ", "sw2_machinery", "通用设备"),
        ("900948.SH", "sw2_power", "电力"),
    ]
    lines = ["symbol,industry_id,industry_name,as_of,provider,source_ref\n"]
    for sym, ind_id, ind_name in rows:
        lines.append(
            f"{sym},{ind_id},{ind_name},2026-09-04T15:00:00+00:00,westock-cli,\n"
        )
    file_path.write_text("".join(lines), encoding="utf-8")
    return file_path


def _benchmark_bars_tuple(count: int = 70) -> tuple[DailyBar, ...]:
    """生成指定数量的 DailyBar 元组。"""
    p = FIXTURE_CSV / "daily_bars_long.csv"
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        dates = sorted({date.fromisoformat(row["trade_date"]) for row in reader})
    selected_dates = dates[-count:]
    return tuple(
        DailyBar(
            symbol=BENCHMARK_ID,
            trade_date=d,
            open=3000.0,
            high=3050.0,
            low=2950.0,
            close=3000.0 + i,
            volume=100000.0,
            amount=1000000.0,
        )
        for i, d in enumerate(selected_dates)
    )


ALL_INDUSTRY_MAP = {
    "000001.SZ": "银行",
    "000002.SZ": "房地产",
    "000003.SZ": "软件开发",
    "000004.SZ": "软件开发",
    "000005.SZ": "环保",
    "000006.SZ": "房地产",
    "300750.SZ": "电池",
    "600000.SH": "银行",
    "600519.SH": "白酒",
    "830799.BJ": "通用设备",
    "900948.SH": "电力",
}


def test_step1_composition_proves_benchmark_and_industry_reach_run_daily(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 1: 装配测试证明 benchmark_bars 与 industry_by_symbol 被真实传递给 run_daily。"""
    import astock_lens.cli.app as app_module

    bm_path = _write_benchmark_csv(tmp_path / "raw" / "benchmark_bars.csv", count=70)
    _write_industry_csv(tmp_path / "raw" / "westock" / "industry")

    monkeypatch.setenv(BENCHMARK_BARS_ENV, str(bm_path))
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(tmp_path / "raw"))
    monkeypatch.setenv("ASTOCK_STORAGE_ROOT", str(tmp_path / "storage"))

    captured_kwargs: dict[str, Any] = {}

    def spy_run_daily(*args: Any, **kwargs: Any) -> DailyRunResult:
        captured_kwargs.update(kwargs)
        return DailyRunResult(as_of=AS_OF)

    monkeypatch.setattr(app_module, "run_daily", spy_run_daily)

    _run_daily(AS_OF, land=False)

    assert "benchmark_id" in captured_kwargs
    assert captured_kwargs["benchmark_id"] == BENCHMARK_ID
    assert "benchmark_bars" in captured_kwargs
    assert captured_kwargs["benchmark_bars"] is not None
    assert len(captured_kwargs["benchmark_bars"]) == 70

    expected_bars = read_benchmark_bars(
        path=bm_path, benchmark_id=BENCHMARK_ID, as_of=AS_OF
    )
    assert captured_kwargs["benchmark_bars"] == expected_bars

    assert "industry_by_symbol" in captured_kwargs
    assert captured_kwargs["industry_by_symbol"] is not None
    expected_industry = _production_industry_map(AS_OF, root=tmp_path / "raw")
    assert captured_kwargs["industry_by_symbol"] == expected_industry
    assert "300750.SZ" in captured_kwargs["industry_by_symbol"]


def test_step2_missing_benchmark_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 2: 缺失基准指数日线文件时，抛出 FileNotFoundError，CLI 退出码非零且不产出新候选快照。"""
    missing_path = tmp_path / "missing_benchmark.csv"
    _write_industry_csv(tmp_path / "raw" / "westock" / "industry")

    monkeypatch.setenv(BENCHMARK_BARS_ENV, str(missing_path))
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(tmp_path / "raw"))
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("ASTOCK_STORAGE_ROOT", str(storage_root))

    # 1. _run_daily 直接调用严格抛出 FileNotFoundError
    with pytest.raises(FileNotFoundError, match=r"Benchmark bars file not found"):
        _run_daily(AS_OF, land=False)

    # 2. CLI daily 运行退出码非零
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["daily", "--as-of", "2026-09-04", "--allow-incomplete"],
        env={
            BENCHMARK_BARS_ENV: str(missing_path),
            "ASTOCK_CSV_ROOT": str(tmp_path / "raw"),
            "ASTOCK_STORAGE_ROOT": str(storage_root),
        },
    )
    assert result.exit_code != 0

    # 3. 绝不写出新的 Candidate 快照
    candidate_snapshot = storage_root / "snapshots" / "CANDIDATE" / "2026-09-04.json"
    assert not candidate_snapshot.exists()


def test_step3_insufficient_59_benchmark_bars_regime_fails_closed(
    tmp_path: Path,
) -> None:
    """Step 3: 仅 59 根基准日线时，DETECT_REGIME 必须严格阻断 fail-closed，候选快照不得产出。"""
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    policy = RepresentativeCandidatePolicy(
        version="v1", soft_reserve_per_strategy=3, max_candidates=50
    )

    store = JsonSnapshotStore(tmp_path / "snapshots")
    job_store = JsonJobStore(tmp_path / "jobs")

    bars_59 = _benchmark_bars_tuple(count=59)

    result = run_daily(
        csv_root=FIXTURE_CSV,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars_long",
        qualifiers=qualifiers,
        candidate_policy=policy,
        benchmark_id=BENCHMARK_ID,
        benchmark_bars=bars_59,
        industry_by_symbol=ALL_INDUSTRY_MAP,
    )

    runs_by_type = {run.job_type: run for run in result.runs}
    assert runs_by_type[JobStage.DETECT_REGIME].status == JobStatus.FAILED
    assert "000985.CSI benchmark trend" in str(
        runs_by_type[JobStage.DETECT_REGIME].error
    )

    # 下游阶段终止，未产生候选集与候选快照
    assert JobStage.BUILD_CANDIDATES not in runs_by_type
    assert len(result.candidates) == 0
    assert not (tmp_path / "snapshots" / "CANDIDATE" / "2026-09-04.json").exists()


def test_step4_qualified_symbol_missing_industry_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    """Step 4: 达标标的缺失申万行业证据时，MARKET_VALIDATE 必须严格阻断 fail-closed。"""
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    policy = RepresentativeCandidatePolicy(
        version="v1", soft_reserve_per_strategy=3, max_candidates=50
    )

    store = JsonSnapshotStore(tmp_path / "snapshots")
    job_store = JsonJobStore(tmp_path / "jobs")

    bars_70 = _benchmark_bars_tuple(count=70)
    # 构造缺失 300750.SZ（达标标的）的行业映射表
    incomplete_industry_map = {
        k: v for k, v in ALL_INDUSTRY_MAP.items() if k != "300750.SZ"
    }

    result = run_daily(
        csv_root=FIXTURE_CSV,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars_long",
        qualifiers=qualifiers,
        candidate_policy=policy,
        benchmark_id=BENCHMARK_ID,
        benchmark_bars=bars_70,
        industry_by_symbol=incomplete_industry_map,
    )

    runs_by_type = {run.job_type: run for run in result.runs}
    assert runs_by_type[JobStage.DETECT_REGIME].status == JobStatus.SUCCEEDED
    assert runs_by_type[JobStage.MARKET_VALIDATE].status == JobStatus.FAILED
    assert "300750.SZ missing required 5D evidence: industry_excess_return_20d" in str(
        runs_by_type[JobStage.MARKET_VALIDATE].error
    )

    # 下游阶段终止，未产生候选集与快照
    assert JobStage.BUILD_CANDIDATES not in runs_by_type
    assert len(result.candidates) == 0
    assert not (tmp_path / "snapshots" / "CANDIDATE" / "2026-09-04.json").exists()


def test_step5_qualified_symbol_insufficient_volume_bars_fails_closed(
    tmp_path: Path,
) -> None:
    """Step 5: 达标标的有效果量不足 20 根 bar 时，MARKET_VALIDATE 必须严格阻断 fail-closed。"""
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    policy = RepresentativeCandidatePolicy(
        version="v1", soft_reserve_per_strategy=3, max_candidates=50
    )

    csv_root = tmp_path / "csv"
    csv_root.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_CSV / "securities.csv", csv_root / "securities.csv")

    p = FIXTURE_CSV / "daily_bars_long.csv"
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    # 对 300750.SZ，仅保留最后 19 根成交量，其余历史成交量置零（有效量 bar < 20）
    sym_rows = [r for r in rows if r["symbol"] == "300750.SZ"]
    for r in sym_rows[:-19]:
        r["volume"] = "0.0"

    with (csv_root / "daily_bars_long.csv").open("w", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    store = JsonSnapshotStore(tmp_path / "snapshots")
    job_store = JsonJobStore(tmp_path / "jobs")
    bars_70 = _benchmark_bars_tuple(count=70)

    result = run_daily(
        csv_root=csv_root,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars_long",
        securities_dataset="securities",
        qualifiers=qualifiers,
        candidate_policy=policy,
        benchmark_id=BENCHMARK_ID,
        benchmark_bars=bars_70,
        industry_by_symbol=ALL_INDUSTRY_MAP,
    )

    runs_by_type = {run.job_type: run for run in result.runs}
    assert runs_by_type[JobStage.DETECT_REGIME].status == JobStatus.SUCCEEDED
    assert runs_by_type[JobStage.MARKET_VALIDATE].status == JobStatus.FAILED
    assert "300750.SZ missing required 5D evidence: volume_ratio_5_20" in str(
        runs_by_type[JobStage.MARKET_VALIDATE].error
    )

    # 下游阶段终止，未产生候选集与快照
    assert JobStage.BUILD_CANDIDATES not in runs_by_type
    assert len(result.candidates) == 0
    assert not (tmp_path / "snapshots" / "CANDIDATE" / "2026-09-04.json").exists()
