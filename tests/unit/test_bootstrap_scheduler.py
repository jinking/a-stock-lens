"""全市场 fallback 调度器的超时边界回归测试。

这些测试先固定当前线程池实现的两个缺陷：Future 的等待超时会按提交顺序累加，
而被放弃的线程仍可能在调度器返回后继续执行。真正的 transport 超时与有界
scheduler 由后续任务实现。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from astock_lens.data.bootstrap import land_bar_chunks
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.domain.enums import DataStatus

AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
END_DATE = date(2026, 9, 17)
BAR_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
)


class FirstNHangFetcher:
    """前 n 个开始的操作挂起，其余操作立即完成，并记录线程状态。"""

    def __init__(self, *, n: int, sleep_seconds: float) -> None:
        self.n = n
        self.sleep_seconds = sleep_seconds
        self.active = 0
        self.max_active = 0
        self.started = 0
        self.finished = 0
        self.release = threading.Event()
        self._lock = threading.Lock()

    def fetch_symbol_bars(self, symbol: str, **_: object) -> RawDataset:
        with self._lock:
            self.started += 1
            ordinal = self.started
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if ordinal <= self.n:
                # 用可释放的事件模拟远超 deadline 的阻塞，测试结束时可安全唤醒
                # 工作线程，避免红测让 pytest 进程永久等待。
                self.release.wait(self.sleep_seconds)
            row = (
                symbol,
                END_DATE.isoformat(),
                "1",
                "1",
                "1",
                "1",
                "1",
                "1000",
                "0.01",
            )
            return RawDataset(
                provider="test",
                dataset="daily_bars",
                fetched_at=datetime.now(UTC),
                provider_version="test",
                status=DataStatus.VALUE,
                row_count=1,
                payload=RawPayload(columns=BAR_COLUMNS, rows=(row,)),
            )
        finally:
            with self._lock:
                self.active -= 1
                self.finished += 1


def _run(
    fetcher: FirstNHangFetcher,
    root: Path,
    symbols: Sequence[str],
    *,
    max_inflight: int,
    operation_timeout_seconds: float,
):
    return land_bar_chunks(
        provider=fetcher,
        root=root,
        as_of=AS_OF,
        symbols=tuple(symbols),
        start_date=date(2026, 9, 1),
        end_date=END_DATE,
        chunk_size=50,
        max_workers=max_inflight,
        symbol_timeout_seconds=operation_timeout_seconds,
    )


def test_all_inflight_workers_hanging_does_not_serialize_timeout_budget(local_tmp: Path):
    symbols = tuple(f"{i:06d}.SZ" for i in range(50))
    fetcher = FirstNHangFetcher(n=6, sleep_seconds=30)

    started = time.perf_counter()
    try:
        result = _run(
            fetcher,
            local_tmp,
            symbols,
            max_inflight=6,
            operation_timeout_seconds=0.2,
        )
    finally:
        fetcher.release.set()
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert elapsed < 1.0, f"timeouts accumulated serially: {elapsed:.3f}s"
    assert result is not None


def test_timeout_does_not_leave_running_work_behind(local_tmp: Path):
    symbols = tuple(f"{i:06d}.SZ" for i in range(50))
    fetcher = FirstNHangFetcher(n=6, sleep_seconds=30)

    try:
        _run(
            fetcher,
            local_tmp,
            symbols,
            max_inflight=6,
            operation_timeout_seconds=0.2,
        )

        assert fetcher.max_active == 6
        assert fetcher.started >= 6
        assert fetcher.finished == fetcher.started
        assert fetcher.active == 0
    finally:
        fetcher.release.set()
