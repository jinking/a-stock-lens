"""有界 completion-order fallback 调度器的回归测试。"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Mapping
from datetime import UTC, date, datetime

from astock_lens.data.bootstrap_scheduler import (
    FallbackAttempt,
    SchedulerStats,
    fetch_symbols_bounded,
)
from astock_lens.data.bootstrap_sources import SymbolBarFallbackSource
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.providers.akshare_provider import (
    AkShareProvider,
)
from astock_lens.domain.enums import DataStatus

AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
END_DATE = date(2026, 9, 17)
BAR_COLUMNS = ("symbol", "trade_date", "close")


class ControlledSource:
    """本地可控 source；所有计数均为跨进程共享状态。"""

    def __init__(
        self, *, delays: dict[str, float] | None = None, hang: bool = False
    ) -> None:
        context = multiprocessing.get_context("fork")
        self.delays = delays or {}
        self.hang = hang
        self.active = context.Value("i", 0)
        self.max_active = context.Value("i", 0)
        self.requests = context.Value("i", 0)
        self._lock = context.Lock()

    def fetch_symbol_bars(self, symbol: str, **_: object) -> RawDataset:
        with self._lock:
            self.requests.value += 1
            self.active.value += 1
            self.max_active.value = max(self.max_active.value, self.active.value)
        try:
            if self.hang:
                multiprocessing.Event().wait(30)
            time.sleep(self.delays.get(symbol, 0))
            return RawDataset(
                provider="test",
                dataset="daily_bars",
                fetched_at=datetime.now(UTC),
                provider_version="test",
                status=DataStatus.VALUE,
                row_count=1,
                payload=RawPayload(
                    columns=BAR_COLUMNS,
                    rows=((symbol, END_DATE.isoformat(), "1"),),
                ),
            )
        finally:
            with self._lock:
                self.active.value -= 1


def _blocking_transport(
    _: str, __: Mapping[str, str]
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """模拟 AkShare transport 永不返回，不访问网络。"""
    multiprocessing.Event().wait(30)
    return (), ()


def _run(
    source: SymbolBarFallbackSource,
    symbols: tuple[str, ...],
    *,
    max_inflight: int = 2,
    operation_timeout_seconds: float = 1.0,
) -> tuple[list[FallbackAttempt], SchedulerStats]:
    attempts: list[FallbackAttempt] = []
    stats = fetch_symbols_bounded(
        source=source,
        symbols=symbols,
        as_of=AS_OF,
        start_date=date(2026, 9, 1),
        end_date=END_DATE,
        max_inflight=max_inflight,
        operation_timeout_seconds=operation_timeout_seconds,
        on_result=attempts.append,
    )
    return attempts, stats


def test_fast_later_symbol_is_checkpointed_before_slow_first_symbol() -> None:
    source = ControlledSource(delays={"slow.SZ": 0.25})

    attempts, stats = _run(source, ("slow.SZ", "fast.SZ"))

    assert [attempt.symbol for attempt in attempts] == ["fast.SZ", "slow.SZ"]
    assert stats.completed == 2


def test_max_inflight_is_bounded_for_5300_fake_symbols() -> None:
    source = ControlledSource()
    symbols = tuple(f"{index:06d}.SZ" for index in range(5_300))

    attempts, stats = _run(source, symbols, max_inflight=6)

    assert len(attempts) == len(symbols)
    assert source.max_active.value <= 6
    assert stats.max_inflight_observed <= 6


def test_all_hanging_akshare_workers_are_terminated_without_serial_timeouts() -> None:
    source = AkShareProvider(transport=_blocking_transport)
    symbols = tuple(f"{index:06d}.SZ" for index in range(50))
    before = {child.pid for child in multiprocessing.active_children()}

    started = time.perf_counter()
    attempts, stats = _run(
        source,
        symbols,
        max_inflight=6,
        operation_timeout_seconds=0.2,
    )
    elapsed = time.perf_counter() - started
    after = {child.pid for child in multiprocessing.active_children()}

    assert elapsed < 1.0, f"timeouts accumulated serially: {elapsed:.3f}s"
    assert len(attempts) == 6
    assert all(attempt.status is DataStatus.SOURCE_ERROR for attempt in attempts)
    assert stats.timed_out == 6
    assert stats.max_inflight_observed == 6
    assert after <= before


def test_all_success_requests_do_not_exceed_symbol_count() -> None:
    source = ControlledSource()
    symbols = tuple(f"{index:06d}.SZ" for index in range(30))

    attempts, stats = _run(source, symbols, max_inflight=30)

    assert len(attempts) == len(symbols)
    assert source.requests.value <= len(symbols)
    assert stats.submitted == len(symbols)
