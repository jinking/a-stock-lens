"""迁移前的输入清单必须是一份**可逐字节比对**的证据。

这活为什么干：把数据从 CSV 搬到 Parquet + DuckDB 之前，先要有一份"迁移前的
样子"。没有它，迁移之后谁也证明不了结果没变。所以这份清单的每一个数字都必须
经得起复算，链路上的每一处"看起来像空"的地方都必须先被证明是空。

本文件钉住四条不许退让的性质：

1. CSV 的条数用 `csv` 解析器数，不是数换行——neodata 的单元格里带真实换行，
   按换行数会把一条记录算成两条。
2. 同一次输入算出的摘要稳定，且与标准库直接算出的 sha256 一致。
3. 损坏的 JSON 显式失败，绝不在清单里退化成 `records=0`；"读不动"和"是空的"
   是两个不同的事实。
4. 扫描只读：跑完之后每个被盘点文件的摘要与原样完全一致。

夹具用仓库自带的 `local_tmp` 而不是 `tmp_path`：本机 `tmp_path` 落在系统临时
根下，被运行环境拒绝（`PermissionError`），仓库的 `tests/conftest.py` 已就此
写明理由。计划示例里写的 `tmp_path` 在本机不可用，行为断言逐条保留。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import audit_research_baseline as audit
from scripts.audit_research_baseline import inventory

SNAPSHOT_ENVELOPE = {
    "kind": "UNIVERSE",
    "as_of": "2026-09-17T15:00:00+08:00",
    "records": [{"symbol": "600519.SH"}],
}


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _single(root: Path, relative: str) -> dict[str, object]:
    found = [item for item in inventory(root) if item["path"] == relative]
    assert len(found) == 1, f"expected exactly one entry for {relative}: {found}"
    return found[0]


# --- 1. CSV 计数 -------------------------------------------------------------


def test_multiline_cell_is_one_record(local_tmp: Path) -> None:
    """一条带换行的单元格仍然只是一条记录。"""
    _write(local_tmp, "data/raw/sample.csv", 'code,content\n1,"甲\n乙"\n')
    found = inventory(local_tmp)
    assert len(found) == 1
    assert found[0]["rows"] == 1
    assert found[0]["path"] == "data/raw/sample.csv"


def test_csv_columns_and_rows_are_the_real_parse(local_tmp: Path) -> None:
    """列名与行数来自解析，不是来自换行或文件名。"""
    _write(
        local_tmp,
        "data/raw/three.csv",
        'code,content\n1,"甲\n乙"\n2,"丙\n丁\n戊"\n3,己\n',
    )
    entry = _single(local_tmp, "data/raw/three.csv")
    assert entry["kind"] == "csv"
    assert entry["rows"] == 3
    assert entry["columns"] == ["code", "content"]
    assert entry["bytes"] == (local_tmp / "data/raw/three.csv").stat().st_size


# --- 2. 摘要稳定 -------------------------------------------------------------


def test_digest_is_stable_and_matches_stdlib(local_tmp: Path) -> None:
    """两次扫描给出同一个摘要，且等于标准库直接算出的 sha256。"""
    path = _write(local_tmp, "data/raw/sample.csv", "code,content\n1,甲\n")
    first = _single(local_tmp, "data/raw/sample.csv")
    second = _single(local_tmp, "data/raw/sample.csv")
    assert first == second
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert first["sha256"] == expected
    assert len(str(first["sha256"])) == 64


def test_entries_are_sorted_by_relative_path(local_tmp: Path) -> None:
    """清单顺序只由相对路径决定，与目录枚举顺序无关。"""
    _write(local_tmp, "data/raw/b.csv", "a\n1\n")
    _write(local_tmp, "data/raw/a.csv", "a\n1\n")
    _write(local_tmp, "data/raw/nested/c.csv", "a\n1\n")
    paths = [item["path"] for item in inventory(local_tmp)]
    assert paths == [
        "data/raw/a.csv",
        "data/raw/b.csv",
        "data/raw/nested/c.csv",
    ]


# --- 3. 损坏不是空 -----------------------------------------------------------


def test_broken_json_is_not_disguised_as_empty(local_tmp: Path) -> None:
    """坏文件必须点名报错，不能在清单里记成 0 条。"""
    broken = _write(local_tmp, "data/snapshots/UNIVERSE/2026-09-17.json", "{not json")
    with pytest.raises(audit.CorruptInput) as caught:
        inventory(local_tmp)
    assert str(broken.relative_to(local_tmp)) in str(caught.value)


def test_json_without_envelope_is_corrupt_not_empty(local_tmp: Path) -> None:
    """合法 JSON 但外壳字段不合约定，同样是损坏：`records` 必须是列表。"""
    _write(
        local_tmp,
        "data/snapshots/UNIVERSE/2026-09-17.json",
        json.dumps({"kind": "UNIVERSE", "records": 0}),
    )
    with pytest.raises(audit.CorruptInput, match="records"):
        inventory(local_tmp)


def test_job_manifest_without_runs_is_corrupt(local_tmp: Path) -> None:
    """Job 同日清单的 `runs` 必须是列表。"""
    _write(local_tmp, "var/jobs/2026-09-17.json", json.dumps({"as_of": "x"}))
    with pytest.raises(audit.CorruptInput, match="runs"):
        inventory(local_tmp)


def test_watchlist_record_must_be_an_object(local_tmp: Path) -> None:
    """Watchlist 一只标的一个文件，外壳必须是一个映射。"""
    _write(local_tmp, "data/watchlist/600519.SH.json", json.dumps(["600519.SH"]))
    with pytest.raises(audit.CorruptInput, match="mapping"):
        inventory(local_tmp)


def test_csv_without_header_is_corrupt(local_tmp: Path) -> None:
    """空 CSV 没有列名，报错而不是记成 0 行 0 列。"""
    _write(local_tmp, "data/raw/empty.csv", "")
    with pytest.raises(audit.CorruptInput, match="empty.csv"):
        inventory(local_tmp)


# --- 4. 只读与覆盖面 ---------------------------------------------------------


def test_running_the_inventory_changes_nothing(local_tmp: Path) -> None:
    """跑一次清单，被盘点的文件逐字节不变。"""
    _write(local_tmp, "data/raw/sample.csv", "code,content\n1,甲\n")
    _write(
        local_tmp,
        "data/snapshots/UNIVERSE/2026-09-17.json",
        json.dumps(SNAPSHOT_ENVELOPE),
    )
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(local_tmp.rglob("*"))
        if path.is_file()
    }
    inventory(local_tmp)
    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(local_tmp.rglob("*"))
        if path.is_file()
    }
    assert before == after


def test_watchlist_and_jobs_are_not_missed(local_tmp: Path) -> None:
    """`data/watchlist` 与 `var/jobs` 一个文件都不许漏。"""
    _write(local_tmp, "data/watchlist/600519.SH.json", json.dumps({"symbol": "x"}))
    _write(
        local_tmp, "var/jobs/2026-09-17.json", json.dumps({"as_of": "x", "runs": []})
    )
    _write(local_tmp, "configs/universe.yaml", "min_listing_days: 120\n")
    _write(local_tmp, "pyproject.toml", "[project]\nname = 'x'\n")
    paths = {item["path"] for item in inventory(local_tmp)}
    assert paths == {
        "data/watchlist/600519.SH.json",
        "var/jobs/2026-09-17.json",
        "configs/universe.yaml",
        "pyproject.toml",
    }


def test_json_entries_record_shape_and_count(local_tmp: Path) -> None:
    """JSON 记录外壳形态与条数，快照的条数就是 `records` 的长度。"""
    _write(
        local_tmp,
        "data/snapshots/UNIVERSE/2026-09-17.json",
        json.dumps(
            {
                "kind": "UNIVERSE",
                "as_of": "2026-09-17T15:00:00+08:00",
                "records": [{"symbol": "a"}, {"symbol": "b"}],
            }
        ),
    )
    entry = _single(local_tmp, "data/snapshots/UNIVERSE/2026-09-17.json")
    assert entry["kind"] == "json"
    assert entry["shape"] == "object"
    assert entry["records"] == 2
    assert entry["declared_as_of"] == "2026-09-17T15:00:00+08:00"


def test_non_whitelisted_files_are_not_read(local_tmp: Path) -> None:
    """白名单之外的东西（含凭证与 `.env`）不进清单。"""
    _write(local_tmp, ".env", "TOKEN=should-never-be-read\n")
    _write(local_tmp, "data/raw/derived.parquet", "not really parquet")
    _write(local_tmp, "data/snapshots/UNIVERSE/notes.txt", "not json")
    _write(local_tmp, "var/logs/2026-09-17.log", "log\n")
    paths = {item["path"] for item in inventory(local_tmp)}
    assert paths == set()


# --- 5. 并发写入 -----------------------------------------------------------------


def test_a_file_rewritten_during_the_scan_aborts_with_the_freeze_hint(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """扫描期间文件被改写：已算出的摘要不属于任何时点，必须中止。

    这里注入故障的是签名读取这个接缝（模拟"有人在扫描时改了文件"），被检验的
    行为——哈希、计数、外壳校验——全部真实执行。测试同时断言这个接缝确实被
    询问了两次，否则用例会因为"根本没检查"而假绿。
    """
    target = _write(local_tmp, "data/raw/sample.csv", "code,content\n1,甲\n")
    real = audit._stat_signature
    seen = {"count": 0}

    def drifting(path: Path) -> tuple[int, int]:
        signature = real(path)
        if path == target:
            seen["count"] += 1
            if seen["count"] >= 2:
                return (signature[0], signature[1] + 1)
        return signature

    monkeypatch.setattr(audit, "_stat_signature", drifting)
    with pytest.raises(audit.InputNotFrozen, match="固定输入后重试"):
        inventory(local_tmp)
    assert seen["count"] >= 2


def test_a_missing_root_fails_explicitly(local_tmp: Path) -> None:
    """根目录不存在就显式失败，不返回空清单冒充"没有文件"。"""
    with pytest.raises(audit.AuditRootMissing):
        inventory(local_tmp / "does-not-exist")


def test_a_missing_whitelisted_root_is_not_fatal(local_tmp: Path) -> None:
    """白名单根缺失是事实（本机 `data/watchlist` 就没有），不是错误。"""
    _write(local_tmp, "data/raw/sample.csv", "code,content\n1,甲\n")
    assert inventory(local_tmp) != ()


# --- 6. 命令行产物 -----------------------------------------------------------


def test_main_writes_only_the_output_file(local_tmp: Path) -> None:
    """`main()` 只写 `--output` 指的那个文件。"""
    _write(local_tmp, "data/raw/sample.csv", "code,content\n1,甲\n")
    output = local_tmp / "var/acceptance/run/input-inventory.json"
    before = {path for path in local_tmp.rglob("*") if path.is_file()}

    exit_code = audit.main(["--root", str(local_tmp), "--output", str(output)])

    assert exit_code == 0
    after = {path for path in local_tmp.rglob("*") if path.is_file()}
    assert after - before == {output}


def test_manifest_names_every_whitelisted_root_even_when_empty(local_tmp: Path) -> None:
    """清单要点名五类根目录：缺失的那类也在，`present=false`。

    这是本任务验收里"清单含 data/raw、data/snapshots、data/watchlist、
    var/jobs、configs"的落点：`data/watchlist` 在本机**不存在**，所以它不可能
    以文件条目出现；它出现在 `scanned_roots` 里，带 0 个文件与 `present=false`。
    """
    _write(local_tmp, "data/raw/sample.csv", "code,content\n1,甲\n")
    output = local_tmp / "var/acceptance/run/input-inventory.json"
    assert audit.main(["--root", str(local_tmp), "--output", str(output)]) == 0

    document = json.loads(output.read_text(encoding="utf-8"))
    roots = {item["root"]: item for item in document["scanned_roots"]}
    assert set(roots) == {
        "data/raw",
        "data/snapshots",
        "data/watchlist",
        "var/jobs",
        "configs",
    }
    assert roots["data/raw"]["files"] == 1
    assert roots["data/watchlist"]["files"] == 0
    assert roots["data/watchlist"]["present"] is False
    assert document["file_count"] == 1
    assert document["whitelist"]["single_files"] == ["pyproject.toml", "uv.lock"]
    # 单文件白名单声明与实际存在是两件事：夹具里这两个文件都不存在。
    assert [item["path"] for item in document["files"]] == ["data/raw/sample.csv"]


def test_manifest_entries_are_byte_for_byte_reproducible(local_tmp: Path) -> None:
    """除时间戳外，两次扫描的清单逐字节一致。"""
    _write(local_tmp, "data/raw/sample.csv", "code,content\n1,甲\n")
    first_output = local_tmp / "var/acceptance/a/input-inventory.json"
    second_output = local_tmp / "var/acceptance/b/input-inventory.json"
    assert audit.main(["--root", str(local_tmp), "--output", str(first_output)]) == 0
    assert audit.main(["--root", str(local_tmp), "--output", str(second_output)]) == 0

    first = json.loads(first_output.read_text(encoding="utf-8"))
    second = json.loads(second_output.read_text(encoding="utf-8"))
    del first["generated_at"], second["generated_at"]
    assert first == second


def test_main_reports_a_corrupt_input_as_a_failure(local_tmp: Path, capsys) -> None:
    """命令行下坏文件是"非零退出 + 点名报错"，不是静默成功。"""
    _write(local_tmp, "data/snapshots/UNIVERSE/2026-09-17.json", "{broken")
    output = local_tmp / "var/acceptance/run/input-inventory.json"
    assert audit.main(["--root", str(local_tmp), "--output", str(output)]) == 1
    assert not output.exists()
    assert "2026-09-17.json" in capsys.readouterr().err


def test_the_script_is_importable_as_a_package_module() -> None:
    """`scripts` 必须是包，否则计划里的 `from scripts...` 直接 ModuleNotFoundError。"""
    assert Path(audit.__file__).name == "audit_research_baseline.py"
