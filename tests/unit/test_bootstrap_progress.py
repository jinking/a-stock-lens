"""冷启动的内建心跳与进度。

2026-09-18 的复盘把"看不见运行状态"列为独立缺陷：进程 3 分钟无输出、文件不再增长、CPU
却满载，人只能靠另一块屏幕上的 `scripts/watch-bootstrap.sh` 猜；而那个脚本把总数与日期写死
在自身。这些测试钉住三件事：慢运行必须在跑完之前就发心跳；数字必须来自本次 invocation；
进度行里不得出现写死的总数或日期。
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    bootstrap_liquidity_history,
)
from astock_lens.data.bootstrap_progress import (
    BootstrapProgress,
    BootstrapProgressTracker,
    render_progress,
)
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.domain.enums import DataStatus

ROOT = Path(__file__).resolve().parents[2]
AS_OF = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)
END_DATE = date(2026, 9, 18)
COLUMNS = ("symbol", "trade_date", "close", "amount")
REQUIRED_BARS = 20


class _Clock:
    """假时钟：让"间隔到了才发"这条性质不靠真的等 15 秒。"""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _CollectingSink:
    def __init__(self) -> None:
        self.emitted: list[BootstrapProgress] = []

    def emit(self, progress: BootstrapProgress) -> None:
        self.emitted.append(progress)


def test_progress_is_emitted_only_once_the_heartbeat_interval_elapses() -> None:
    clock = _Clock()
    sink = _CollectingSink()
    tracker = BootstrapProgressTracker(
        total=10, sink=sink, heartbeat_seconds=15.0, now=clock
    )

    tracker.record(processed=1)
    assert len(sink.emitted) == 1, "启动就该有一行，让操作者知道这次要处理多少只"
    assert sink.emitted[0].processed == 1

    for _ in range(4):
        tracker.record(processed=1)
    assert len(sink.emitted) == 1, "间隔没到就不该刷屏"

    clock.advance(16.0)
    tracker.record(processed=1)

    assert len(sink.emitted) == 2
    assert sink.emitted[1].processed == 6
    assert sink.emitted[1].pending == 4


def test_finishing_always_leaves_a_last_line() -> None:
    clock = _Clock()
    sink = _CollectingSink()
    tracker = BootstrapProgressTracker(
        total=4, sink=sink, heartbeat_seconds=15.0, now=clock
    )
    tracker.record(processed=4)

    progress = tracker.finish()

    assert [item.processed for item in sink.emitted] == [4, 4]
    assert sink.emitted[-1] is not None, "收尾那条必须带完整的最终数字"
    assert progress.pending == 0


def test_satisfied_is_the_measured_count_not_the_success_count() -> None:
    tracker = BootstrapProgressTracker(total=10)
    tracker.record(processed=8)

    progress = tracker.measure(satisfied=7)

    assert progress.processed == 8
    assert progress.satisfied == 7, "落盘成功不等于达标：少 bar 的标的下轮还要再抓"


def test_a_negative_total_is_refused() -> None:
    try:
        BootstrapProgressTracker(total=-1)
    except ValueError as error:
        assert "total" in str(error)
    else:  # pragma: no cover - 失败路径
        raise AssertionError("total 不得为负")


def test_the_progress_line_carries_no_hard_coded_total_or_date() -> None:
    progress = BootstrapProgress(
        total=7,
        processed=7,
        satisfied=7,
        failed=0,
        pending=0,
        inflight=0,
        elapsed_seconds=3.0,
        throughput_per_second=2.3,
    )

    line = render_progress(progress)

    assert "processed 7/7" in line
    assert "2.3 sym/s" in line
    assert "elapsed 00:00:03" in line
    assert "5301" not in line, "总数必须来自本次 invocation，不是写死的全市场只数"
    assert "2026" not in line, "进度行不得夹带写死的日期"


class _SlowFallback:
    """每只标的都慢慢回答：慢运行正是心跳存在的理由。"""

    def __init__(
        self,
        *,
        delay_seconds: float,
        short: frozenset[str] = frozenset(),
        failing: frozenset[str] = frozenset(),
    ) -> None:
        self._delay = delay_seconds
        self._short = short
        self._failing = failing
        self.calls: list[str] = []

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        self.calls.append(symbol)
        time.sleep(self._delay)
        if symbol in self._failing:
            return RawDataset(
                provider="slow",
                dataset="daily_bars",
                fetched_at=AS_OF,
                provider_version="test",
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
                message=f"{symbol} could not be fetched",
            )
        days = 5 if symbol in self._short else 30
        rows = tuple(
            (
                symbol,
                (END_DATE - timedelta(days=offset)).isoformat(),
                "10",
                "30000000",
            )
            for offset in range(days)
        )
        return RawDataset(
            provider="slow",
            dataset="daily_bars",
            fetched_at=AS_OF,
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=COLUMNS, rows=rows),
        )


def _run_with_progress(
    root: Path,
    symbols: tuple[str, ...],
    *,
    sink: _CollectingSink,
    heartbeat_seconds: float,
    delay_seconds: float = 0.0,
    short: frozenset[str] = frozenset(),
    failing: frozenset[str] = frozenset(),
):
    return bootstrap_liquidity_history(
        batch_source=None,
        fallback_source=_SlowFallback(
            delay_seconds=delay_seconds, short=short, failing=failing
        ),
        root=root,
        as_of=AS_OF,
        symbols=symbols,
        requirement=BootstrapRequirement(
            factor_name="avg_amount_20d", required_valid_bars=REQUIRED_BARS
        ),
        end_date=END_DATE,
        batch_size=100,
        max_inflight=1,
        progress=sink,
        heartbeat_seconds=heartbeat_seconds,
    )


def test_a_slow_fake_run_emits_progress_before_it_finishes(local_tmp: Path) -> None:
    sink = _CollectingSink()
    symbols = ("000001.SZ", "000002.SZ", "000003.SZ")

    result = _run_with_progress(
        # 0.4 秒 × 3 只 ≈ 1.2 秒：跨过"速率必须有实测窗口"的 1 秒门槛。
        local_tmp,
        symbols,
        sink=sink,
        heartbeat_seconds=0.05,
        delay_seconds=0.4,
    )

    assert len(sink.emitted) >= 2, (
        "慢运行必须在结束前就给出心跳，而不是只在收尾打一行；实际 "
        f"{len(sink.emitted)} 行"
    )
    assert {item.total for item in sink.emitted} == {len(symbols)}
    assert sink.emitted[-1].processed == len(symbols)
    assert sink.emitted[-1].pending == 0
    assert sink.emitted[-1].inflight == 0
    assert sink.emitted[-1].throughput_per_second > 0
    assert set(result.satisfied_symbols) == set(symbols)


def test_the_total_follows_the_invocation_not_a_written_down_market_size(
    local_tmp: Path,
) -> None:
    small = _CollectingSink()
    large = _CollectingSink()

    _run_with_progress(
        local_tmp / "small", ("000001.SZ",), sink=small, heartbeat_seconds=0.0
    )
    _run_with_progress(
        local_tmp / "large",
        ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"),
        sink=large,
        heartbeat_seconds=0.0,
    )

    assert {item.total for item in small.emitted} == {1}
    assert {item.total for item in large.emitted} == {5}
    assert all("5301" not in render_progress(item) for item in large.emitted)


def test_a_symbol_short_of_history_is_not_reported_as_satisfied(
    local_tmp: Path,
) -> None:
    sink = _CollectingSink()
    symbols = ("000001.SZ", "000002.SZ")

    result = _run_with_progress(
        local_tmp,
        symbols,
        sink=sink,
        heartbeat_seconds=0.0,
        short=frozenset({"000002.SZ"}),
    )

    assert sink.emitted, "收尾必须留一行"
    assert set(result.satisfied_symbols) == {"000001.SZ"}
    assert sink.emitted[-1].satisfied == 1, (
        "成功落盘但不够 bar 的标的不得计入 satisfied；实际 "
        f"{sink.emitted[-1].satisfied}"
    )
    assert sink.emitted[-1].processed == len(symbols)


def test_the_heartbeat_counts_failed_symbols_not_failed_attempts(
    local_tmp: Path,
) -> None:
    """一只标的重试失败多轮只能算"失败 1 只"，否则心跳会夸大成两倍。

    2026-09-18 真实 100 只门禁实测：5 只 BJ 标的（腾讯接口不支持）被重试一次后，
    心跳写出 `failed 10`，而清单里只有 5 条 source_error。
    """
    sink = _CollectingSink()
    symbols = ("000001.SZ", "000002.SZ")

    result = _run_with_progress(
        local_tmp,
        symbols,
        sink=sink,
        heartbeat_seconds=0.0,
        failing=frozenset({"000002.SZ"}),
    )

    assert result.failed_symbols == ("000002.SZ",)
    assert sink.emitted[-1].failed == 1, (
        f"失败只数了 1 只标的，心跳却写 {sink.emitted[-1].failed}"
    )


def test_throughput_needs_a_measured_window() -> None:
    """不到 1 秒的分母给不出有意义的速率：宁可不写。"""
    clock = _Clock()
    tracker = BootstrapProgressTracker(total=10, now=clock)
    tracker.record(processed=5)

    assert tracker.snapshot().throughput_per_second == 0.0, "秒级以下不印速率"

    clock.advance(2.0)

    assert tracker.snapshot().throughput_per_second == 2.5
