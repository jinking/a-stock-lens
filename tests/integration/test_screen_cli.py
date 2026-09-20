"""策略选股 CLI 命令集成测试（任务 3）。

验证：
- 基于存储快照只读筛选，绝不重算因子或扫描器；
- 混合策略快照的隔离与 TOP 截断；
- 缺失 STRATEGY 快照报错与提示；
- 策略不存在报错与提示；
- 低覆盖率告警（LOW_COVERAGE_WARNING_RATIO = 0.90）；
- 合格标的过滤与 --all-results 开关；
- --min-percentile 百分位过滤；
- 只读保证：快照、自选与作业目录完全不被修改。
"""

import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from click.testing import Result
from typer.testing import CliRunner

from astock_lens.cli.app import app
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult
from tests.support import strip_ansi

SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY = "2026-09-17"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=SHANGHAI)


def _strategy_result(
    symbol: str,
    *,
    strategy_id: str = "growth",
    strategy_version: str = "v1",
    score: float | None = None,
    percentile: float | None = None,
    eligible: bool = True,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        as_of=AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version=strategy_version),
        score=score,
        rank_percentile=percentile,
    )


def _invoke(
    snapshot_root: Path,
    watchlist_root: Path,
    job_root: Path,
    *args: str,
) -> Result:
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_WATCHLIST_ROOT": str(watchlist_root),
            "ASTOCK_JOB_ROOT": str(job_root),
        },
    )


def _tree_hashes(directory: Path) -> dict[str, str]:
    """计算目录下所有文件的相对路径和 SHA256，用于断言只读性。"""
    hashes: dict[str, str] = {}
    if not directory.exists():
        return hashes
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(directory))
            content = path.read_bytes()
            hashes[rel] = hashlib.sha256(content).hexdigest()
    return hashes


def test_screen_cli_help() -> None:
    """验证 screen 命令帮助信息与参数声明。"""
    runner = CliRunner()
    result = runner.invoke(app, ["screen", "--help"])
    assert result.exit_code == 0
    help_text = strip_ansi(result.stdout)
    assert "--as-of" in help_text
    assert "--top" in help_text
    assert "--min-percentile" in help_text
    assert "--all-results" in help_text


def test_screen_mixed_strategy_snapshot_top_limit(tmp_path: Path) -> None:
    """Step 1: 混合策略快照中只显示指定策略，且严格应用 top 截断。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    # 写入 growth 与 momentum 混合快照
    growth_results = [
        _strategy_result(
            "600000.SH", strategy_id="growth", score=80.0, percentile=0.95
        ),
        _strategy_result(
            "000001.SZ", strategy_id="growth", score=75.0, percentile=0.90
        ),
        _strategy_result(
            "600519.SH", strategy_id="growth", score=70.0, percentile=0.85
        ),
    ]
    momentum_results = [
        _strategy_result(
            "601398.SH", strategy_id="momentum", score=90.0, percentile=0.98
        ),
        _strategy_result(
            "300750.SZ", strategy_id="momentum", score=85.0, percentile=0.92
        ),
    ]
    store.write(SnapshotKind.STRATEGY, AS_OF, growth_results + momentum_results)

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        DAY,
        "--top",
        "2",
    )

    assert result.exit_code == 0, result.output
    assert f"growth — {DAY}" in result.stdout
    assert "coverage: total=3 eligible=3 scored=3 ranked=3" in result.stdout
    assert "showing: 2" in result.stdout

    # 包含排名前 2 的 growth 标的
    assert "600000.SH" in result.stdout
    assert "000001.SZ" in result.stdout
    # 被 top=2 截断的第 3 个 growth 标的不在输出中
    assert "600519.SH" not in result.stdout
    # momentum 标的绝不出现
    assert "601398.SH" not in result.stdout
    assert "300750.SZ" not in result.stdout


def test_screen_missing_snapshot(tmp_path: Path) -> None:
    """Step 2: 快照不存在时输出规范提示并返回非零。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        DAY,
    )

    assert result.exit_code != 0
    expected_message = (
        f"no STRATEGY snapshot for {DAY}\n"
        f"run `astock daily --as-of {DAY} --allow-incomplete` first"
    )
    assert expected_message in result.output


def test_screen_unknown_strategy(tmp_path: Path) -> None:
    """Step 3: 快照存在但没有所请求的策略结果时报错并退出。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.STRATEGY,
        AS_OF,
        [
            _strategy_result(
                "600000.SH", strategy_id="growth", score=80.0, percentile=0.95
            )
        ],
    )

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "foo",
        "--as-of",
        DAY,
    )

    assert result.exit_code != 0
    assert f"strategy 'foo' has no stored results for {DAY}" in result.output


def test_screen_low_coverage_warning(tmp_path: Path) -> None:
    """Step 5: scored / total < 0.90 时打印低覆盖率告警。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    # 5 个结果中只有 4 个有分数：4 / 5 = 0.80 < 0.90
    results = [
        _strategy_result("S1", score=80.0, percentile=0.95),
        _strategy_result("S2", score=75.0, percentile=0.90),
        _strategy_result("S3", score=70.0, percentile=0.85),
        _strategy_result("S4", score=65.0, percentile=0.80),
        _strategy_result("S5", score=None, percentile=None),
    ]
    store.write(SnapshotKind.STRATEGY, AS_OF, results)

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        DAY,
        "--all-results",
    )

    assert result.exit_code == 0, result.output
    assert (
        "coverage warning: only 4/5 stored results have a score; "
        "ranking reflects available data" in result.stdout
    )


def test_screen_high_coverage_no_warning(tmp_path: Path) -> None:
    """覆盖率 >= 0.90 时不打印告警。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    results = [
        _strategy_result("S1", score=80.0, percentile=0.95),
        _strategy_result("S2", score=75.0, percentile=0.90),
    ]
    store.write(SnapshotKind.STRATEGY, AS_OF, results)

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        DAY,
    )

    assert result.exit_code == 0, result.output
    assert "coverage warning" not in result.stdout


def test_screen_eligible_filter_and_all_results_flag(tmp_path: Path) -> None:
    """默认仅显示合格标的，--all-results 包含不合格标的。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    results = [
        _strategy_result("AAA", score=80.0, percentile=0.95, eligible=True),
        _strategy_result("BBB", score=90.0, percentile=0.99, eligible=False),
    ]
    store.write(SnapshotKind.STRATEGY, AS_OF, results)

    # 默认 eligible-only
    res_default = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        DAY,
    )
    assert res_default.exit_code == 0
    assert "showing: 1" in res_default.stdout
    assert "AAA" in res_default.stdout
    assert "BBB" not in res_default.stdout

    # --all-results
    res_all = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        DAY,
        "--all-results",
    )
    assert res_all.exit_code == 0
    assert "showing: 2" in res_all.stdout
    assert "AAA" in res_all.stdout
    assert "BBB" in res_all.stdout


def test_screen_min_percentile_filter(tmp_path: Path) -> None:
    """--min-percentile 过滤低于阈值的标的。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    results = [
        _strategy_result("AAA", score=80.0, percentile=0.96),
        _strategy_result("BBB", score=75.0, percentile=0.94),
        _strategy_result("CCC", score=70.0, percentile=0.80),
    ]
    store.write(SnapshotKind.STRATEGY, AS_OF, results)

    res = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        DAY,
        "--min-percentile",
        "0.95",
    )
    assert res.exit_code == 0
    assert "showing: 1" in res.stdout
    assert "AAA" in res.stdout
    assert "BBB" not in res.stdout
    assert "CCC" not in res.stdout


def test_screen_read_only_guarantee(tmp_path: Path) -> None:
    """Step 6: 只读保证——执行前后快照、自选与作业目录完全无变化。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    snapshot_root.mkdir(parents=True)
    watchlist_root.mkdir(parents=True)
    job_root.mkdir(parents=True)

    # 放置哨兵文件
    (snapshot_root / "SENTINEL.txt").write_text("snapshot sentinel", encoding="utf-8")
    (watchlist_root / "SENTINEL.txt").write_text("watchlist sentinel", encoding="utf-8")
    (job_root / "SENTINEL.txt").write_text("job sentinel", encoding="utf-8")

    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.STRATEGY,
        AS_OF,
        [_strategy_result("600000.SH", score=80.0, percentile=0.95)],
    )

    # 记录执行前哈希
    hashes_snapshot_before = _tree_hashes(snapshot_root)
    hashes_watchlist_before = _tree_hashes(watchlist_root)
    hashes_job_before = _tree_hashes(job_root)

    # 执行 screen
    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        DAY,
    )
    assert result.exit_code == 0

    # 验证执行后哈希完全一致
    assert _tree_hashes(snapshot_root) == hashes_snapshot_before
    assert _tree_hashes(watchlist_root) == hashes_watchlist_before
    assert _tree_hashes(job_root) == hashes_job_before
