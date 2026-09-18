"""全市场 fallback 调度器的超时边界回归测试。

这些测试先固定当前线程池实现的两个缺陷：Future 的等待超时会按提交顺序累加，
而被放弃的线程仍可能在调度器返回后继续执行。真正的 transport 超时与有界
scheduler 由后续任务实现。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

from astock_lens.data.bootstrap_scheduler import run_fallback_scheduler


class FirstNHangFetcher:
    """前 n 个开始的操作挂起，其余操作立即完成，并记录线程状态。"""

    def __init__(self, *, n: int, sleep_seconds: float) -> None:
        self.n = n
        self.sleep_seconds = sleep_seconds
        self.active = 0
        self.max_active = 0
        self.started = 0
        self.finished = 0
        self._lock = threading.Lock()

    def fetch_symbol_bars(self, symbol: str, **_: object) -> None:
        with self._lock:
            self.started += 1
            ordinal = self.started
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if ordinal <= self.n:
                time.sleep(self.sleep_seconds)
        finally:
            with self._lock:
                self.active -= 1
                self.finished += 1


def _run(
    fetcher: FirstNHangFetcher,
    symbols: Sequence[str],
    *,
    max_inflight: int,
    operation_timeout_seconds: float,
) -> object:
    return run_fallback_scheduler(
        fetcher=fetcher,
        symbols=tuple(symbols),
        max_inflight=max_inflight,
        operation_timeout_seconds=operation_timeout_seconds,
    )


def test_all_inflight_workers_hanging_does_not_serialize_timeout_budget():
    symbols = tuple(f"{i:06d}.SZ" for i in range(50))
    fetcher = FirstNHangFetcher(n=6, sleep_seconds=30)

    started = time.perf_counter()
    result = _run(
        fetcher,
        symbols,
        max_inflight=6,
        operation_timeout_seconds=0.2,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert result is not None


def test_timeout_does_not_leave_running_work_behind():
    symbols = tuple(f"{i:06d}.SZ" for i in range(50))
    fetcher = FirstNHangFetcher(n=6, sleep_seconds=30)

    _run(
        fetcher,
        symbols,
        max_inflight=6,
        operation_timeout_seconds=0.2,
    )

    assert fetcher.max_active == 6
    assert fetcher.started >= 6
    assert fetcher.finished == fetcher.started
    assert fetcher.active == 0
