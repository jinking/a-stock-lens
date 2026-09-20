"""`astock calibrate market-signal-readiness` 命令集成测试 (Plan C Task 2).

验证：
- 严格只读：运行前后 Snapshot/Watchlist/Job 目录指纹完全一致；
- 缺少快照：缺少 FACTOR 或 STRATEGY 快照时退出非 0，并点名缺失类别；
- 配置非法：资格配置损坏或未知阈值键时立即失败（fail loudly）；
- 确定性输出：在 --output-dir 下生成符合命名的 .json 和 .md 产物。
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astock_lens.cli.app import app
from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.domain.enums import DataStatus, SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult

AS_OF_STR = "2026-09-19"
AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


def _hash_tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    hashes = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            hashes[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
    return hashes


def test_missing_snapshot_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 2: 缺少 FACTOR 或 STRATEGY 快照时报错并指出缺失类别。"""
    runner = CliRunner()
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))

    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "calibrate",
            "market-signal-readiness",
            "--as-of",
            AS_OF_STR,
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code != 0
    assert "FACTOR" in result.output or "STRATEGY" in result.output


def test_read_only_and_deterministic_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 1 & Step 4: 严格只读，生成正确的 JSON 与 MD 报告。"""
    runner = CliRunner()
    snap_dir = tmp_path / "snapshots"
    watch_dir = tmp_path / "watchlist"
    job_dir = tmp_path / "jobs"
    out_dir = tmp_path / "out"

    snap_dir.mkdir(parents=True)
    watch_dir.mkdir(parents=True)
    job_dir.mkdir(parents=True)

    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_dir))
    monkeypatch.setenv("ASTOCK_WATCHLIST_ROOT", str(watch_dir))
    monkeypatch.setenv("ASTOCK_JOB_ROOT", str(job_dir))

    store = resolve_snapshot_store(snap_dir)
    fr = FactorResult(
        symbol="600519.SH",
        factor="ret_20d",
        as_of=AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(),
        raw_value=0.12,
    )
    sr = StrategyResult(
        symbol="600519.SH",
        strategy_id="value",
        as_of=AS_OF,
        score=88.0,
        rank_percentile=0.95,
        eligible=True,
        strategy_version="v1",
        lineage=SnapshotLineage(),
        factor_snapshot=(),
    )
    store.write(SnapshotKind.FACTOR, AS_OF, [fr])
    store.write(SnapshotKind.STRATEGY, AS_OF, [sr])

    # 记录执行前各目录指纹
    before_snaps = _hash_tree(snap_dir)
    before_watch = _hash_tree(watch_dir)
    before_jobs = _hash_tree(job_dir)

    result = runner.invoke(
        app,
        [
            "calibrate",
            "market-signal-readiness",
            "--as-of",
            AS_OF_STR,
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0
    assert (out_dir / f"market-signal-readiness-{AS_OF_STR}.json").is_file()
    assert (out_dir / f"market-signal-readiness-{AS_OF_STR}.md").is_file()

    # 验证严格只读
    assert _hash_tree(snap_dir) == before_snaps
    assert _hash_tree(watch_dir) == before_watch
    assert _hash_tree(job_dir) == before_jobs


def test_invalid_qualification_config_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 3: 资格规则配置非法时 fail loudly，绝不以空合格标的静默产生报告。"""
    runner = CliRunner()
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir(parents=True)
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_dir))

    # 指向一个损坏的资格配置文件目录
    bad_cfg_dir = tmp_path / "configs" / "qualifications"
    bad_cfg_dir.mkdir(parents=True)
    (bad_cfg_dir / "value.yaml").write_text(
        "rules: [{unknown_key: foo}]", encoding="utf-8"
    )
    monkeypatch.setenv("ASTOCK_QUALIFICATION_DIR", str(bad_cfg_dir))

    store = resolve_snapshot_store(snap_dir)
    fr = FactorResult(
        symbol="600519.SH",
        factor="ret_20d",
        as_of=AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(),
        raw_value=0.12,
    )
    sr = StrategyResult(
        symbol="600519.SH",
        strategy_id="value",
        as_of=AS_OF,
        score=88.0,
        rank_percentile=0.95,
        eligible=True,
        strategy_version="v1",
        lineage=SnapshotLineage(),
        factor_snapshot=(),
    )
    store.write(SnapshotKind.FACTOR, AS_OF, [fr])
    store.write(SnapshotKind.STRATEGY, AS_OF, [sr])

    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "calibrate",
            "market-signal-readiness",
            "--as-of",
            AS_OF_STR,
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code != 0
