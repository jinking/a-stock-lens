"""Candidate-v2 market evidence impact audit unit tests.

Auditable impact report tests:
- Explicit denominator and counts per primary strategy;
- Accurate tracking of complete 5D evidence vs missing industry/benchmark/volume;
- Deterministic counts of BREAKDOWN, TREND_WEAKEN, NO_SIGNAL;
- Markdown output formatting and strict read-only guarantee.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astock_lens.calibration.candidate_v2_impact import (
    CandidateV2ImpactReport,
    StrategyImpactSummary,
    compute_candidate_v2_impact,
    render_candidate_v2_impact_markdown,
)
from astock_lens.cli.app import app
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import DataStatus, SnapshotKind
from astock_lens.domain.models import DailyBar, SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def _factor(
    symbol: str, factor: str, value: float | None, status: DataStatus = DataStatus.VALUE
) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _qual(
    symbol: str, strategy_id: str = "momentum", rank: float = 0.95
) -> StrategyQualification:
    return StrategyQualification(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version="v1",
        as_of=AS_OF,
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=rank,
        reasons=(),
        lineage=SnapshotLineage(strategy_version="v1"),
    )


def _bar(symbol: str, count: int) -> tuple[DailyBar, ...]:
    return tuple(
        DailyBar(
            symbol=symbol,
            trade_date=AS_OF.date(),
            open=10.0,
            high=10.5,
            low=9.5,
            close=10.0,
            volume=1000.0,
        )
        for _ in range(count)
    )


def test_compute_candidate_v2_impact_explicit_counts() -> None:
    # 构造标的：
    # s1: 完整5D, BREAKOUT (prox=0.96)
    # s2: 缺 volume_ratio (<20 bars), BREAKDOWN (ret_20d=-0.20)
    # s3: 缺 industry, TREND_WEAKEN (ret_60d=0.20, ret_20d=-0.08)
    quals = (
        _qual("s1", "momentum", 0.99),
        _qual("s2", "momentum", 0.98),
        _qual("s3", "momentum", 0.97),
    )
    factors = (
        _factor("s1", "ret_20d", 0.10),
        _factor("s1", "ret_60d", 0.15),
        _factor("s1", "proximity_52w_high", 0.96),
        _factor("s2", "ret_20d", -0.20),
        _factor("s2", "ret_60d", -0.10),
        _factor("s2", "proximity_52w_high", 0.70),
        _factor("s3", "ret_20d", -0.08),
        _factor("s3", "ret_60d", 0.20),
        _factor("s3", "proximity_52w_high", 0.88),
    )
    # s1 有 20 根 bar，s2 只有 5 根 bar，s3 有 20 根 bar
    bars = _bar("s1", 20) + _bar("s2", 5) + _bar("s3", 20)
    industry_mapped = {"s1", "s2"}  # s3 缺行业
    benchmark_available = True  # 基准具备

    report = compute_candidate_v2_impact(
        qualifications=quals,
        factors=factors,
        bars=bars,
        industry_mapped_symbols=industry_mapped,
        benchmark_available=benchmark_available,
        as_of=AS_OF,
    )

    assert isinstance(report, CandidateV2ImpactReport)
    assert len(report.summaries) == 1
    summary = report.summaries[0]
    assert summary.strategy_id == "momentum"
    assert summary.qualified_count == 3
    assert summary.missing_volume_ratio_count == 1  # s2
    assert summary.missing_industry_count == 1  # s3
    assert summary.missing_benchmark_count == 0  # 基准可用
    assert summary.complete_5d_evidence_count == 1  # 仅 s1 完整
    assert summary.candidate_v1_count == 3
    assert summary.breakdown_count == 1  # s2
    assert summary.trend_weaken_count == 1  # s3
    assert summary.no_signal_count == 0  # s1 为 BREAKOUT


def test_candidate_v2_impact_markdown_render() -> None:
    report = CandidateV2ImpactReport(
        as_of=AS_OF,
        summaries=(
            StrategyImpactSummary(
                strategy_id="momentum",
                qualified_count=100,
                complete_5d_evidence_count=85,
                missing_industry_count=5,
                missing_benchmark_count=0,
                missing_volume_ratio_count=10,
                candidate_v1_count=100,
                breakdown_count=4,
                trend_weaken_count=6,
                no_signal_count=12,
            ),
        ),
    )

    md = render_candidate_v2_impact_markdown(report)
    assert "Candidate v2 市场证据与技术信号影响审计报告" in md
    assert "momentum" in md
    assert "100" in md
    assert "85" in md
    assert "BREAKDOWN" in md


def test_candidate_v2_impact_cli_execution_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_root = tmp_path / "snapshots"
    store = JsonSnapshotStore(snapshot_root)

    # 注入基础 FACTOR 和 STRATEGY
    store.write(
        SnapshotKind.FACTOR,
        AS_OF,
        [
            FactorResult(
                symbol="600519.SH",
                factor="ret_20d",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=0.10,
            )
        ],
    )
    store.write(
        SnapshotKind.STRATEGY,
        AS_OF,
        [
            StrategyResult(
                symbol="600519.SH",
                strategy_id="momentum",
                as_of=AS_OF,
                score=80.0,
                rank_percentile=0.95,
                eligible=True,
                strategy_version="v1",
                lineage=SnapshotLineage(strategy_version="v1"),
            )
        ],
    )

    # 记录 snapshot 目录运行前的 sha256 指纹
    def _fingerprint(path: Path) -> dict[str, str]:
        return {
            str(f.relative_to(path)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in path.rglob("*")
            if f.is_file()
        }

    before_fp = _fingerprint(snapshot_root)

    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snapshot_root))
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "candidate-v2-impact",
            "--as-of",
            "2026-09-20",
            "--output-dir",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    # 产物落盘
    assert (out_dir / "candidate-v2-impact-2026-09-20.json").is_file()
    assert (out_dir / "candidate-v2-impact-2026-09-20.md").is_file()

    # 核心只读红线：快照目录绝未发生任何改写
    after_fp = _fingerprint(snapshot_root)
    assert before_fp == after_fp
