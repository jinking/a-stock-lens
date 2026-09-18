"""冷启动的按标的持久化检查点。

为什么需要它（2026-09-18 失败复盘的直接教训）：旧流程每完成一块就把整份
`daily_bars.csv` 合并重写一遍，代价与**文件大小**成正比，于是运行到 10 万行之后，
"写"本身成了主要开销——表现为 CPU 满载、文件 mtime 一直更新、而有效数据一根不涨。

检查点把"完成"的代价改成与**已完成量**成正比：

```text
data/raw/bootstrap/<as-of>/manifest.json   ← 每只标的一条状态（原子替换写入）
data/raw/bootstrap/<as-of>/parts/<symbol>.csv ← 该标的这一轮取回的行
```

- 分片文件名就是 symbol，因此同一只标的重复成功会**覆盖自己的分片**，天然幂等；
- 清单用"临时文件 + 原子替换"落盘，不会留下写了一半的 JSON；
- 续跑只暴露仍缺的标的，已完成的不再抓（这是"不得为了验证修复重跑全市场"的机制基础）。

分片何时合并进 `daily_bars.csv` 由 Task 7 的一次性确定性压实负责；本模块不做合并。
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path

from astock_lens.data.contracts import RawPayload
from astock_lens.data.sync import merge_payloads, read_raw_rows, write_merged_atomic
from astock_lens.domain.models import DomainRecord


class BootstrapSymbolState(str, Enum):
    """一只标的在本轮冷启动里的处置结果。"""

    PENDING = "pending"
    SUCCESS = "success"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    SOURCE_ERROR = "source_error"


class BootstrapManifestEntry(DomainRecord):
    """清单里的一行：一只标的的状态与证据。"""

    symbol: str
    status: BootstrapSymbolState
    bars: int = 0
    attempts: int = 0
    last_error: str | None = None
    updated_at: datetime


class BootstrapManifest(DomainRecord):
    """一次冷启动的完整清单。"""

    as_of: date
    required_valid_bars: int
    entries: tuple[BootstrapManifestEntry, ...] = ()


def _atomic_write_text(path: Path, text: str) -> None:
    """先写临时文件再原子替换：读者永远看不到半份清单。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = _mkstemp(path)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _mkstemp(path: Path) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )


def compact_bootstrap_run(
    *,
    checkpoint: BootstrapCheckpoint,
    canonical_path: Path,
) -> tuple[int, int]:
    """把本轮**成功**标的的分片一次性、确定性地合并进整份行情文件。

    顺序只由内容决定：清单里成功的标的按 symbol 排序（`manifest()` 本身有序），分片就按这个
    顺序读，于是同一批分片无论按什么顺序落盘，合并结果逐字节相同；同一次运行重复压实也不会
    改动文件（同键替换 + 确定的顺序）。整份文件只被读写一次，写入走原子替换，进程在中途被杀
    不会留下半份行情。

    失败标的的分片不参与合并：`TIMEOUT` / `SOURCE_ERROR` / `EMPTY` 是"这次没拿到"，不是"拿到了
    零根 bar"，把它当成功合并进去就是静默兜底。没有成功分片时不动整份文件，返回 `(0, 0)`。
    """
    payloads: list[RawPayload] = []
    for entry in checkpoint.manifest().entries:
        if entry.status is not BootstrapSymbolState.SUCCESS:
            continue
        columns, rows = read_raw_rows(checkpoint.parts_path(entry.symbol))
        if columns and rows:
            payloads.append(RawPayload(columns=columns, rows=rows))

    payload = merge_payloads(payloads)
    if payload is None:
        return (0, 0)
    return write_merged_atomic(canonical_path, payload)


class BootstrapCheckpoint:
    """一只标的完成一次，就记一次；重开对象也能看见。"""

    def __init__(self, root: Path, *, as_of: date, required_valid_bars: int) -> None:
        self._root = Path(root)
        self._as_of = as_of
        self._required = required_valid_bars
        self._dir = self._root / "bootstrap" / as_of.isoformat()
        self._manifest_path = self._dir / "manifest.json"
        self._parts_dir = self._dir / "parts"
        self._entries: dict[str, BootstrapManifestEntry] = {
            entry.symbol: entry for entry in self._load_entries()
        }

    # ---- 读取 -------------------------------------------------------------

    def manifest(self) -> BootstrapManifest:
        return BootstrapManifest(
            as_of=self._as_of,
            required_valid_bars=self._required,
            entries=tuple(self._entries[symbol] for symbol in sorted(self._entries)),
        )

    def entry_for(self, symbol: str) -> BootstrapManifestEntry | None:
        return self._entries.get(symbol)

    def pending_symbols(self, symbols: Sequence[str]) -> tuple[str, ...]:
        """还缺数据的标的：不是 SUCCESS 的一律算缺。"""
        return tuple(
            symbol
            for symbol in symbols
            if self._entries.get(symbol) is None
            or self._entries[symbol].status is not BootstrapSymbolState.SUCCESS
        )

    def parts_path(self, symbol: str) -> Path:
        return self._parts_dir / f"{symbol}.csv"

    def iter_part_files(self) -> Iterator[Path]:
        if not self._parts_dir.is_dir():
            return iter(())
        return iter(sorted(self._parts_dir.glob("*.csv")))

    # ---- 写入 -------------------------------------------------------------

    def record_success(
        self,
        symbol: str,
        *,
        columns: Sequence[str],
        rows: Sequence[Sequence[str]],
    ) -> BootstrapManifestEntry:
        """落一份分片并记状态；重复成功覆盖自己的分片，不产生第二份。"""
        path = self.parts_path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = _mkstemp(path)
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows)
        os.replace(temporary, path)

        previous = self._entries.get(symbol)
        return self._record(
            BootstrapManifestEntry(
                symbol=symbol,
                status=BootstrapSymbolState.SUCCESS,
                bars=len(rows),
                attempts=(previous.attempts if previous else 0) + 1,
                last_error=None,
                updated_at=datetime.now(UTC),
            )
        )

    def record_failure(
        self,
        symbol: str,
        *,
        state: BootstrapSymbolState,
        error: str | None = None,
    ) -> BootstrapManifestEntry:
        """记一次失败；分片不写，绝不把失败写成空数据。"""
        previous = self._entries.get(symbol)
        return self._record(
            BootstrapManifestEntry(
                symbol=symbol,
                status=state,
                bars=previous.bars if previous else 0,
                attempts=(previous.attempts if previous else 0) + 1,
                last_error=error,
                updated_at=datetime.now(UTC),
            )
        )

    # ---- 内部 -------------------------------------------------------------

    def _record(self, entry: BootstrapManifestEntry) -> BootstrapManifestEntry:
        self._entries[entry.symbol] = entry
        _atomic_write_text(
            self._manifest_path,
            json.dumps(
                self.manifest().model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        return entry

    def _load_entries(self) -> tuple[BootstrapManifestEntry, ...]:
        if not self._manifest_path.is_file():
            return ()
        payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        return BootstrapManifest.model_validate(payload).entries
