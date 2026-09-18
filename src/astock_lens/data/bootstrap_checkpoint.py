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


# 攒够这么多条未落盘记录就原子重写一次清单。逐只重写会让写放大变成 O(N²)（实测 5,300 只
# 84.4 秒）；攒批之后写入次数与标的数成正比、单次代价仍是"清单大小"，崩溃时最多丢掉这一批
# 记录——分片已经落盘，重跑最多少抓几只。技术节流值，不是产品阈值。
MANIFEST_FLUSH_EVERY = 64


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

    没有清单条目的分片**要**合并：分片只在 `record_success` 里落盘，所以"有分片、没条目"意味着
    进程在攒批 flush 之前被硬杀——那批数据是真抓到的，丢掉它就等于白抓。（反之，条目明确是失败
    状态时该分片是更早一轮的旧窗口，下一轮会重抓它，这里不合并。）
    """
    payloads: list[RawPayload] = []
    entries = {entry.symbol: entry for entry in checkpoint.manifest().entries}
    for part in checkpoint.iter_part_files():
        entry = entries.get(part.stem)
        if entry is not None and entry.status is not BootstrapSymbolState.SUCCESS:
            continue
        columns, rows = read_raw_rows(part)
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
        self._unflushed = 0

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
        flush: bool = True,
    ) -> BootstrapManifestEntry:
        """落一份分片并记状态；重复成功覆盖自己的分片，不产生第二份。

        `flush=False` 表示"先攒着"：分片此刻已经落盘，清单等 `flush()` 或攒够
        `MANIFEST_FLUSH_EVERY` 条再一次性原子写。批量落地内循环用它把写放大从
        O(N²) 压回 O(N)，落地调用结束前一定会 flush。
        """
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
            ),
            flush=flush,
        )

    def record_failure(
        self,
        symbol: str,
        *,
        state: BootstrapSymbolState,
        error: str | None = None,
        flush: bool = True,
    ) -> BootstrapManifestEntry:
        """记一次失败；分片不写，绝不把失败写成空数据。语义同 `record_success`。"""
        previous = self._entries.get(symbol)
        return self._record(
            BootstrapManifestEntry(
                symbol=symbol,
                status=state,
                bars=previous.bars if previous else 0,
                attempts=(previous.attempts if previous else 0) + 1,
                last_error=error,
                updated_at=datetime.now(UTC),
            ),
            flush=flush,
        )

    def flush(self) -> None:
        """把清单原子写到磁盘；没有未落盘的改动时什么都不做。"""
        if self._unflushed == 0:
            return
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
        self._unflushed = 0

    def adopt_success(self, symbol: str, *, bars: int) -> BootstrapManifestEntry:
        """把上一轮已落盘、清单却没记下来的成功补记进来。

        `record_success` 先写分片再写清单，进程恰好死在两次清单写之间时，续跑会因为
        "分片覆盖了窗口"而跳过这只标的——如果只跳过不补记，清单里就永远缺它一条，
        而清单是留给外部观察者（watcher、运营核对）看的，缺条目与"没抓到"无法区分。
        attempts 记 1：崩溃后无法得知真实尝试次数，只保证"至少抓到过一次"。
        """
        return self._record(
            BootstrapManifestEntry(
                symbol=symbol,
                status=BootstrapSymbolState.SUCCESS,
                bars=bars,
                attempts=1,
                last_error=None,
                updated_at=datetime.now(UTC),
            ),
            flush=False,
        )

    def adopt_staged_parts(self) -> tuple[str, ...]:
        """把"有分片、清单没条目"的标的全部补记并落盘，返回补记的 symbol。

        崩溃续跑之后调用：分片是已落盘的成功证据，清单是给外部观察者看的，两者必须一致。
        """
        adopted: list[str] = []
        for path in self.iter_part_files():
            if self.entry_for(path.stem) is not None:
                continue
            columns, rows = read_raw_rows(path)
            if columns and rows:
                self.adopt_success(path.stem, bars=len(rows))
                adopted.append(path.stem)
        self.flush()
        return tuple(adopted)

    # ---- 内部 -------------------------------------------------------------

    def _record(
        self, entry: BootstrapManifestEntry, *, flush: bool
    ) -> BootstrapManifestEntry:
        self._entries[entry.symbol] = entry
        self._unflushed += 1
        if flush or self._unflushed >= MANIFEST_FLUSH_EVERY:
            self.flush()
        return entry

    def _load_entries(self) -> tuple[BootstrapManifestEntry, ...]:
        if not self._manifest_path.is_file():
            return ()
        payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        return BootstrapManifest.model_validate(payload).entries
