"""`astock qualified` CLI 命令集成测试（Plan A 任务 2）。

验证：
- 只读已存储的 FACTOR / STRATEGY 快照 + 已批准资格配置，展示双门槛通过结果；
- 缺 FACTOR / STRATEGY 快照时非零退出并给出规范提示；
- 资格配置非法（ASTOCK_QUALIFICATION_DIR）时 fail-closed，绝不降级为零合格正常屏；
- 请求的策略不在已批准 qualifiers 中时显式 not-found 报错；
- Dividend 零合格：退出 0、`qualified: 0`、显式数据健康 warning；
- 只读保证：Snapshot / Watchlist / Job 三个根目录前后指纹完全一致。

资格配置一律从仓库 `configs/qualifications` 复制到临时目录（已批准阈值，
测试不发明任何数值），再通过 `ASTOCK_QUALIFICATION_DIR` 注入。
"""

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner, Result

from astock_lens.cli.app import app
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import DataStatus, SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult
from tests.support import strip_ansi

SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY = "2026-09-17"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=SHANGHAI)

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_QUALIFICATION_DIR = REPO_ROOT / "configs" / "qualifications"

# growth 已批准绝对门槛：net_profit_parent_yoy>=15、revenue_yoy>=5、roe_ttm>=8
GROWTH_FACTOR_SEEDS: dict[str, dict[str, float]] = {
    # 绝对门槛通过
    "600000.SH": {"net_profit_parent_yoy": 20.0, "revenue_yoy": 8.0, "roe_ttm": 9.0},
    # 绝对门槛不通过：净利同比 10 < 15
    "600001.SH": {"net_profit_parent_yoy": 10.0, "revenue_yoy": 8.0, "roe_ttm": 9.0},
    # 绝对门槛通过
    "600002.SH": {"net_profit_parent_yoy": 25.0, "revenue_yoy": 12.0, "roe_ttm": 10.0},
    # 绝对门槛通过
    "600003.SH": {"net_profit_parent_yoy": 30.0, "revenue_yoy": 15.0, "roe_ttm": 11.0},
}


def _factor(symbol: str, name: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _strategy_result(
    symbol: str,
    *,
    strategy_id: str = "growth",
    score: float | None = 80.0,
    percentile: float | None = 0.95,
    eligible: bool = True,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
        rank_percentile=percentile,
    )


def _qualification_dir(tmp_path: Path) -> Path:
    """把仓库里已批准的资格配置复制到临时目录，测试不改任何阈值。"""
    target = tmp_path / "qualifications"
    shutil.copytree(CANONICAL_QUALIFICATION_DIR, target)
    return target


def _seed_growth_snapshots(snapshot_root: Path) -> None:
    """播种 growth 双门槛场景：600003/600000 双通过，其余各缺一门。"""
    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.FACTOR,
        AS_OF,
        tuple(
            _factor(symbol, name, value)
            for symbol, factors in GROWTH_FACTOR_SEEDS.items()
            for name, value in factors.items()
        ),
    )
    store.write(
        SnapshotKind.STRATEGY,
        AS_OF,
        (
            # percentile 0.95 通过 + 绝对门槛通过 → 双通过
            _strategy_result("600000.SH", percentile=0.95, score=80.0),
            # percentile 0.95 通过 + 绝对门槛失败
            _strategy_result("600001.SH", percentile=0.95, score=75.0),
            # percentile 0.50 失败 + 绝对门槛通过
            _strategy_result("600002.SH", percentile=0.50, score=70.0),
            # percentile 0.99 通过 + 绝对门槛通过 → 双通过（排第一）
            _strategy_result("600003.SH", percentile=0.99, score=88.0),
            # 其他策略：隔离性验证，绝不出现
            _strategy_result("601398.SH", strategy_id="momentum", percentile=0.99),
        ),
    )


def _invoke(
    snapshot_root: Path,
    watchlist_root: Path,
    job_root: Path,
    qualification_dir: Path,
    *args: str,
) -> Result:
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_WATCHLIST_ROOT": str(watchlist_root),
            "ASTOCK_JOB_ROOT": str(job_root),
            "ASTOCK_QUALIFICATION_DIR": str(qualification_dir),
        },
    )


def _tree_fingerprint(directory: Path) -> dict[str, str]:
    """文件相对路径 → 内容 SHA256；目录相对路径 → 占位符。

    同时覆盖「内容被改」「新增/删除文件」「新增/删除目录」三种变化。
    """
    entries: dict[str, str] = {}
    if not directory.exists():
        return entries
    for path in sorted(directory.rglob("*")):
        rel = path.relative_to(directory).as_posix()
        if path.is_file():
            entries[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            entries[rel] = "directory"
    return entries


def test_qualified_cli_help() -> None:
    """帮助信息声明 --as-of 与 --top。"""
    result = CliRunner().invoke(app, ["qualified", "--help"])
    assert result.exit_code == 0
    help_text = strip_ansi(result.stdout)
    assert "--as-of" in help_text
    assert "--top" in help_text


def test_qualified_only_dual_pass_displayed(tmp_path: Path) -> None:
    """Step 1: 只展示双门槛通过的行；覆盖度计数完整可见。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)
    _seed_growth_snapshots(snapshot_root)

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "growth",
        "--as-of",
        DAY,
    )

    assert result.exit_code == 0, result.output
    out = strip_ansi(result.stdout)
    assert f"growth — {DAY}" in out
    assert (
        "coverage: eligible=4 ranked=4 percentile_pass=3 absolute_pass=3 "
        "qualified=2" in out
    )
    assert "qualified: 2" in out
    assert "showing: 2" in out
    # 双通过的两行，按 rank_percentile DESC 排序
    assert "1  600003.SH  score=88.00  percentile=0.9900" in out
    assert "2  600000.SH  score=80.00  percentile=0.9500" in out
    assert out.index("600003.SH") < out.index("600000.SH")
    # 单门槛通过与其他策略的标的不出现
    assert "600001.SH" not in out
    assert "600002.SH" not in out
    assert "601398.SH" not in out


def test_qualified_top_limit_truncates_items_not_coverage(tmp_path: Path) -> None:
    """--top 截断展示行数，但不改变 limit 之前计算的覆盖度。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)
    _seed_growth_snapshots(snapshot_root)

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "growth",
        "--as-of",
        DAY,
        "--top",
        "1",
    )

    assert result.exit_code == 0, result.output
    out = strip_ansi(result.stdout)
    assert "showing: 1" in out
    assert "600003.SH" in out
    assert "600000.SH" not in out
    # 覆盖度仍按全量计算
    assert "qualified=2" in out
    assert "qualified: 2" in out


def test_qualified_missing_factor_snapshot(tmp_path: Path) -> None:
    """Step 2: 缺 FACTOR 快照 → 非零退出 + 规范提示。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "growth",
        "--as-of",
        DAY,
    )

    assert result.exit_code != 0
    assert f"no FACTOR snapshot for {DAY}" in strip_ansi(result.output)


def test_qualified_missing_strategy_snapshot(tmp_path: Path) -> None:
    """Step 3: 缺 STRATEGY 快照 → 非零退出 + 规范提示。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)

    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.FACTOR,
        AS_OF,
        (_factor("600000.SH", "roe_ttm", 9.0),),
    )

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "growth",
        "--as-of",
        DAY,
    )

    assert result.exit_code != 0
    assert f"no STRATEGY snapshot for {DAY}" in strip_ansi(result.output)


def test_qualified_invalid_config_fails_closed(tmp_path: Path) -> None:
    """Step 4: 非法资格配置必须报错退出，绝不打印零结果正常屏。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)
    _seed_growth_snapshots(snapshot_root)

    # 未批准的因子名 → load_canonical_qualifiers 抛 QualificationConfigInvalid
    (qualification_dir / "growth.yaml").write_text(
        "strategy_id: growth\n"
        "version: v1\n"
        "thresholds:\n"
        "  not_an_approved_factor:\n"
        "    min: 1.0\n",
        encoding="utf-8",
    )

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "growth",
        "--as-of",
        DAY,
    )

    assert result.exit_code != 0
    out = strip_ansi(result.output)
    assert "qualification configuration is invalid" in out
    assert "not_an_approved_factor" in out
    # 绝不降级为正常的零合格屏
    assert "qualified:" not in out
    assert "showing:" not in out


def test_qualified_unknown_strategy_fails_loudly(tmp_path: Path) -> None:
    """请求的策略不在已批准 qualifiers 中：显式 not-found，不打印正常表格。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)
    _seed_growth_snapshots(snapshot_root)

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "foo",
        "--as-of",
        DAY,
    )

    assert result.exit_code != 0
    out = strip_ansi(result.output)
    assert "foo" in out
    assert "no approved qualification rule" in out
    assert "qualified:" not in out
    assert "showing:" not in out


def test_qualified_dividend_zero_result_warns(tmp_path: Path) -> None:
    """Step 5: Dividend 零合格 → 退出 0、`qualified: 0`、显式 warning。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)

    store = JsonSnapshotStore(snapshot_root)
    # 现实缺口：股息率因子没有上游数据，快照里没有 dividend_yield_ttm 记录
    store.write(
        SnapshotKind.FACTOR,
        AS_OF,
        (_factor("000001.SZ", "roe_ttm", 9.0),),
    )
    store.write(
        SnapshotKind.STRATEGY,
        AS_OF,
        (_strategy_result("000001.SZ", strategy_id="dividend", percentile=0.95),),
    )

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "dividend",
        "--as-of",
        DAY,
    )

    assert result.exit_code == 0, result.output
    out = strip_ansi(result.output)
    assert "qualified: 0" in out
    assert "warning:" in out
    assert "无任何双门槛通过标的" in out
    assert "showing: 0" in out


def test_qualified_read_only_guarantee(tmp_path: Path) -> None:
    """Step 8: 只读证明——三个根目录的文件与目录集合前后完全一致。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)

    watchlist_root.mkdir(parents=True)
    job_root.mkdir(parents=True)
    (snapshot_root / "SENTINEL.txt").parent.mkdir(parents=True, exist_ok=True)
    (snapshot_root / "SENTINEL.txt").write_text("snapshot sentinel", encoding="utf-8")
    (watchlist_root / "SENTINEL.txt").write_text("watchlist sentinel", encoding="utf-8")
    (job_root / "SENTINEL.txt").write_text("job sentinel", encoding="utf-8")
    _seed_growth_snapshots(snapshot_root)

    before = (
        _tree_fingerprint(snapshot_root),
        _tree_fingerprint(watchlist_root),
        _tree_fingerprint(job_root),
    )

    result = _invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "growth",
        "--as-of",
        DAY,
    )
    assert result.exit_code == 0, result.output

    after = (
        _tree_fingerprint(snapshot_root),
        _tree_fingerprint(watchlist_root),
        _tree_fingerprint(job_root),
    )
    # 内容哈希、文件集合、目录集合全部一致：没有修改，也没有新建
    assert after == before
