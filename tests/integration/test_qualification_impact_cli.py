"""Integration tests for the read-only qualification impact audit CLI.

Pins down:

- the command reads stored FACTOR / STRATEGY snapshots and strict canonical
  qualifiers, and writes only the two audit files under ``--output-dir``;
- it guarantees zero production mutation across snapshot / watchlist / job roots;
- it fails loudly when the required snapshots are absent.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from typer.testing import CliRunner

from astock_lens.cli.app import _as_of, app
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import DataStatus, SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult

DAY = "2026-09-04"


def _factor(symbol: str, name: str, value: float, day: datetime) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=day,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _growth_result(
    symbol: str, day: datetime, *, rank_percentile: float = 0.95
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id="growth",
        strategy_version="v1",
        as_of=day,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=90.0,
        rank_percentile=rank_percentile,
    )


def _write_snapshots(snapshot_root: Path, day: datetime) -> None:
    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.FACTOR,
        day,
        (
            _factor("600000.SH", "net_profit_parent_yoy", 20.0, day),
            _factor("600000.SH", "revenue_yoy", 8.0, day),
            _factor("600000.SH", "roe_ttm", 9.0, day),
            _factor("600001.SH", "net_profit_parent_yoy", 10.0, day),
            _factor("600001.SH", "revenue_yoy", 8.0, day),
            _factor("600001.SH", "roe_ttm", 9.0, day),
        ),
    )
    store.write(
        SnapshotKind.STRATEGY,
        day,
        (
            _growth_result("600000.SH", day),
            _growth_result("600001.SH", day),
        ),
    )


def _fingerprint(root: Path) -> dict[str, tuple[int, int, str]]:
    """文件名 + 大小 + mtime + 内容 hash 的确定性指纹。"""
    result: dict[str, tuple[int, int, str]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[path.relative_to(root).as_posix()] = (
                stat.st_size,
                stat.st_mtime_ns,
                digest,
            )
    return result


def test_qualification_impact_cli_is_read_only(tmp_path: Path) -> None:
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    output_dir = tmp_path / "impact_out"

    day = _as_of(DAY)
    _write_snapshots(snapshot_root, day)
    watchlist_root.mkdir(parents=True)
    job_root.mkdir(parents=True)
    (watchlist_root / "SENTINEL.txt").write_text(
        "watchlist untouched", encoding="utf-8"
    )
    (job_root / "SENTINEL.txt").write_text("job untouched", encoding="utf-8")

    before = (
        _fingerprint(snapshot_root),
        _fingerprint(watchlist_root),
        _fingerprint(job_root),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "qualification-impact",
            "--as-of",
            DAY,
            "--output-dir",
            str(output_dir),
        ],
        env={
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_WATCHLIST_ROOT": str(watchlist_root),
            "ASTOCK_JOB_ROOT": str(job_root),
        },
    )
    assert result.exit_code == 0, result.output
    assert "Qualification impact audit written" in result.stdout

    after = (
        _fingerprint(snapshot_root),
        _fingerprint(watchlist_root),
        _fingerprint(job_root),
    )
    # 只读：Snapshot / Watchlist / Job 状态逐字节不变。
    assert before == after

    json_path = output_dir / f"qualification-impact-{DAY}.json"
    md_path = output_dir / f"qualification-impact-{DAY}.md"
    assert json_path.is_file()
    assert md_path.is_file()

    document = json.loads(json_path.read_text(encoding="utf-8"))
    strategies = {item["strategy_id"]: item for item in document["strategies"]}
    growth = strategies["growth"]
    assert growth["strategy_eligible_count"] == 2
    assert growth["top_ten_count"] == 2
    assert growth["absolute_pass_count"] == 1
    assert growth["dual_pass_count"] == 1
    assert growth["qualified_symbols"] == ["600000.SH"]

    markdown = md_path.read_text(encoding="utf-8")
    assert (
        "| strategy | eligible | ranked | top10 | absolute-pass | dual-pass |"
        in markdown
    )
    assert "`growth`" in markdown


def test_qualification_impact_cli_fails_on_missing_snapshot(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "qualification-impact",
            "--as-of",
            DAY,
            "--output-dir",
            str(tmp_path / "out"),
        ],
        env={"ASTOCK_SNAPSHOT_ROOT": str(tmp_path / "snapshots")},
    )
    assert result.exit_code != 0
    assert "no FACTOR snapshot" in result.output
