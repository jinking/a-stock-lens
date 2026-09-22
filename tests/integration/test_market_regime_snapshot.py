"""Integration tests for MARKET_REGIME snapshot persistence and today CLI integration.

Verifies:
1. Daily pipeline persists MARKET_REGIME snapshot with exactly one record.
2. Persisted MARKET_REGIME record carries regime_version in lineage.
3. Snapshot immutability: same-date changed-content raises SnapshotConflictError.
4. Independent artifact validator rules for MARKET_REGIME snapshot.
5. `astock today` displays the persisted market regime value.
"""

import csv
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from artifacts.validator import validate_snapshot
from typer.testing import CliRunner

from astock_lens.candidates.models import Candidate
from astock_lens.cli.app import app
from astock_lens.data.snapshots.store import JsonSnapshotStore, SnapshotConflictError
from astock_lens.domain.enums import (
    JobStage,
    MarketRegime,
    MarketValidation,
    NextAction,
    Signal,
    SnapshotKind,
)
from astock_lens.domain.models import DailyBar, SnapshotLineage
from astock_lens.factors.config import load_factor_config
from astock_lens.jobs.models import JobStatus
from astock_lens.jobs.store import JsonJobStore
from astock_lens.market.regime import MarketRegimeResult
from astock_lens.pipelines.daily import run_daily
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.qualifications.registry import load_canonical_qualifiers
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CSV = ROOT / "tests" / "fixtures" / "csv"
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
BENCHMARK_ID = "000985.CSI"

runner = CliRunner()


def _benchmark_bars(count: int = 70) -> tuple[DailyBar, ...]:
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


def _run_pipeline(store: JsonSnapshotStore, job_store: JsonJobStore) -> None:
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    active_qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    run_daily(
        csv_root=FIXTURE_CSV,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars_long",
        qualifiers=active_qualifiers,
        benchmark_id=BENCHMARK_ID,
        benchmark_bars=_benchmark_bars(70),
    )


def test_step1_daily_pipeline_writes_exactly_one_market_regime_record(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    _run_pipeline(store, job_store)

    # 1. 验证 MARKET_REGIME 快照文件被实际写入
    snap_path = store.path_for(SnapshotKind.MARKET_REGIME, AS_OF)
    assert snap_path.is_file(), f"Expected snapshot file at {snap_path}"

    # 2. 验证 store 能够查出日期
    assert AS_OF.date().isoformat() in store.dates(SnapshotKind.MARKET_REGIME)

    # 3. 验证记录数量恰好为 1
    records = store.read(SnapshotKind.MARKET_REGIME, AS_OF)
    assert len(records) == 1, f"Expected exactly 1 record, got {len(records)}"

    rec = records[0]
    assert isinstance(rec, dict)
    assert rec["regime"] in {
        "BULL",
        "RANGE_UP",
        "RANGE",
        "RANGE_DOWN",
        "BEAR",
        "EXTREME_VOLATILITY",
    }
    assert rec["breadth_ratio"] is not None
    assert rec["index_trend"] is not None
    assert isinstance(rec["reasons"], list)
    assert len(rec["reasons"]) > 0


def test_step2_market_regime_snapshot_carries_lineage_regime_version(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    _run_pipeline(store, job_store)

    records = store.read(SnapshotKind.MARKET_REGIME, AS_OF)
    assert len(records) == 1
    rec = records[0]
    assert "lineage" in rec
    lineage = rec["lineage"]
    assert isinstance(lineage, dict)
    assert lineage.get("regime_version") == "v1"


def test_step3_same_date_changed_content_raises_snapshot_conflict(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    # 先写入一个同日期的不同内容快照
    conflicting_record = MarketRegimeResult(
        as_of=AS_OF,
        regime=MarketRegime.BEAR,
        breadth_ratio=0.1,
        index_trend=0.8,
        reasons=("pre-existing contradictory regime",),
        lineage=SnapshotLineage(regime_version="v0_conflict"),
    )
    store.write(SnapshotKind.MARKET_REGIME, AS_OF, [conflicting_record])

    # 再次尝试直接写入不同记录应当抛出 SnapshotConflictError
    another_record = MarketRegimeResult(
        as_of=AS_OF,
        regime=MarketRegime.BULL,
        breadth_ratio=0.9,
        index_trend=1.2,
        reasons=("conflicting bull regime",),
        lineage=SnapshotLineage(regime_version="v1"),
    )
    with pytest.raises(SnapshotConflictError):
        store.write(SnapshotKind.MARKET_REGIME, AS_OF, [another_record])

    # 通过 pipeline 执行也必须在 DETECT_REGIME 阶段抛出冲突阻断
    result = run_daily(
        csv_root=FIXTURE_CSV,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=tuple(
            load_factor_config(p) for p in sorted((CONFIGS / "factors").glob("*.yaml"))
        ),
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars_long",
        qualifiers=load_canonical_qualifiers(),
        benchmark_id=BENCHMARK_ID,
        benchmark_bars=_benchmark_bars(70),
    )
    regime_run = next(
        run for run in result.runs if run.job_type is JobStage.DETECT_REGIME
    )
    assert regime_run.status is JobStatus.FAILED
    assert regime_run.error is not None
    assert "SnapshotConflictError" in regime_run.error
    assert SnapshotKind.MARKET_REGIME.value in regime_run.error


def test_step5_artifact_validator_for_market_regime() -> None:
    # 1. 干净的合法记录
    clean_record = {
        "as_of": AS_OF.isoformat(),
        "regime": "BULL",
        "breadth_ratio": 0.65,
        "index_trend": 1.05,
        "reasons": ["宽度走强", "指数上行"],
        "lineage": {"regime_version": "v1"},
    }
    findings = validate_snapshot("MARKET_REGIME", [clean_record], as_of=AS_OF)
    assert findings == (), f"Expected clean findings, got {findings}"

    # 2. 缺失必填字段 (缺少 reasons)
    incomplete_record = {
        "as_of": AS_OF.isoformat(),
        "regime": "BULL",
        "breadth_ratio": 0.65,
        "index_trend": 1.05,
        "lineage": {"regime_version": "v1"},
    }
    incomplete_findings = validate_snapshot(
        "MARKET_REGIME", [incomplete_record], as_of=AS_OF
    )
    assert any(f.check == "required_keys" for f in incomplete_findings)

    # 3. 记录条数不为 1 (例如空快照或 2 条)
    empty_findings = validate_snapshot("MARKET_REGIME", [], as_of=AS_OF)
    assert any(f.check == "market_regime_count" for f in empty_findings)

    multi_findings = validate_snapshot(
        "MARKET_REGIME", [clean_record, clean_record], as_of=AS_OF
    )
    assert any(f.check == "market_regime_count" for f in multi_findings)

    # 4. 非法词表
    bad_vocab_record = dict(clean_record, regime="UNKNOWN_REGIME")
    bad_vocab_findings = validate_snapshot(
        "MARKET_REGIME", [bad_vocab_record], as_of=AS_OF
    )
    assert any(f.check == "regime_vocabulary" for f in bad_vocab_findings)

    # 5. 空版本号
    empty_ver_record = dict(clean_record, lineage={"regime_version": ""})
    empty_ver_findings = validate_snapshot(
        "MARKET_REGIME", [empty_ver_record], as_of=AS_OF
    )
    assert any(f.check == "empty_version" for f in empty_ver_findings)


def test_step6_seed_market_regime_and_candidate_today_cli_prints_it(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)

    # 写入 MARKET_REGIME 快照
    regime_record = MarketRegimeResult(
        as_of=AS_OF,
        regime=MarketRegime.BULL,
        breadth_ratio=0.72,
        index_trend=1.08,
        reasons=("全市场宽度强劲", "基准指数走多"),
        lineage=SnapshotLineage(regime_version="v1"),
    )
    store.write(SnapshotKind.MARKET_REGIME, AS_OF, [regime_record])

    # 写入 CANDIDATE 快照
    candidate = Candidate(
        symbol="600519.SH",
        as_of=AS_OF,
        next_action=NextAction.WATCH,
        lineage=SnapshotLineage(
            strategy_version="v1",
            qualification_version="v1",
            candidate_policy_version="v1",
            regime_version="v1",
            market_validation_version="v1",
            signal_version="v1",
            universe_snapshot="2026-09-04:u1",
        ),
        primary_strategy_id="momentum",
        strategy_qualifications=(
            StrategyQualification(
                symbol="600519.SH",
                strategy_id="momentum",
                strategy_version="v1",
                qualification_version="v1",
                qualified=True,
                percentile_pass=True,
                absolute_pass=True,
                rank_percentile=0.98,
                as_of=AS_OF,
            ),
        ),
        strategy_results=(
            StrategyResult(
                symbol="600519.SH",
                strategy_id="momentum",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                score=92.0,
                rank_percentile=0.98,
                lineage=SnapshotLineage(strategy_version="v1"),
            ),
        ),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.BREAKOUT,
        reasons=("qualified momentum breakout",),
        risks=(),
    )
    store.write(SnapshotKind.CANDIDATE, AS_OF, [candidate])

    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))
    result = runner.invoke(app, ["today", "--as-of", "2026-09-04"])
    assert result.exit_code == 0, result.output
    output = result.output

    assert "as_of: 2026-09-04" in output
    assert "candidates: 1" in output
    assert "market_regime: BULL" in output
