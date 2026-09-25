"""正式快照的写入权只属于 `daily`。

本文件钉住两个 P0 问题：

1. `astock factors compute` 走的是 first slice 那条旧链路，它会写 FACTOR 与
   CANDIDATE 两份正式快照。于是"只算因子"的只读命令会覆盖当天已经落好的正式
   候选结果——一个哨兵值就能证明这件事。
2. `astock scan` 同样会写正式快照。它只跑一个 Scanner，却能让当天由 `daily`
   写出的完整候选结果消失，读者无从知道哪一份才是当天的正式产物。

目标行为写在计划 `a-stock-lens-core-hardening-plan.md` Task 1 / Task 3：
`factors compute` 与 `strategy run` 是纯计算，`scan` 是预览，`daily` 是唯一
正式 Snapshot writer。测试先失败，实现随后跟上。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from click.testing import Result
from typer.testing import CliRunner

from astock_lens.cli.app import app
from astock_lens.domain.enums import SnapshotKind

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
DAY = "2026-09-04"
LONG_DATASET = "daily_bars_long"

CANDIDATE_JSON = Path(SnapshotKind.CANDIDATE.value) / f"{DAY}.json"

SENTINEL_MARKER = "sentinel-candidate-written-by-another-run"


def _snapshot_root(local_tmp: Path) -> Path:
    return local_tmp / "snapshots"


def _invoke(snapshot_root: Path, *args: str) -> Result:
    """Run the CLI against the fixture data and a scratch snapshot root."""
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_CSV_ROOT": str(CSV_ROOT),
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_JOB_ROOT": str(snapshot_root.parent / "jobs"),
            "ASTOCK_WATCHLIST_ROOT": str(snapshot_root.parent / "watchlist"),
            "ASTOCK_DATASET": LONG_DATASET,
        },
    )


def _write_sentinel(snapshot_root: Path) -> str:
    """落一份当天已经存在的正式 CANDIDATE，内容一眼可辨。"""
    path = snapshot_root / CANDIDATE_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": SnapshotKind.CANDIDATE.value,
        "as_of": datetime(2026, 9, 4, 15, 0, tzinfo=UTC).isoformat(),
        "records": [{"symbol": "600519.SH", "marker": SENTINEL_MARKER}],
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path.read_text(encoding="utf-8")


def _candidate_text(snapshot_root: Path) -> str:
    return (snapshot_root / CANDIDATE_JSON).read_text(encoding="utf-8")


def _written_snapshots(snapshot_root: Path) -> tuple[str, ...]:
    """每份正式快照文件，按相对路径排序。"""
    if not snapshot_root.is_dir():
        return ()
    return tuple(
        sorted(
            str(path.relative_to(snapshot_root))
            for path in snapshot_root.rglob("*.json")
        )
    )


def _snapshot_texts(snapshot_root: Path) -> dict[str, str]:
    """正式快照目录的完整内容，用来证明一次命令之后什么都没被动过。"""
    if not snapshot_root.is_dir():
        return {}
    return {
        str(path.relative_to(snapshot_root)): path.read_text(encoding="utf-8")
        for path in sorted(snapshot_root.rglob("*.json"))
    }


# --- factors compute ---------------------------------------------------------


def test_factors_compute_does_not_touch_the_formal_candidate_snapshot(
    local_tmp: Path,
) -> None:
    """计算因子不是一次正式运行，不能重写当天的正式候选结果。"""
    root = _snapshot_root(local_tmp)
    sentinel = _write_sentinel(root)

    result = _invoke(root, "factors", "compute", "--as-of", DAY)

    assert result.exit_code == 0, result.output
    assert _candidate_text(root) == sentinel


# --- strategy run ------------------------------------------------------------

# 「不写正式快照的命令」三行：行序与原用例一致，label 即原测试名，
# 原 docstring 逐字保留为行注释。族横跨三个命令小节，落在中间的
# `# --- strategy run ---` 小节里，三个小节标题就都还有内容。
# 列 = label, args：
#   - `args` 逐行保留原 `_invoke(root, ...)` 的命令行参数；
#   - 每行各用 `local_tmp/<label>` 作快照根（原用例各自拿一份新的 `local_tmp`），
#     行与行不共享现场，一行落下快照不会误伤邻行。
NON_PERSISTENT_COMMAND_CASES = (
    # test_factors_compute_writes_no_formal_snapshot_at_all:
    #   目标状态：`factors compute` 只计算，不落任何正式 Snapshot。
    (
        "test_factors_compute_writes_no_formal_snapshot_at_all",
        ("factors", "compute", "--as-of", DAY),
    ),
    # test_strategy_run_writes_no_formal_snapshot:
    #   跑一个 Scanner 是纯计算：它没有资格写当天的 STRATEGY/CANDIDATE。
    (
        "test_strategy_run_writes_no_formal_snapshot",
        ("strategy", "run", "momentum", "--as-of", DAY),
    ),
    # test_scan_writes_no_formal_snapshot_at_all:
    #   目标状态：`scan` 是 non-persistent preview。
    (
        "test_scan_writes_no_formal_snapshot_at_all",
        ("scan", "--as-of", DAY),
    ),
)


def test_read_only_commands_write_no_formal_snapshot(local_tmp: Path) -> None:
    """factors compute / strategy run / scan 都不落任何正式 Snapshot。

    原 3 条「writes_no_formal_snapshot」用例逐条成行；循环只收集，
    断言在表外一次完成，失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, args in NON_PERSISTENT_COMMAND_CASES:
        root = _snapshot_root(local_tmp / label)
        result = _invoke(root, *args)
        if result.exit_code != 0:
            wrong.append(
                f"{label}: exit_code 为 {result.exit_code}，输出 {result.output!r}"
            )
        written = _written_snapshots(root)
        if written != ():
            wrong.append(f"{label}: 落下了正式快照 {written!r}")
    assert not wrong, "只读命令不得写正式快照:\n" + "\n".join(wrong)


# --- scan --------------------------------------------------------------------


def test_scan_leaves_every_formal_snapshot_untouched(local_tmp: Path) -> None:
    """`daily` 写下的正式快照，不能被一次预览改动哪怕一个字节。"""
    root = _snapshot_root(local_tmp)

    daily = _invoke(root, "daily", "--as-of", DAY, "--allow-incomplete")
    assert daily.exit_code == 0, daily.output
    formal = _snapshot_texts(root)
    assert formal, "前置条件：daily 必须真的写过正式快照"

    after = _invoke(root, "scan", "--as-of", DAY)

    assert after.exit_code == 0, after.output
    assert _snapshot_texts(root) == formal


def test_scan_does_not_replace_a_formal_candidate_snapshot(local_tmp: Path) -> None:
    """哨兵法：只要 `scan` 真的写了正式快照，这份哨兵就不可能是原样。

    本夹具上预览与 `daily` 恰好算出同样的候选内容，所以"内容没变"不能证明
    任何事。哨兵是任何人都不会产出的内容，它还在原地就意味着没人动过这个文件。
    """
    root = _snapshot_root(local_tmp)
    sentinel = _write_sentinel(root)

    result = _invoke(root, "scan", "--as-of", DAY)

    assert result.exit_code == 0, result.output
    assert _candidate_text(root) == sentinel
