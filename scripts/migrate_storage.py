"""一次性存储迁移：Raw CSV / JSON 业务状态 → Normalized Parquet + DuckDB。

按 `docs/STORAGE.md` 的四层裁决把已经落地的数据搬进 Parquet 与 DuckDB，并当场做
第 5 条要求的四关校验：

1. 结构：Parquet 的列集合与规范模型字段一一对应；
2. 计数：逐数据集行数与内存中的规范记录数一致；
3. 主键：规范主键在 Parquet 里唯一；
4. 双读：把 Parquet 读回来重建成规范模型，与内存记录逐条做摘要比对。

另外单独查一遍"零值有没有凭空出现"：源里是 `None` 的格子，落盘后不得变成 `0`。

明确不做的事：

- 不删除、不重写任何 Raw CSV。Raw 层在 DuckDB 里只建**视图**（`read_csv`），
  不复制一份会漂移的副本；
- 不新增第二套归一化语义：归一化全部调用 `astock_lens.pipelines.stages.normalize_stage`；
- 不依赖 pyarrow：Parquet 的读写都由 DuckDB 完成（本机 `pyarrow`/`polars` 因
  `files.pythonhosted.org` 不可达而装不上，而 DuckDB 原生就能读写 Parquet）。
  归一化记录先落**暂存 CSV**（`\\N` 表示 NULL，避免空串与 NULL 混淆），
  再走 `read_csv → COPY TO (FORMAT PARQUET)`。用 `executemany` 逐行插入实测只有
  约 6,000 行/秒，全市场要跑 4 分钟以上，所以不用那条路；
- 校验出现 P0 时命令以非零码结束，但已写入的产物不回滚（它们本身是可重建的派生物）。

用法：

    python scripts/migrate_storage.py --as-of 2026-09-17
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from datetime import time as clock
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE_AT = clock(15, 0)

RAW_DATASETS = (
    "daily_bars",
    "securities",
    "financial_balance",
    "financial_income",
    "financial_cashflow",
)

SNAPSHOT_KINDS = ("UNIVERSE", "FACTOR", "STRATEGY", "MARKET_REGIME", "CANDIDATE")

# 列定义的唯一出处：写暂存 CSV、让 DuckDB 建表、校验列集合，全部从这里派生。
COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "daily_bars": (
        ("symbol", "VARCHAR"),
        ("trade_date", "DATE"),
        ("open", "DOUBLE"),
        ("high", "DOUBLE"),
        ("low", "DOUBLE"),
        ("close", "DOUBLE"),
        ("pre_close", "DOUBLE"),
        ("volume", "DOUBLE"),
        ("amount", "DOUBLE"),
        ("turnover_rate", "DOUBLE"),
        ("pct_change", "DOUBLE"),
        ("adj_factor", "DOUBLE"),
    ),
    "securities": (
        ("symbol", "VARCHAR"),
        ("name", "VARCHAR"),
        ("exchange", "VARCHAR"),
        ("list_date", "DATE"),
        ("is_st", "BOOLEAN"),
        ("is_delisting_board", "BOOLEAN"),
        ("suspended_trading_days", "BIGINT"),
    ),
    "financial_observations": (
        ("symbol", "VARCHAR"),
        ("metric", "VARCHAR"),
        ("report_period", "DATE"),
        ("announce_date", "DATE"),
        ("available_at", "TIMESTAMPTZ"),
        ("as_of", "TIMESTAMPTZ"),
        ("source", "VARCHAR"),
        ("value", "DOUBLE"),
        ("unit", "VARCHAR"),
    ),
    "valuations": (
        ("symbol", "VARCHAR"),
        ("metric", "VARCHAR"),
        ("valuation_date", "DATE"),
        ("available_at", "TIMESTAMPTZ"),
        ("as_of", "TIMESTAMPTZ"),
        ("source", "VARCHAR"),
        ("value", "DOUBLE"),
        ("unit", "VARCHAR"),
        ("text_value", "VARCHAR"),
    ),
}

PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "daily_bars": ("symbol", "trade_date"),
    "securities": ("symbol",),
    "financial_observations": ("symbol", "report_period", "metric"),
    "valuations": ("symbol", "valuation_date", "metric"),
}

NULLABLE_NUMERIC: dict[str, tuple[str, ...]] = {
    "daily_bars": (
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "volume",
        "amount",
        "turnover_rate",
        "pct_change",
        "adj_factor",
    ),
    "financial_observations": ("value",),
    "valuations": ("value",),
    "securities": ("suspended_trading_days",),
}

NULL_TOKEN = r"\N"


class Verification:
    """收集校验结论；任何 P0 都会让命令以非零码结束。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def record(self, dataset: str, check: str, severity: str, detail: str) -> None:
        self.rows.append((dataset, check, severity, detail))

    @property
    def blocked(self) -> bool:
        return any(severity == "P0" for _, _, severity, _ in self.rows)

    def report(self) -> str:
        lines = []
        for dataset, check, severity, detail in self.rows:
            mark = {"P0": "x", "P1": "!", "P2": "~", "PASS": "+"}.get(severity, "?")
            lines.append(f"  {mark} [{severity:<4}] {dataset:<24} {check:<18} {detail}")
        return "\n".join(lines)


def _duckdb() -> Any:
    try:
        import duckdb
    except ImportError as error:  # pragma: no cover - environment guard
        raise SystemExit(
            "DuckDB 未安装；先运行 `uv sync --extra data`（或 --extra providers）"
        ) from error
    return duckdb


def _as_of(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), CLOSE_AT, SHANGHAI)


# --------------------------------------------------------------------------- #
# 摘要：类型感知的规范形式，让两侧用同一把尺子
# --------------------------------------------------------------------------- #


def _canonical_record(record: Any) -> bytes:
    payload: dict[str, object] = {}
    for name in type(record).model_fields:
        value = getattr(record, name)
        if isinstance(value, datetime):
            # 时间点按瞬时比较：Parquet 的 TIMESTAMPTZ 回读是 UTC，
            # 内存里是 +08:00，两者是同一时刻，摘要必须一致。
            payload[name] = value.astimezone(UTC).isoformat()
        elif isinstance(value, date):
            payload[name] = value.isoformat()
        else:
            payload[name] = value
    return (
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )


def _digest(records: Iterable[Any]) -> tuple[str, int]:
    hasher = hashlib.sha256()
    count = 0
    for record in records:
        hasher.update(_canonical_record(record))
        count += 1
    return hasher.hexdigest(), count


# --------------------------------------------------------------------------- #
# 第一段：Raw CSV → DuckDB 视图（不复制数据）
# --------------------------------------------------------------------------- #


def stage_raw(conn: Any, csv_root: Path, log: Any) -> None:
    started = time.monotonic()
    created = 0
    for dataset in RAW_DATASETS:
        path = csv_root / f"{dataset}.csv"
        if not path.is_file():
            log(f"  - raw {dataset}: 文件不存在，跳过")
            continue
        conn.execute(
            f"CREATE OR REPLACE VIEW raw_{dataset} AS "
            f"SELECT * FROM read_csv('{path}', header=true, all_varchar=true)"
        )
        created += 1
    log(
        f"  raw 视图 {created} 个，用时 {time.monotonic() - started:.1f}s（未复制任何 CSV）"
    )


# --------------------------------------------------------------------------- #
# 第二段：归一化 → Parquet（暂存 CSV + DuckDB COPY）
# --------------------------------------------------------------------------- #


def _staging_value(value: object) -> str:
    if value is None:
        return NULL_TOKEN
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _land(
    conn: Any,
    dataset: str,
    records: Sequence[Any],
    *,
    path: Path,
    staging_dir: Path,
    log: Any,
) -> None:
    """把一批规范记录落成 Parquet，并在 DuckDB 里挂一个指向它的同名视图。

    路线：暂存 CSV（`\\N` 表示 NULL）→ `read_csv` 带显式类型 → `COPY TO` Parquet。
    全程由 DuckDB 完成，不需要 pyarrow。
    """
    columns = COLUMNS[dataset]
    names = [name for name, _ in columns]
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging = staging_dir / f"{dataset}.csv"

    started = time.monotonic()
    with staging.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(names)
        for record in records:
            writer.writerow([_staging_value(getattr(record, name)) for name in names])
    written = time.monotonic() - started

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f"{path.name}.tmp"
    types = "{" + ", ".join(f"'{name}': '{kind}'" for name, kind in columns) + "}"
    conn.execute(
        f"COPY (SELECT * FROM read_csv('{staging}', header=true, "
        f"nullstr='{NULL_TOKEN}', types={types})) "
        f"TO '{temporary}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    temporary.replace(path)

    # 归一化数据的权威副本是 Parquet，DuckDB 里只留一个指向它的视图：
    # 灌一份实体表会立刻产生"两份会漂移的归一化数据"，而项目里不允许有两个真相。
    # 视图用的是相对仓库根目录的路径，所以要从仓库根目录打开这个库。
    conn.execute(
        f"CREATE OR REPLACE VIEW {dataset} AS SELECT * FROM read_parquet('{path}')"
    )
    staging.unlink()
    log(
        f"  {dataset:<24} {len(records):>9,} 行 → {path.stat().st_size / 1e6:.1f} MB"
        f"（暂存 {written:.1f}s，导出 {time.monotonic() - started - written:.1f}s）"
    )


def normalize_in_memory(
    *, csv_root: Path, as_of: datetime, log: Any
) -> tuple[dict[str, tuple[Any, ...]], list[dict[str, object]]]:
    """跑一次项目自己的归一化链路，返回内存记录与质量门报告。

    只计算、不落盘：`stage_normalized` 与 `--verify-only` 共用这一段，
    保证"写下去的东西"和"用来比对的东西"来自同一次归一化语义。
    """
    from astock_lens.pipelines.stages import normalize_stage

    started = time.monotonic()
    log("  调用 normalize_stage（项目唯一归一化链路）…")
    outcome = normalize_stage(csv_root=csv_root, as_of=as_of)
    log(f"  归一化完成，用时 {time.monotonic() - started:.1f}s")

    in_memory: dict[str, tuple[Any, ...]] = {
        "daily_bars": outcome.bars.daily_bars,
        "securities": outcome.securities,
        "financial_observations": outcome.financials.observations,
        "valuations": outcome.valuations.observations,
    }
    findings = [
        report.model_dump(mode="json")
        for report in (outcome.quality_report, *outcome.financials.reports)
    ]
    return in_memory, findings


def stage_normalized(
    conn: Any,
    *,
    in_memory: dict[str, tuple[Any, ...]],
    findings: Sequence[dict[str, object]],
    parquet_root: Path,
    staging_dir: Path,
    log: Any,
) -> None:
    """把归一化产物落成 Parquet，并在 DuckDB 里挂成同名表。"""
    for dataset, records in in_memory.items():
        _land(
            conn,
            dataset,
            records,
            path=parquet_root / dataset / f"{dataset}.parquet",
            staging_dir=staging_dir,
            log=log,
        )

    # 被质量门挡下的记录同样要留证据。这是小型报告 manifest，按裁决第 4 条用 JSON。
    findings_path = parquet_root / "quality_findings" / "quality_findings.json"
    findings_path.parent.mkdir(parents=True, exist_ok=True)
    findings_path.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    log(f"  质量门报告 {len(findings)} 份 → quality_findings.json")


# --------------------------------------------------------------------------- #
# 第三段：JSON 业务状态 → DuckDB
# --------------------------------------------------------------------------- #


def stage_state(
    conn: Any, *, snapshot_root: Path, job_root: Path, watchlist_root: Path, log: Any
) -> dict[str, int]:
    now = datetime.now(tz=SHANGHAI)
    counts: dict[str, int] = {}

    conn.execute(
        """
        CREATE OR REPLACE TABLE snapshots (
            kind VARCHAR NOT NULL,
            as_of DATE NOT NULL,
            record_count BIGINT NOT NULL,
            payload JSON NOT NULL,
            written_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (kind, as_of)
        )
        """
    )
    snapshot_rows = 0
    for kind in SNAPSHOT_KINDS:
        directory = snapshot_root / kind
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            records = document.get("records", [])
            conn.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?, ?)",
                [
                    str(document.get("kind", kind)),
                    date.fromisoformat(path.stem),
                    len(records),
                    json.dumps(records, ensure_ascii=False),
                    now,
                ],
            )
            snapshot_rows += 1
    counts["snapshots"] = snapshot_rows

    conn.execute(
        """
        CREATE OR REPLACE TABLE job_runs (
            as_of DATE NOT NULL,
            position BIGINT NOT NULL,
            job_type VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            rows_in BIGINT,
            rows_out BIGINT,
            error VARCHAR,
            note VARCHAR,
            payload JSON NOT NULL,
            PRIMARY KEY (as_of, job_type)
        )
        """
    )
    job_rows = 0
    job_paths = sorted(job_root.glob("*.json")) if job_root.is_dir() else []
    for path in job_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for position, run in enumerate(document.get("runs", [])):
            conn.execute(
                "INSERT OR REPLACE INTO job_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    date.fromisoformat(str(document.get("as_of", path.stem))[:10]),
                    position,
                    str(run.get("job_type")),
                    str(run.get("status")),
                    run.get("started_at"),
                    run.get("finished_at"),
                    run.get("rows_in"),
                    run.get("rows_out"),
                    run.get("error"),
                    run.get("note"),
                    json.dumps(run, ensure_ascii=False),
                ],
            )
            job_rows += 1
    counts["job_runs"] = job_rows

    conn.execute(
        """
        CREATE OR REPLACE TABLE watchlist (
            symbol VARCHAR NOT NULL,
            state VARCHAR NOT NULL,
            updated_at TIMESTAMPTZ,
            payload JSON NOT NULL,
            PRIMARY KEY (symbol)
        )
        """
    )
    watch_rows = 0
    watch_paths = (
        sorted(watchlist_root.glob("*.json")) if watchlist_root.is_dir() else []
    )
    for path in watch_paths:
        entry = json.loads(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT OR REPLACE INTO watchlist VALUES (?, ?, ?, ?)",
            [
                str(entry.get("symbol", path.stem)),
                str(entry.get("state")),
                entry.get("updated_at"),
                json.dumps(entry, ensure_ascii=False),
            ],
        )
        watch_rows += 1
    counts["watchlist"] = watch_rows
    counts["job_files"] = len(job_paths)
    counts["snapshot_files"] = sum(
        len(list((snapshot_root / kind).glob("*.json")))
        for kind in SNAPSHOT_KINDS
        if (snapshot_root / kind).is_dir()
    )

    log(
        f"  业务状态入库：snapshots {snapshot_rows} 条 / job_runs {job_rows} 条 / "
        f"watchlist {watch_rows} 条"
    )
    return counts


# --------------------------------------------------------------------------- #
# 第四段：四关校验
# --------------------------------------------------------------------------- #


def _model_for(dataset: str) -> Any:
    from astock_lens.domain.models import (
        DailyBar,
        FinancialObservation,
        SecurityProfile,
        ValuationObservation,
    )

    return {
        "daily_bars": DailyBar,
        "securities": SecurityProfile,
        "financial_observations": FinancialObservation,
        "valuations": ValuationObservation,
    }[dataset]


def _scalar(conn: Any, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def _select_list(dataset: str) -> tuple[str, list[str], list[str]]:
    """双读时用的 SELECT 列清单。

    `TIMESTAMPTZ` 在 DuckDB 的 Python 客户端里回读成 Python 对象需要 `pytz`，
    本机装不上（`files.pythonhosted.org` 不可达）。所以时间列在 SQL 侧就转成
    ISO 字符串，Python 侧用 `datetime.fromisoformat` 还原——绕开那个可选依赖，
    比较的仍然是同一瞬时。
    """
    parts: list[str] = []
    names: list[str] = []
    kinds: list[str] = []
    for name, kind in COLUMNS[dataset]:
        if kind == "TIMESTAMPTZ":
            parts.append(f"CAST({name} AS VARCHAR) AS {name}")
        else:
            parts.append(name)
        names.append(name)
        kinds.append(kind)
    return ", ".join(parts), names, kinds


def _row_to_values(
    names: Sequence[str], kinds: Sequence[str], row: Sequence[Any]
) -> dict[str, object]:
    values: dict[str, object] = {}
    for name, kind, value in zip(names, kinds, row, strict=True):
        if kind == "TIMESTAMPTZ" and isinstance(value, str):
            values[name] = datetime.fromisoformat(value)
        else:
            values[name] = value
    return values


def stage_verify(
    conn: Any,
    *,
    parquet_root: Path,
    in_memory: dict[str, tuple[Any, ...]],
    verification: Verification,
    log: Any,
) -> None:
    for dataset, records in in_memory.items():
        path = parquet_root / dataset / f"{dataset}.parquet"
        if not path.is_file():
            verification.record(dataset, "结构", "P0", f"Parquet 不存在：{path}")
            continue

        model = _model_for(dataset)
        expected_fields = set(model.model_fields)
        names = [name for name, _ in COLUMNS[dataset]]
        reader = f"read_parquet('{path}')"

        # 关 1：结构
        described = {
            row[0]
            for row in conn.execute(f"DESCRIBE SELECT * FROM {reader}").fetchall()
        }
        if described != expected_fields or set(names) != expected_fields:
            verification.record(
                dataset,
                "结构",
                "P0",
                f"列不一致：Parquet 多 {sorted(described - expected_fields)} / "
                f"缺 {sorted(expected_fields - described)}",
            )
        else:
            verification.record(
                dataset, "结构", "PASS", f"{len(described)} 列与规范模型一致"
            )

        # 关 2：计数
        written = _scalar(conn, f"SELECT count(*) FROM {reader}")
        if written != len(records):
            verification.record(
                dataset,
                "计数",
                "P0",
                f"Parquet {written:,} 行 != 内存 {len(records):,} 行",
            )
        else:
            verification.record(dataset, "计数", "PASS", f"{written:,} 行两侧一致")

        # 关 3：主键唯一
        keys = PRIMARY_KEYS[dataset]
        key_list = ", ".join(keys)
        duplicates = _scalar(
            conn,
            f"SELECT count(*) FROM (SELECT {key_list} FROM {reader} "
            f"GROUP BY {key_list} HAVING count(*) > 1)",
        )
        if duplicates:
            verification.record(
                dataset, "主键", "P0", f"{duplicates} 组重复主键（{key_list}）"
            )
        else:
            verification.record(dataset, "主键", "PASS", f"{key_list} 唯一")

        # 关 4a：空值与零值——缺失必须仍是缺失，不得变成 0
        clean = True
        for column in NULLABLE_NUMERIC.get(dataset, ()):
            written_nulls = _scalar(
                conn, f"SELECT count(*) FROM {reader} WHERE {column} IS NULL"
            )
            memory_nulls = sum(1 for r in records if getattr(r, column) is None)
            written_zeros = _scalar(
                conn, f"SELECT count(*) FROM {reader} WHERE {column} = 0"
            )
            memory_zeros = sum(1 for r in records if getattr(r, column) == 0)
            if written_nulls != memory_nulls:
                clean = False
                verification.record(
                    dataset,
                    f"空值 {column}",
                    "P0",
                    f"Parquet {written_nulls:,} != 内存 {memory_nulls:,}",
                )
            if written_zeros != memory_zeros:
                clean = False
                verification.record(
                    dataset,
                    f"零值 {column}",
                    "P0",
                    f"Parquet {written_zeros:,} != 内存 {memory_zeros:,}（0 凭空出现）",
                )
        if clean:
            verification.record(
                dataset, "空值/零值", "PASS", "缺失仍为缺失，未退化成 0"
            )

        # 关 4b：双读——Parquet 读回来重建成规范模型，逐条比摘要
        memory_digest, memory_count = _digest(records)
        select_list, read_names, read_kinds = _select_list(dataset)
        hasher = hashlib.sha256()
        replayed = 0
        cursor = conn.execute(f"SELECT {select_list} FROM {reader}")
        while True:
            rows = cursor.fetchmany(200_000)
            if not rows:
                break
            for row in rows:
                rebuilt = model.model_validate(
                    _row_to_values(read_names, read_kinds, row)
                )
                hasher.update(_canonical_record(rebuilt))
                replayed += 1
        if replayed != memory_count or hasher.hexdigest() != memory_digest:
            verification.record(
                dataset,
                "双读",
                "P0",
                f"摘要不一致：Parquet {hasher.hexdigest()[:12]}/{replayed:,} "
                f"!= 内存 {memory_digest[:12]}/{memory_count:,}",
            )
        else:
            verification.record(
                dataset, "双读", "PASS", f"逐条重建后摘要一致 {memory_digest[:12]}"
            )

    log("  四关校验完成")


def stage_verify_state(
    conn: Any, counts: dict[str, int], verification: Verification
) -> None:
    stored = _scalar(conn, "SELECT count(*) FROM snapshots")
    severity = "PASS" if counts["snapshot_files"] == stored else "P0"
    verification.record(
        "snapshots",
        "计数",
        severity,
        f"JSON {counts['snapshot_files']} 份 <-> DuckDB {stored} 行",
    )

    job_days = _scalar(conn, "SELECT count(DISTINCT as_of) FROM job_runs")
    severity = "PASS" if counts["job_files"] == job_days else "P0"
    verification.record(
        "job_runs",
        "计数",
        severity,
        f"JSON {counts['job_files']} 天 <-> DuckDB {job_days} 天",
    )


def _persist_verification(conn: Any, verification: Verification) -> None:
    """把校验报告写进库里，让"这一层到底验过什么"有据可查。"""
    conn.execute("DROP TABLE IF EXISTS migration_verification")
    conn.execute(
        "CREATE TABLE migration_verification ("
        "dataset VARCHAR, check_name VARCHAR, severity VARCHAR, detail VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO migration_verification VALUES (?, ?, ?, ?)", verification.rows
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="存储迁移：CSV/JSON → Parquet + DuckDB"
    )
    parser.add_argument("--as-of", default="2026-09-17", help="交易日 YYYY-MM-DD")
    parser.add_argument("--csv-root", default="data/raw")
    parser.add_argument("--parquet-root", default="data/normalized")
    parser.add_argument("--snapshot-root", default="data/snapshots")
    parser.add_argument("--job-root", default="var/jobs")
    parser.add_argument("--watchlist-root", default="data/watchlist")
    parser.add_argument("--database", default="var/astock.duckdb")
    parser.add_argument("--staging", default="var/_migration_staging")
    parser.add_argument(
        "--state-only",
        action="store_true",
        help="只搬 Raw 视图与业务状态，跳过全市场归一化（快）",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="不写任何东西，只对已落盘的 Parquet 与 DuckDB 重跑四关校验",
    )
    arguments = parser.parse_args()

    def log(message: str) -> None:
        print(message, flush=True)

    duckdb = _duckdb()
    csv_root = Path(arguments.csv_root)
    parquet_root = Path(arguments.parquet_root)
    database = Path(arguments.database)
    staging_dir = Path(arguments.staging)
    as_of = _as_of(arguments.as_of)

    log(
        f"迁移目标：as_of={arguments.as_of}  database={database}  parquet_root={parquet_root}"
    )
    database.parent.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(database))
    # 时间列的字符串渲染固定到 UTC，让回读结果与机器所在时区无关。
    conn.execute("SET TimeZone='UTC'")

    verification = Verification()
    started = time.monotonic()

    snapshot_root = Path(arguments.snapshot_root)
    job_root = Path(arguments.job_root)

    if arguments.verify_only:
        log("[verify-only] 不写任何东西，只对已落盘产物重跑四关校验")
        in_memory, _findings = normalize_in_memory(
            csv_root=csv_root, as_of=as_of, log=log
        )
        counts = {
            "snapshot_files": sum(
                len(list((snapshot_root / kind).glob("*.json")))
                for kind in SNAPSHOT_KINDS
                if (snapshot_root / kind).is_dir()
            ),
            "job_files": len(list(job_root.glob("*.json"))) if job_root.is_dir() else 0,
        }
        log("[4/4] 四关校验")
        stage_verify(
            conn,
            parquet_root=parquet_root,
            in_memory=in_memory,
            verification=verification,
            log=log,
        )
        stage_verify_state(conn, counts, verification)
        _persist_verification(conn, verification)
        log("")
        log(verification.report())
        log("")
        log(
            f"总用时 {time.monotonic() - started:.1f}s；报告已写入 migration_verification 表"
        )
        return 1 if verification.blocked else 0

    log("[1/4] Raw CSV → DuckDB 视图")
    stage_raw(conn, csv_root, log)

    in_memory: dict[str, tuple[Any, ...]] = {}
    log("[2/4] 归一化 → Parquet")
    if arguments.state_only:
        log("  --state-only：跳过归一化，只把已有 Parquet 挂成视图")
        for dataset in COLUMNS:
            path = parquet_root / dataset / f"{dataset}.parquet"
            if path.is_file():
                conn.execute(
                    f"CREATE OR REPLACE VIEW {dataset} AS "
                    f"SELECT * FROM read_parquet('{path}')"
                )
    else:
        in_memory, findings = normalize_in_memory(
            csv_root=csv_root, as_of=as_of, log=log
        )
        stage_normalized(
            conn,
            in_memory=in_memory,
            findings=findings,
            parquet_root=parquet_root,
            staging_dir=staging_dir,
            log=log,
        )

    log("[3/4] JSON 业务状态 → DuckDB")
    counts = stage_state(
        conn,
        snapshot_root=snapshot_root,
        job_root=job_root,
        watchlist_root=Path(arguments.watchlist_root),
        log=log,
    )

    log("[4/4] 四关校验")
    if in_memory:
        stage_verify(
            conn,
            parquet_root=parquet_root,
            in_memory=in_memory,
            verification=verification,
            log=log,
        )
    stage_verify_state(conn, counts, verification)
    _persist_verification(conn, verification)

    log("")
    log(verification.report())
    log("")
    log(
        f"总用时 {time.monotonic() - started:.1f}s；报告已写入 migration_verification 表"
    )

    shutil.rmtree(staging_dir, ignore_errors=True)

    if verification.blocked:
        log("结论：存在 P0，**不得**把默认读取路径切到 Parquet。")
        return 1
    log("结论：四关全绿，可以进入默认读取路径切换。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
