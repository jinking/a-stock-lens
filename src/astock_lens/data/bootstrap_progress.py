"""冷启动的原生心跳与进度事件。

2026-09-18 的复盘：全市场冷启动跑到中段时，判断"还在动"的唯一办法是另一块屏幕上的
`scripts/watch-bootstrap.sh`，而那个脚本把总数、所需 bar 数和日期写死在自己身上——它一旦
和这次运行的参数不一致，看到的进度就是假的。进度必须由**本次 invocation** 自己给出。

三条约定：

- 数字只有一个来源：本次调用的标的集合、调度器的 in-flight 计数、以及实测的达标 bar 数；
- 心跳按 wall-clock 节流（默认 15 秒，设计文档要求 10–20 秒），收尾必发最后一条；
- `satisfied` 是**实测**达标数，不是"成功落盘数"：落盘了但不够 bar 的标的下一轮还会再抓，
  把它算成达标就是自欺。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from astock_lens.domain.models import DomainRecord

# 心跳间隔：设计文档要求至少每 10–20 秒给出一行。技术节流值，不是产品阈值。
HEARTBEAT_SECONDS = 15.0


class BootstrapProgress(DomainRecord):
    """一次冷启动运行的进度快照；每个字段都来自本次调用。"""

    total: int
    processed: int
    satisfied: int
    failed: int
    pending: int
    inflight: int
    elapsed_seconds: float
    throughput_per_second: float


class ProgressSink(Protocol):
    """进度的消费端：CLI 打印、测试收集，或未来的日志与指标。"""

    def emit(self, progress: BootstrapProgress) -> None: ...


def render_progress(progress: BootstrapProgress) -> str:
    """把一次进度快照渲染成一行；格式里没有任何写死的数字或日期。"""
    minutes, seconds = divmod(int(progress.elapsed_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return (
        f"processed {progress.processed}/{progress.total} | "
        f"satisfied {progress.satisfied} | failed {progress.failed} | "
        f"pending {progress.pending} | inflight {progress.inflight} | "
        f"{progress.throughput_per_second:.1f} sym/s | "
        f"elapsed {hours:02d}:{minutes:02d}:{seconds:02d}"
    )


class BootstrapProgressTracker:
    """累计一次运行的数字，并按节流间隔决定何时发心跳。

    `now` 可注入：测试用假时钟把"间隔到了才发"这条性质钉死，不必真的等 15 秒。
    throughput 只由本次运行实测的 processed/elapsed 推出；没有样本时为 0，不猜 ETA。
    """

    def __init__(
        self,
        *,
        total: int,
        sink: ProgressSink | None = None,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if total < 0:
            raise ValueError(f"total must not be negative, got {total}")
        if heartbeat_seconds < 0:
            raise ValueError(
                f"heartbeat_seconds must not be negative, got {heartbeat_seconds}"
            )
        self._total = total
        self._sink = sink
        self._heartbeat = heartbeat_seconds
        self._now = now
        self._started = now()
        # 启动即发第一行：既让操作者立刻看到"这次要处理多少只"，也顺带 flush 掉前面被
        # 缓冲住的上市/预筛输出（2026-09-18 真实门禁里，重定向日志在前 20 秒里一行都没有）。
        self._last_emit = self._started - heartbeat_seconds
        self._processed = 0
        self._satisfied = 0
        self._failed = 0
        self._inflight = 0

    # ---- 累计 -------------------------------------------------------------

    def record(
        self,
        *,
        processed: int = 0,
        failed: int = 0,
        inflight: int | None = None,
    ) -> BootstrapProgress:
        """记下本次 invocation 里又消化了多少只标的，必要时发一条心跳。"""
        self._processed += processed
        self._failed += failed
        if inflight is not None:
            self._inflight = inflight
        return self._emit_if_due()

    def measure(
        self,
        *,
        processed: int | None = None,
        satisfied: int | None = None,
        failed: int | None = None,
    ) -> BootstrapProgress:
        """用**实测**只数覆盖 `satisfied` / `failed`。

        两个数都是"多少只标的"，不是"发生过多少次"：同一只标的跨轮重试失败只算一只，
        否则心跳会写出"失败 10"而实际只失败 5 只——2026-09-18 真实 100 只门禁里踩到过。
        `satisfied` 同样是实测达标数，不是成功落盘数。
        """
        if satisfied is not None:
            self._satisfied = satisfied
        if failed is not None:
            self._failed = failed
        if processed is not None:
            # 只允许向上：这只标的是"有结果了"，不是重新开始计数。
            self._processed = max(self._processed, processed)
        return self._emit_if_due()

    def snapshot(self) -> BootstrapProgress:
        elapsed = max(self._now() - self._started, 0.0)
        processed = min(self._processed, self._total)
        # 不到 1 秒的窗口算不出有意义的速率：续跑一上来就有几十只"已满足"时，秒级以下的
        # 分母会印出 15489.9 sym/s 这种数字（2026-09-18 真实门禁实测），宁可不给。
        measured = elapsed >= 1.0
        return BootstrapProgress(
            total=self._total,
            processed=processed,
            satisfied=self._satisfied,
            failed=self._failed,
            pending=max(self._total - processed, 0),
            inflight=self._inflight,
            elapsed_seconds=elapsed,
            throughput_per_second=(processed / elapsed) if measured else 0.0,
        )

    def finish(self) -> BootstrapProgress:
        """收尾：无论间隔是否到，都发最后一条，让日志里留下一份完整账。"""
        progress = self.snapshot()
        self._publish(progress)
        return progress

    # ---- 内部 -------------------------------------------------------------

    def _emit_if_due(self) -> BootstrapProgress:
        progress = self.snapshot()
        if self._now() - self._last_emit >= self._heartbeat:
            self._publish(progress)
        return progress

    def _publish(self, progress: BootstrapProgress) -> None:
        self._last_emit = self._now()
        if self._sink is not None:
            self._sink.emit(progress)
