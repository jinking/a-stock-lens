"""迁移前的输入与正式状态清单。

**这活为什么干。** 把数据从 CSV 搬到 Parquet + DuckDB 之前，必须先留下一份
**可逐字节比对**的基线。没有它，迁移之后没有任何人能证明"结果没变"——最多只能
证明"这次跑出来的东西看起来还行"。所以本脚本只做一件事：把白名单内的每个文件按
相对路径稳定排序，逐个记录 `bytes` 与 `sha256`；CSV 额外记录解析出来的真实行数与
列名，JSON 额外记录外壳形态与条数；最后原样落成一份 JSON 清单。

**三条不许违反的规则。**

1. **只读。** 脚本只写 `--output` 指向的那一个文件，绝不碰任何被盘点的输入。
2. **损坏不是空。** 文件读不动、JSON 解析不了、外壳字段不合约定，一律显式抛出并
   把路径写进错误信息，绝不在清单里退化成 `rows=0` / `records=0`。"读不动"和
   "是空的"是两个不同的事实，把它们合并会让一份损坏的证据看起来像一份干净的。
3. **输入必须冻结。** 每个文件读前读后各取一次 `(size, mtime_ns)`；不一致说明有人
   在扫描期间改了文件，此时已经算出的 sha256 不属于任何一个时点，必须中止并提示
   "固定输入后重试"。

**为什么用 `csv` 解析器数行。** neodata 的单元格里带真实换行，按 `\\n` 数会把
一条记录算成两条，基线数字随之虚高。计数必须来自解析，不能来自字节。

**为什么缺失的白名单根不算错误。** `data/watchlist/` 在本机**不存在**（还没有
tracked 标的，目录也随 `.gitignore` 不进库）。把它当成错误会逼着脚本要么伪造一个
空目录、要么拒绝出清单，两者都会让基线失真。正确做法是把它作为"声明过、本次为空"
记进 `scanned_roots`，让读者一眼看到它被考虑过、且当时确实没有文件。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

ARTIFACT = "research-baseline-input-inventory"

# 白名单：只盘点这些东西。凭证、`.env`、Parquet、日志一律不读也不记。
CSV_ROOTS: tuple[str, ...] = ("data/raw",)
JSON_ROOTS: tuple[tuple[str, str], ...] = (
    ("data/snapshots", "snapshot"),
    ("data/watchlist", "watchlist"),
    ("var/jobs", "job"),
)
YAML_ROOTS: tuple[str, ...] = ("configs",)
SINGLE_FILES: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", "toml"),
    ("uv.lock", "uv-lock"),
)

CHUNK_BYTES = 1024 * 1024
FREEZE_HINT = "固定输入后重试"


class AuditRootMissing(RuntimeError):
    """扫描根不存在。这是显式失败，不是"没有文件"。"""


class CorruptInput(RuntimeError):
    """文件损坏或外壳不合约定。损坏不是空，必须点名报错。"""


class InputNotFrozen(RuntimeError):
    """扫描期间文件被改写，已算出的摘要不再属于任何一个时点。"""


def digest_file(path: Path) -> str:
    """流式计算一个文件的 SHA-256，不把整个文件读进内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _stat_signature(path: Path) -> tuple[int, int]:
    """`(size, mtime_ns)`：判断文件在扫描期间有没有被动过的最小充分签名。"""
    info = path.stat()
    return (info.st_size, info.st_mtime_ns)


def _parse_csv(path: Path) -> tuple[int, tuple[str, ...]]:
    """返回 `(数据行数, 列名)`，行数来自解析而不是数换行。

    没有表头的 CSV（含 0 字节文件）是"读不动"，不是"0 行"。
    """
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            try:
                header = next(reader)
            except StopIteration:
                raise CorruptInput(
                    f"{path}: CSV has no header row, so its columns are unknown; "
                    "an unreadable file is not an empty one"
                ) from None
            rows = sum(1 for _ in reader)
    except UnicodeDecodeError as failure:
        raise CorruptInput(f"{path}: CSV is not valid UTF-8 ({failure})") from failure
    except OSError as failure:
        raise CorruptInput(f"{path}: CSV cannot be read ({failure})") from failure
    return rows, tuple(header)


def _inspect_json(path: Path, envelope: str) -> tuple[str, int, str | None]:
    """校验 JSON 外壳并返回 `(形态, 条数, 外壳声明的 as_of)`。

    外壳约定与仓库里三种 Store 各自的读契约完全一致，避免审计脚本自己发明一套
    更松或更严的规矩：

    * `snapshot`：对象，且 `records` 是列表（`JsonSnapshotStore.read`）；
    * `job`：对象，且 `runs` 是列表（`JsonJobStore.runs`）；
    * `watchlist`：对象，一只标的一个文件（`JsonWatchlistStore.read`）。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as failure:
        raise CorruptInput(f"{path}: JSON is not valid UTF-8 ({failure})") from failure
    except OSError as failure:
        raise CorruptInput(f"{path}: JSON cannot be read ({failure})") from failure

    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError as failure:
        raise CorruptInput(
            f"{path}: invalid JSON ({failure}); a broken file is not an empty one"
        ) from failure

    if not isinstance(payload, dict):
        raise CorruptInput(
            f"{path}: {envelope} record is not a mapping, it is {type(payload).__name__}"
        )

    declared_as_of = payload.get("as_of")
    if declared_as_of is not None and not isinstance(declared_as_of, str):
        raise CorruptInput(f"{path}: as_of is not a string: {declared_as_of!r}")

    if envelope == "watchlist":
        return "object", 1, declared_as_of

    field = "records" if envelope == "snapshot" else "runs"
    items = payload.get(field)
    if not isinstance(items, list):
        raise CorruptInput(
            f"{path}: {envelope} envelope carries no {field} list, "
            f"it has {sorted(payload)!r}"
        )
    return "object", len(items), declared_as_of


def _collect(root: Path) -> tuple[tuple[str, str, str, str | None], ...]:
    """按相对路径稳定排序的 `(相对路径, 记录形态, 白名单根, JSON 外壳)`。"""
    found: list[tuple[str, str, str, str | None]] = []
    for directory in CSV_ROOTS:
        found.extend(
            (_relative(root, path), "csv", directory, None)
            for path in _rglob(root, directory, "*.csv")
        )
    for directory, envelope in JSON_ROOTS:
        found.extend(
            (_relative(root, path), "json", directory, envelope)
            for path in _rglob(root, directory, "*.json")
        )
    for directory in YAML_ROOTS:
        found.extend(
            (_relative(root, path), "yaml", directory, None)
            for path in _rglob(root, directory, "*.yaml")
        )
    found.extend(
        (relative, kind, ".", None)
        for relative, kind in SINGLE_FILES
        if (root / relative).is_file()
    )
    found.sort(key=lambda item: item[0])
    return tuple(found)


def _rglob(root: Path, directory: str, pattern: str) -> tuple[Path, ...]:
    """递归枚举一个白名单根；根不存在时返回空，不伪造目录。"""
    base = root / directory
    if not base.is_dir():
        return ()
    return tuple(sorted(base.rglob(pattern)))


def _relative(root: Path, path: Path) -> str:
    """相对路径一律用 POSIX 分隔符，跨平台比较才有意义。"""
    return path.relative_to(root).as_posix()


def _inspect(
    root: Path,
    relative: str,
    kind: str,
    root_label: str,
    envelope: str | None,
) -> dict[str, object]:
    """盘点一个文件；读前读后签名不一致就中止。"""
    path = root / relative
    before = _stat_signature(path)
    entry: dict[str, object] = {
        "path": relative,
        "root": root_label,
        "kind": kind,
        "bytes": before[0],
        "sha256": digest_file(path),
    }
    if kind == "csv":
        rows, columns = _parse_csv(path)
        entry["rows"] = rows
        entry["columns"] = list(columns)
    elif kind == "json":
        assert envelope is not None  # 由 _collect 保证
        shape, count, declared_as_of = _inspect_json(path, envelope)
        entry["shape"] = shape
        entry["records"] = count
        entry["declared_as_of"] = declared_as_of

    after = _stat_signature(path)
    if after != before:
        raise InputNotFrozen(
            f"{path}: changed while it was being scanned "
            f"({before[0]}B/mtime {before[1]} -> {after[0]}B/mtime {after[1]}); "
            f"a digest measured across a write belongs to no point in time — "
            f"{FREEZE_HINT}"
        )
    return entry


def inventory(root: Path) -> tuple[dict[str, object], ...]:
    """白名单内每个文件一条记录，按相对路径稳定排序。

    缺失的白名单根不进入结果，也不报错——它没有文件，就没有条目；它"被考虑过"
    这件事由 `scanned_roots` 记在清单头部。根目录本身不存在则是显式失败。
    """
    if not root.is_dir():
        raise AuditRootMissing(
            f"scan root does not exist: {root}; refusing to report an empty "
            "inventory for a directory that is not there"
        )
    return tuple(_inspect(root, *item) for item in _collect(root))


def scanned_roots(root: Path) -> tuple[dict[str, object], ...]:
    """每个白名单根的声明与实况：`present`、文件数、总字节。

    这一节是清单里唯一会点名**空根**的地方，也是"清单含 data/watchlist"的落点：
    本机该目录不存在，它只能以 `present=false, files=0` 的形式被如实记录。
    """
    entries = _collect(root)
    totals: dict[str, list[int]] = {}
    for relative, _kind, label, _envelope in entries:
        bucket = totals.setdefault(label, [0, 0])
        bucket[0] += 1
        bucket[1] += (root / relative).stat().st_size

    declared: list[tuple[str, str]] = (
        [(directory, "*.csv") for directory in CSV_ROOTS]
        + [(directory, "*.json") for directory, _ in JSON_ROOTS]
        + [(directory, "*.yaml") for directory in YAML_ROOTS]
    )
    return tuple(
        {
            "root": directory,
            "pattern": pattern,
            "present": (root / directory).is_dir(),
            "files": totals.get(directory, [0, 0])[0],
            "bytes": totals.get(directory, [0, 0])[1],
        }
        for directory, pattern in declared
    )


def build_document(root: Path) -> dict[str, object]:
    """装配清单文档；只有 `generated_at` 不是输入的纯函数。"""
    entries = inventory(root)
    return {
        "artifact": ARTIFACT,
        "generated_at": datetime.now(UTC).isoformat(),
        "root": str(root.resolve()),
        "whitelist": {
            "csv_roots": list(CSV_ROOTS),
            "json_roots": [directory for directory, _ in JSON_ROOTS],
            "yaml_roots": list(YAML_ROOTS),
            "single_files": [relative for relative, _ in SINGLE_FILES],
        },
        "scanned_roots": [dict(item) for item in scanned_roots(root)],
        "file_count": len(entries),
        "total_bytes": sum(int(item["bytes"]) for item in entries),
        "files": [dict(item) for item in entries],
    }


def _report(document: dict[str, object]) -> None:
    """把清单头部摘要打到 stdout，让命令行输出本身就是可读的验收证据。"""
    print(f"inventory written: {document['artifact']}")
    roots = document["scanned_roots"]
    assert isinstance(roots, list)
    for item in roots:
        print(
            f"  {item['root']} ({item['pattern']}): {item['files']} files, "
            f"{item['bytes']} bytes, present={item['present']}"
        )
    print("  pyproject.toml / uv.lock: declared single files")
    print(f"total: {document['file_count']} files, {document['total_bytes']} bytes")


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：只写 `--output`，其余一切只读。"""
    parser = argparse.ArgumentParser(
        prog="audit_research_baseline.py",
        description=(
            "盘点研究基线的输入与正式状态（只读，落一份可逐字节比对的 JSON 清单）"
        ),
    )
    parser.add_argument("--root", type=Path, default=Path("."), help="仓库根目录")
    parser.add_argument("--output", type=Path, required=True, help="清单输出路径")
    options = parser.parse_args(argv)

    try:
        document = build_document(options.root)
    except (AuditRootMissing, CorruptInput, InputNotFrozen) as failure:
        print(f"inventory failed: {failure}", file=sys.stderr)
        return 1

    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"inventory written: {options.output}")
    _report(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
