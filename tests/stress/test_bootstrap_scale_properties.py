"""全市场规模下的冷启动属性（Task 10 硬门禁）。

这些测试**只**用假源，但用的是真实的编排路径：5,300 只标的、有界 in-flight、完成顺序调度、
逐标的检查点、跑完只压实一次。它们要证明的不是"今天跑得动"，而是四条与规模无关的性质：

1. 请求数有上界，且达标的标的不再被请求；
2. 并发不超过配置的 in-flight；
3. 1% 超时 + 1% 来源错误 + 1% 空历史时，成功的不丢、失败的不伪装、循环仍然收敛；
4. 中途停下再续跑，已落盘的标的不会被重抓，最终整份文件与一次跑完完全相同；
   批量覆盖 90% 时，逐标的补缺只投向缺口。

在 Task 10 完全通过之前，任何人不得运行 5,000+ 真实标的（计划里的 LIVE FULL-MARKET GATE）。
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    BootstrapSyncResult,
    bootstrap_liquidity_history,
)
from astock_lens.data.bootstrap_checkpoint import (
    BootstrapCheckpoint,
    BootstrapSymbolState,
)
from astock_lens.data.bootstrap_sources import (
    BatchFetchResult,
    BatchMarketBarSource,
    BootstrapBatchRequest,
    SymbolBarFallbackSource,
)
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.sync import read_raw_rows
from astock_lens.domain.enums import DataStatus

# 一个可复现的假市场：规模按 2026-09-18 实测的全市场标的数。
MARKET_SIZE = 5300
REQUIRED_BARS = 20
BARS_PER_SYMBOL = 20
MAX_INFLIGHT = 8
BATCH_REQUEST_SIZE = 1000
OPERATION_TIMEOUT_SECONDS = 0.05
TIMEOUT_SLEEP_SECONDS = 0.2
AS_OF = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)
END_DATE = date(2026, 9, 18)
COLUMNS = ("symbol", "trade_date", "close", "amount")


def _symbols(count: int = MARKET_SIZE) -> tuple[str, ...]:
    return tuple(f"{index:06d}.SZ" for index in range(count))


def _rows(symbol: str, *, bars: int = BARS_PER_SYMBOL) -> tuple[tuple[str, ...], ...]:
    """每只标的都带足够多的、落在 as_of 之前的 bar。"""
    return tuple(
        (
            symbol,
            (END_DATE - timedelta(days=offset)).isoformat(),
            "10",
            "30000000",
        )
        for offset in range(bars)
    )


def _value_dataset(symbol: str, rows: tuple[tuple[str, ...], ...]) -> RawDataset:
    return RawDataset(
        provider="fake",
        dataset="daily_bars",
        fetched_at=AS_OF,
        provider_version="stress",
        status=DataStatus.VALUE,
        row_count=len(rows),
        payload=RawPayload(columns=COLUMNS, rows=rows),
    )


class FakeMarketSource:
    """按标的取数的假市场，记录每一次请求与**真实观测到**的并发。"""

    def __init__(
        self,
        *,
        timed_out: set[str] | frozenset[str] = frozenset(),
        source_errors: set[str] | frozenset[str] = frozenset(),
        empty: set[str] | frozenset[str] = frozenset(),
        per_call_delay_seconds: float = 0.0,
    ) -> None:
        self.timed_out = set(timed_out)
        self.source_errors = set(source_errors)
        self.empty = set(empty)
        # 瞬时返回的假源在线程里根本来不及重叠，并发上界就成了空洞断言；
        # 给每次调用一点点真实耗时，重叠才会真的发生。
        self._delay = per_call_delay_seconds
        self.requests: list[str] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        with self._lock:
            self.requests.append(symbol)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            return self._answer(symbol)
        finally:
            with self._lock:
                self.active -= 1

    def _answer(self, symbol: str) -> RawDataset:
        if self._delay:
            time.sleep(self._delay)
        if symbol in self.timed_out:
            # 故意超过调度器 deadline：这只标的不会按时回答，必须被记成超时。
            time.sleep(TIMEOUT_SLEEP_SECONDS)
        if symbol in self.source_errors:
            return RawDataset(
                provider="fake",
                dataset="daily_bars",
                fetched_at=AS_OF,
                provider_version="stress",
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
                message=f"{symbol} failed at the source",
            )
        if symbol in self.empty:
            return RawDataset(
                provider="fake",
                dataset="daily_bars",
                fetched_at=AS_OF,
                provider_version="stress",
                status=DataStatus.NULL,
                row_count=0,
            )
        rows = _rows(symbol)
        return _value_dataset(symbol, rows)


class FakeBatchSource:
    """一次批量请求覆盖多个标的；没覆盖到的进 missing_symbols。"""

    def __init__(self, *, covered: set[str]) -> None:
        self.covered = covered
        self.requests: list[tuple[str, ...]] = []

    def fetch_recent_bars(self, request: BootstrapBatchRequest) -> BatchFetchResult:
        self.requests.append(request.symbols)
        covered = tuple(s for s in request.symbols if s in self.covered)
        missing = tuple(s for s in request.symbols if s not in self.covered)
        rows = tuple(row for symbol in covered for row in _rows(symbol))
        datasets = (_value_dataset("*", rows),) if rows else ()
        return BatchFetchResult(
            datasets=datasets, missing_symbols=missing, source_name="fake-batch"
        )


def _run(
    root: Path,
    symbols: tuple[str, ...],
    *,
    fallback_source: SymbolBarFallbackSource,
    batch_source: BatchMarketBarSource | None = None,
    max_inflight: int = MAX_INFLIGHT,
) -> BootstrapSyncResult:
    return bootstrap_liquidity_history(
        batch_source=batch_source,
        fallback_source=fallback_source,
        root=root,
        as_of=AS_OF,
        symbols=symbols,
        requirement=BootstrapRequirement(
            factor_name="avg_amount_20d", required_valid_bars=REQUIRED_BARS
        ),
        end_date=END_DATE,
        batch_size=BATCH_REQUEST_SIZE,
        max_inflight=max_inflight,
        operation_timeout_seconds=OPERATION_TIMEOUT_SECONDS,
    )


def _manifest(root: Path) -> BootstrapCheckpoint:
    return BootstrapCheckpoint(root, as_of=END_DATE, required_valid_bars=REQUIRED_BARS)


def _landed_symbols(root: Path) -> set[str]:
    columns, rows = read_raw_rows(root / "daily_bars.csv")
    index = columns.index("symbol")
    return {row[index] for row in rows}


def test_all_success_converges_within_the_configured_request_bound(
    local_tmp: Path,
) -> None:
    """5,300 只全部成功：一次请求一只、不重复抓、并发有上界、清单终结。"""
    symbols = _symbols()
    source = FakeMarketSource(per_call_delay_seconds=0.002)

    result = _run(local_tmp, symbols, fallback_source=source)

    assert set(result.satisfied_symbols) == set(symbols)
    assert result.failed_symbols == ()
    assert len(source.requests) <= MARKET_SIZE, (
        f"请求数 {len(source.requests)} 超过标的数 {MARKET_SIZE}"
    )
    assert len(set(source.requests)) == len(source.requests), (
        "达标的标的不得被请求第二次"
    )
    # 下界与上界一起断言：只写 <= 的话，一个把并发退化成串行的实现也能"通过"。
    assert 2 <= source.max_active <= MAX_INFLIGHT, (
        f"观测到的并发 {source.max_active} 必须落在 (1, {MAX_INFLIGHT}] 内"
    )

    manifest = _manifest(local_tmp).manifest()
    assert len(manifest.entries) == MARKET_SIZE
    assert all(
        entry.status is BootstrapSymbolState.SUCCESS for entry in manifest.entries
    ), "清单必须收敛到「全部成功」"
    assert _landed_symbols(local_tmp) == set(symbols)


def test_mixed_failures_stay_explicit_and_the_run_still_converges(
    local_tmp: Path,
) -> None:
    """1% 超时 + 1% 来源错误 + 1% 空历史：成功不丢、失败不伪装、循环收敛。"""
    symbols = _symbols()
    timed_out = set(symbols[0::100])
    source_errors = set(symbols[1::100])
    empty = set(symbols[2::100])
    broken = timed_out | source_errors | empty
    assert len(timed_out) == len(source_errors) == len(empty) == 53, (
        "注入比例必须是 1%/1%/1%，否则这条性质就没在 5,300 的规模上被验证"
    )
    source = FakeMarketSource(
        timed_out=timed_out, source_errors=source_errors, empty=empty
    )

    result = _run(local_tmp, symbols, fallback_source=source)

    assert set(result.failed_symbols) == broken
    assert set(result.satisfied_symbols) == set(symbols) - broken
    assert _landed_symbols(local_tmp) == set(symbols) - broken, (
        "失败的标的不得留下任何一行；成功的必须都在整份文件里"
    )

    checkpoint = _manifest(local_tmp)
    assert checkpoint.entry_for(next(iter(timed_out))).status is (  # type: ignore[union-attr]
        BootstrapSymbolState.TIMEOUT
    )
    assert checkpoint.entry_for(next(iter(source_errors))).status is (  # type: ignore[union-attr]
        BootstrapSymbolState.SOURCE_ERROR
    )
    assert checkpoint.entry_for(next(iter(empty))).status is (  # type: ignore[union-attr]
        BootstrapSymbolState.EMPTY
    )

    # 收敛的上界：第一次全量 + 每轮只重试仍缺的标的。失败标的在第二轮被重试一次后
    # 计数没有前进，循环必须停下（"没有进展就停"，不是无限重试）。
    assert len(source.requests) <= MARKET_SIZE + 3 * len(broken), (
        f"请求数 {len(source.requests)} 超出收敛上界"
    )
    # 这里只能断言"有上界"，不能断言"严格等于 max_inflight"：假源没有进程隔离，
    # 超时被放弃的调用**还在线程里跑**，观测到的活调用可能比调度器的 in-flight 多。
    # 这条限制是 Task 4/5 裁决的直接后果（AkShare 路径走可终止的子进程，其严格上界由
    # tests/unit/test_bootstrap_scheduler.py 钉住）；调度器的"整批超时且无完成就停止提交"
    # 保证这种堆积不会无限增长。
    assert source.max_active <= 2 * MAX_INFLIGHT, (
        f"观测到的活调用峰值 {source.max_active} 超出上界 {2 * MAX_INFLIGHT}"
    )


def test_a_run_that_stopped_early_resumes_without_refetching(
    local_tmp: Path,
) -> None:
    """中途停下再续跑：已落盘的标的不得重抓，最终文件与一次跑完逐字节相同。

    "崩溃"在这里由一次只覆盖前 2,000 只的调用表示：磁盘上的状态（分片 + 清单）就是崩溃
    现场，续跑只该从这份状态出发。
    """
    symbols = _symbols()
    first_half = symbols[:2000]
    reference_root = local_tmp / "reference"
    resumed_root = local_tmp / "resumed"

    _run(reference_root, symbols, fallback_source=FakeMarketSource())

    first = FakeMarketSource()
    _run(resumed_root, first_half, fallback_source=first)
    checkpoint = _manifest(resumed_root)
    assert sum(
        1
        for entry in checkpoint.manifest().entries
        if entry.status is BootstrapSymbolState.SUCCESS
    ) == len(first_half), "中断前的成功必须先落盘，续跑才有意义"

    second = FakeMarketSource()
    result = _run(resumed_root, symbols, fallback_source=second)

    assert set(second.requests) == set(symbols) - set(first_half), (
        "已落盘并达标的标的不得被再次请求"
    )
    assert set(result.satisfied_symbols) == set(symbols)
    assert (resumed_root / "daily_bars.csv").read_bytes() == (
        reference_root / "daily_bars.csv"
    ).read_bytes(), "续跑结果必须与一次跑完相同（确定性压实）"


def test_batch_covering_ninety_percent_falls_back_only_for_the_gap(
    local_tmp: Path,
) -> None:
    """批量覆盖 90% 时，逐标的补缺只投向缺口，且批量请求本身不超上限。"""
    symbols = _symbols()
    covered = set(symbols[: int(MARKET_SIZE * 0.9)])
    gap = set(symbols) - covered
    batch = FakeBatchSource(covered=covered)
    fallback = FakeMarketSource(per_call_delay_seconds=0.002)

    result = _run(local_tmp, symbols, fallback_source=fallback, batch_source=batch)

    assert batch.requests, "批量来源必须被优先使用"
    assert all(len(request) <= BATCH_REQUEST_SIZE for request in batch.requests)
    assert sum(len(request) for request in batch.requests) == MARKET_SIZE, (
        "每一只标的都必须被某一次批量请求问过"
    )
    assert set(fallback.requests) == gap, (
        "补缺请求必须恰好是批量没覆盖的标的；多出来的："
        f"{sorted(set(fallback.requests) - gap)[:5]}"
    )
    assert len(fallback.requests) <= len(gap) + len(result.failed_symbols)
    assert set(result.satisfied_symbols) == set(symbols)
    assert _landed_symbols(local_tmp) == set(symbols)
    assert fallback.max_active <= MAX_INFLIGHT
