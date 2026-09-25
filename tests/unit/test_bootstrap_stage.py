"""bootstrap 阶段（扫描成本、调度器）长尾用例。

本文件由 Task 12「文件合并」把以下 2 个同域小文件整体搬入：
    - tests/unit/test_bootstrap_scan_cost.py（4 例）
    - tests/unit/test_bootstrap_scheduler.py（4 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from astock_lens.data import bootstrap
from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    bootstrap_liquidity_history,
    land_bar_chunks,
)
from astock_lens.data.bootstrap_checkpoint import BootstrapCheckpoint
from astock_lens.data.bootstrap_scheduler import (
    FallbackAttempt,
    SchedulerStats,
    fetch_symbols_bounded,
)
from astock_lens.data.bootstrap_sources import SymbolBarFallbackSource
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.providers.akshare_provider import AkShareProvider
from astock_lens.domain.enums import DataStatus

# ===========================================================================
# 来源：tests/unit/test_bootstrap_scan_cost.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 启动流程的读取成本：一次运行只读落地文件常数次，不按标的数重复读。
#
# 2026-09-18 全池实测发现的缺陷：首轮 5,301 只标的落地完成后，流程在收尾计数上
# 烧了 30 分钟以上的纯 CPU（`ps` 显示 96% CPU、零 TCP 连接、日志 31 分钟无输出）。
# 根因是 `_count_bars` 每只标的都把整份 `daily_bars.csv`（当时 97,641 行）重新读一遍
# 并解析一遍，于是"按标的计数"变成 O(标的数 × 文件行数)。
#
# 这条测试用可计数的 `read_raw_rows` 替代品把成本钉住：一次运行读取落地文件的次数
# 必须是常数级（每轮扩展一次 + 收尾一次），而不是随标的数增长。
#


AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


SCAN_COST_END_DATE = date(2026, 9, 17)


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


SYMBOLS = tuple(f"{index:06d}.SZ" for index in range(60))


class CountingFetcher:
    """每只标的都返回足够长的历史，于是不会有扩展轮次。"""

    def __init__(self, *, days: int = 30) -> None:
        self._days = days

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        rows = tuple(
            (
                symbol,
                (end_date - __import__("datetime").timedelta(days=offset)).isoformat(),
                "1",
                "1",
                "1",
                "1",
                "1",
                "1000",
                "0.01",
            )
            for offset in range(self._days)
        )
        return RawDataset(
            provider="counting",
            dataset="daily_bars",
            fetched_at=datetime.now(UTC),
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=BAR_COLUMNS, rows=rows),
        )


def test_the_flow_reads_the_landed_file_a_constant_number_of_times(
    local_tmp: Path, monkeypatch
) -> None:
    real_read = bootstrap.read_raw_rows
    big_file = local_tmp / "daily_bars.csv"
    calls = {"whole_file": 0, "parts": 0}

    def counted_read(path: Path):
        # 按标的暂存后，分片是每只标的小文件读一次；被钉住的是"整份落地文件"的读取，
        # 它必须与标的数无关。
        if path == big_file:
            calls["whole_file"] += 1
        else:
            calls["parts"] += 1
        return real_read(path)

    monkeypatch.setattr(bootstrap, "read_raw_rows", counted_read)

    bootstrap_liquidity_history(
        batch_source=None,
        fallback_source=CountingFetcher(),
        root=local_tmp,
        as_of=AS_OF,
        symbols=SYMBOLS,
        requirement=BootstrapRequirement(
            factor_name="avg_amount_20d", required_valid_bars=20
        ),
        end_date=SCAN_COST_END_DATE,
        batch_size=20,
    )

    assert calls["whole_file"] >= 1, "成本测试必须确认确实读取过落地文件"
    # 一次运行最多读几次：覆盖判定 + 每轮扩展一次计数 + 收尾一次。60 只标的
    # 只应有的个位数次数；按标的重复读会是 60 次以上。
    assert calls["whole_file"] <= 8, (
        "the landed file must be read a constant number of times per run, not "
        "once per symbol; read "
        f"{calls['whole_file']} times for {len(SYMBOLS)} symbols"
    )
    # 分片读取按标的数线性增长：同一只标的的分片每轮最多读两次（续跑判定一次、压实一次），
    # 不是每块读一次、也不是按整份文件的行数重复读。这条用例只有一轮，所以上界是标的数。
    assert calls["parts"] <= len(SYMBOLS), (
        "每只标的的分片每轮最多读两次；实际读取 "
        f"{calls['parts']} 次，标的数 {len(SYMBOLS)}"
    )


class RecordingFetcher:
    """只在工作日有 bar（真实市场的形状），并记录每次请求。"""

    def __init__(self) -> None:
        self.requests: list[tuple[str, date, date]] = []

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        self.requests.append((symbol, start_date, end_date))
        days = (end_date - start_date).days
        trading = [
            end_date - __import__("datetime").timedelta(days=offset)
            for offset in range(days + 1)
        ]
        rows = tuple(
            (symbol, day.isoformat(), "1", "1", "1", "1", "1", "1000", "0.01")
            for day in trading
            if day.weekday() < 5
        )
        return RawDataset(
            provider="recording",
            dataset="daily_bars",
            fetched_at=datetime.now(UTC),
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=BAR_COLUMNS, rows=rows),
        )


def test_the_first_window_is_wide_enough_to_finish_in_one_round(
    local_tmp: Path,
) -> None:
    """20 根 bar 不能被翻译成 20 个自然日。

    2026-09-18 全池实测：初始窗口按"所需 bar 数 = 自然日数"取，20 个自然日只含
    约 15 个交易日，于是 5,301 只标的里 92% 被判不足、全市场白跑第二遍。这里用
    每日都有数据的标的把"一遍就够"钉住：每只标的只应被请求一次。
    """
    provider = RecordingFetcher()

    bootstrap_liquidity_history(
        batch_source=None,
        fallback_source=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=SYMBOLS[:5],
        requirement=BootstrapRequirement(
            factor_name="avg_amount_20d", required_valid_bars=20
        ),
        end_date=SCAN_COST_END_DATE,
        batch_size=5,
    )

    per_symbol = {symbol: 0 for symbol in SYMBOLS[:5]}
    for symbol, _, _ in provider.requests:
        per_symbol[symbol] += 1
    assert set(per_symbol.values()) == {1}, (
        "a daily-history symbol must be satisfied by the first window; rounds per "
        f"symbol were {per_symbol}"
    )


class HangingFetcher:
    """一只标的永久挂住，其余正常返回。"""

    def __init__(self, hanging: str) -> None:
        self.hanging = hanging

    def fetch_symbol_bars(self, symbol: str, *, as_of, start_date, end_date):
        if symbol == self.hanging:
            __import__("time").sleep(60)
        row = (symbol, end_date.isoformat(), "1", "1", "1", "1", "1", "1000", "0.01")
        return RawDataset(
            provider="hanging",
            dataset="daily_bars",
            fetched_at=datetime.now(UTC),
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=1,
            payload=RawPayload(columns=BAR_COLUMNS, rows=(row,)),
        )


def test_one_hung_symbol_must_not_block_the_whole_chunk(local_tmp: Path) -> None:
    """块落盘不得依赖"所有请求都返回"。

    2026-09-18 全池续跑实测：进程 3 分钟零落盘、0% CPU、只有 1 条 TCP 连接、
    日志 0 字节——某个网络请求永久挂住，而分块落盘要等整块所有 future 返回，
    于是一只标的把整轮都拖成静止。这里用一只故意挂 60 秒的标的钉住修复：
    整块必须在有界时间内完成落盘，挂住的那只按失败记账、下一轮再试。
    """
    symbols = tuple(f"{index:06d}.SZ" for index in range(6))
    fetcher = HangingFetcher(hanging="000003.SZ")
    started = __import__("time").perf_counter()

    result = land_bar_chunks(
        fallback_source=fetcher,
        root=local_tmp,
        as_of=AS_OF,
        symbols=symbols,
        start_date=date(2026, 9, 1),
        end_date=SCAN_COST_END_DATE,
        batch_size=6,
        checkpoint=BootstrapCheckpoint(
            local_tmp, as_of=AS_OF.date(), required_valid_bars=20
        ),
        max_inflight=6,
        operation_timeout_seconds=1.0,
    )
    elapsed = __import__("time").perf_counter() - started

    assert elapsed < 10, (
        f"the chunk must not wait for the hung symbol; took {elapsed:.1f}s"
    )
    assert result.failed_symbols == ("000003.SZ",)
    assert set(result.completed_symbols) == set(symbols) - {"000003.SZ"}
    columns, rows = bootstrap.read_raw_rows(local_tmp / "daily_bars.csv")
    assert {row[columns.index("symbol")] for row in rows} == set(symbols) - {
        "000003.SZ"
    }, "the symbols that answered must be persisted before the round ends"


def test_a_symbol_that_already_has_enough_bars_is_not_fetched_again(
    local_tmp: Path,
) -> None:
    """判定"要不要抓"必须看实测 bar 数，而不是窗口边界。

    2026-09-18 实测：窗口 start 取到 2026-08-08（周六），而标的第一根 bar 在
    08-10，`covered_symbols` 要求 `最早行 <= start`，于是**永远判缺**——那 400 只
    早已够 20 根的标的被反复重抓，抓回来的东西文件里本来就有：CPU 91%、文件 mtime
    一直更新、行数一根不涨。这条测试钉住正确语义：够数的标的一次都不该再被请求。
    """
    symbol = "000001.SZ"
    # 25 根，全部 <= as_of（时点规则：晚于 as_of 的 bar 不算数）
    rows = [
        "symbol,trade_date,open,high,low,close,volume,amount,turnover_rate",
        *[
            f"{symbol},{(SCAN_COST_END_DATE - __import__('datetime').timedelta(days=offset)).isoformat()},"
            "1,1,1,1,1,1000,0.01"
            for offset in range(25)
        ],
    ]
    (local_tmp / "daily_bars.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    provider = RecordingFetcher()
    bootstrap_liquidity_history(
        batch_source=None,
        fallback_source=provider,
        root=local_tmp,
        as_of=AS_OF,
        symbols=(symbol,),
        requirement=BootstrapRequirement(
            factor_name="avg_amount_20d", required_valid_bars=20
        ),
        end_date=SCAN_COST_END_DATE,
        batch_size=5,
    )

    assert provider.requests == [], (
        "a symbol that already carries the required bars must not be fetched; "
        f"requests were {provider.requests}"
    )


# ===========================================================================
# 来源：tests/unit/test_bootstrap_scheduler.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


SCHEDULER_AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


END_DATE = date(2026, 9, 17)


SCHEDULER_BAR_COLUMNS = ("symbol", "trade_date", "close")


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
                    columns=SCHEDULER_BAR_COLUMNS,
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
        as_of=SCHEDULER_AS_OF,
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
