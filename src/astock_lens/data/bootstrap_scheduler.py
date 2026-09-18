"""逐标的 fallback 的有界完成顺序调度。

这里的 deadline 是 scheduler 对一次 source 调用的 wall-clock 上界，不是网络
transport timeout。AkShare 明确声明 transport 不可取消时，每个调用都必须放进
可终止、可 join 的独立进程；普通受控 source 则可以使用有界 daemon 线程。
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

from astock_lens.data.bootstrap_sources import (
    SymbolBarFallbackSource,
    ValidatedSymbolBarFallbackSource,
)
from astock_lens.data.contracts import RawDataset
from astock_lens.data.providers.akshare_provider import (
    AKSHARE_FALLBACK_REQUIRES_PROCESS_ISOLATION,
)
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord


class FallbackAttempt(DomainRecord):
    """一次 fallback 调用的完成记录，供 checkpoint 回调立即消费。"""

    symbol: str
    status: DataStatus
    dataset: RawDataset | None = None
    error: str | None = None


class SchedulerStats(DomainRecord):
    """本次调度实际提交和完成的计数，不推测未提交标的的状态。"""

    submitted: int
    completed: int
    timed_out: int
    source_errors: int
    max_inflight_observed: int


@dataclass
class _ActiveWorker:
    started_at: float
    worker: Any
    result_queue: Any
    process_isolated: bool


def _fetch_in_worker(
    result_queue: Any,
    source: ValidatedSymbolBarFallbackSource,
    symbol: str,
    as_of: datetime,
    start_date: date,
    end_date: date,
) -> None:
    """在独立执行单元内运行 validated boundary，永远以结果消息返回。"""
    try:
        dataset = source.fetch_symbol_bars(
            symbol,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
        )
        result_queue.put((dataset, None))
    except Exception as error:  # noqa: BLE001 -- source failures must be recorded
        result_queue.put((None, f"{type(error).__name__}: {error}"))


def fetch_symbols_bounded(
    *,
    source: SymbolBarFallbackSource,
    symbols: Sequence[str],
    as_of: datetime,
    start_date: date,
    end_date: date,
    max_inflight: int,
    operation_timeout_seconds: float,
    on_result: Callable[[FallbackAttempt], None],
) -> SchedulerStats:
    """按完成顺序回调结果，并把运行集合严格限制为 ``max_inflight``。

    对声明 AkShare 隔离约束的 source，deadline 到期会终止并 join 对应 worker
    process，因此底层不可控 I/O 不会遗留为运行中任务。对于没有该声明的 fake 或
    受控 source，调度器只使用 daemon 线程来提供轻量并发；其 deadline 仍只是
    scheduler 等待边界，不能被表述为 transport timeout。
    """
    if max_inflight <= 0:
        raise ValueError("max_inflight must be positive")
    if operation_timeout_seconds <= 0:
        raise ValueError("operation_timeout_seconds must be positive")

    validated_source = (
        source
        if isinstance(source, ValidatedSymbolBarFallbackSource)
        else ValidatedSymbolBarFallbackSource(source)
    )
    process_isolated = (
        getattr(source, "fallback_execution_requirement", None)
        == AKSHARE_FALLBACK_REQUIRES_PROCESS_ISOLATION
    )
    context = multiprocessing.get_context("fork") if process_isolated else None
    pending = iter(dict.fromkeys(symbols))
    active: dict[str, _ActiveWorker] = {}
    submitted = completed = timed_out = source_errors = max_observed = 0
    exhausted = False
    draining_after_timeout = False

    def submit_until_full() -> None:
        nonlocal exhausted, submitted, max_observed
        while not exhausted and len(active) < max_inflight:
            try:
                symbol = next(pending)
            except StopIteration:
                exhausted = True
                return
            active[symbol] = _start_worker(
                context=context,
                source=validated_source,
                symbol=symbol,
                as_of=as_of,
                start_date=start_date,
                end_date=end_date,
                process_isolated=process_isolated,
            )
            submitted += 1
            max_observed = max(max_observed, len(active))

    submit_until_full()
    while active:
        completed_this_round = 0
        timed_out_this_round = 0
        for symbol, worker in tuple(active.items()):
            message = _read_message(worker.result_queue)
            if message is not None:
                dataset, error = message
                _reap_finished_worker(worker)
                active.pop(symbol)
                attempt = _attempt_from_message(symbol, dataset, error)
                on_result(attempt)
                completed += 1
                completed_this_round += 1
                if attempt.status is DataStatus.SOURCE_ERROR:
                    source_errors += 1
                continue

            if time.monotonic() - worker.started_at >= operation_timeout_seconds:
                _stop_timed_out_worker(worker)
                active.pop(symbol)
                on_result(
                    FallbackAttempt(
                        symbol=symbol,
                        status=DataStatus.SOURCE_ERROR,
                        error=(
                            "scheduler deadline elapsed; this is not a transport "
                            "timeout"
                        ),
                    )
                )
                completed += 1
                timed_out += 1
                source_errors += 1
                timed_out_this_round += 1

        if timed_out_this_round and not completed_this_round:
            draining_after_timeout = True
        elif completed_this_round:
            draining_after_timeout = False

        # 全部 in-flight 请求在同一轮均超时，说明此 source 当前没有响应能力。
        # 停止继续提交，避免把同一不可控故障放大为 N 次 timeout；已提交的进程
        # 均已 terminate/join，未提交标的由上层 checkpoint 的下一轮处理。
        if timed_out_this_round and not completed_this_round and not active:
            exhausted = True
        if not draining_after_timeout:
            submit_until_full()
        if active:
            time.sleep(0.002)

    return SchedulerStats(
        submitted=submitted,
        completed=completed,
        timed_out=timed_out,
        source_errors=source_errors,
        max_inflight_observed=max_observed,
    )


def _start_worker(
    *,
    context: Any,
    source: ValidatedSymbolBarFallbackSource,
    symbol: str,
    as_of: datetime,
    start_date: date,
    end_date: date,
    process_isolated: bool,
) -> _ActiveWorker:
    """启动一项工作；不使用 Future，因此不会误称等待 timeout 为网络 timeout。"""
    result_queue: Any
    if process_isolated:
        assert context is not None
        result_queue = context.Queue()
        worker = context.Process(
            target=_fetch_in_worker,
            args=(result_queue, source, symbol, as_of, start_date, end_date),
        )
    else:
        result_queue = queue.Queue()
        worker = threading.Thread(
            target=_fetch_in_worker,
            args=(result_queue, source, symbol, as_of, start_date, end_date),
            daemon=True,
        )
    worker.start()
    return _ActiveWorker(
        started_at=time.monotonic(),
        worker=worker,
        result_queue=result_queue,
        process_isolated=process_isolated,
    )


def _read_message(result_queue: Any) -> tuple[RawDataset | None, str | None] | None:
    try:
        return cast(tuple[RawDataset | None, str | None], result_queue.get_nowait())
    except queue.Empty:
        return None


def _attempt_from_message(
    symbol: str, dataset: RawDataset | None, error: str | None
) -> FallbackAttempt:
    if error is not None:
        return FallbackAttempt(
            symbol=symbol, status=DataStatus.SOURCE_ERROR, error=error
        )
    assert dataset is not None
    return FallbackAttempt(symbol=symbol, status=dataset.status, dataset=dataset)


def _reap_finished_worker(worker: _ActiveWorker) -> None:
    if worker.process_isolated:
        worker.worker.join(0.05)
        if worker.worker.is_alive():
            worker.worker.terminate()
            worker.worker.join()
        worker.result_queue.close()
        worker.result_queue.join_thread()
    else:
        worker.worker.join(0.05)


def _stop_timed_out_worker(worker: _ActiveWorker) -> None:
    if worker.process_isolated:
        worker.worker.terminate()
        worker.worker.join()
        worker.result_queue.close()
        worker.result_queue.join_thread()
