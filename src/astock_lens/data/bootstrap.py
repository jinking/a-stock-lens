"""Bootstrap-history requirement for the Research Universe.

A cold start cannot know which symbols are liquid before it has some price
history: `avg_amount_20d` is *measured* over a window, so the window has to be
fetched before the Universe rule can compare it against the approved floor. How
many bars that takes is not a number this module may choose — it is the window
the configured liquidity factor declares, read from `configs/factors/*.yaml`.

Two failure modes are kept loud:

- the liquidity factor is not among the configured factors at all;
- the factor is configured but its window has not been reviewed (`window: null`,
  the same convention `configs/universe.yaml` uses for deferred rules).

Neither falls back to a default. A guessed window would silently change which
symbols qualify for research, which is a product decision, not an
implementation detail.
"""

from collections.abc import Callable, Iterator, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from astock_lens.data.bootstrap_checkpoint import (
    BootstrapCheckpoint,
    BootstrapSymbolState,
    compact_bootstrap_run,
)
from astock_lens.data.bootstrap_progress import (
    HEARTBEAT_SECONDS,
    BootstrapProgressTracker,
    ProgressSink,
)
from astock_lens.data.bootstrap_scheduler import FallbackAttempt, fetch_symbols_bounded
from astock_lens.data.bootstrap_sources import (
    BatchMarketBarSource,
    BootstrapBatchRequest,
    SymbolBarFallbackSource,
    validate_bootstrap_batch_result,
)
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.sync import (
    DEFAULT_BAR_DATASET,
    SYMBOL_COLUMN,
    TRADE_DATE_COLUMN,
    covered_symbols,
    read_raw_rows,
)
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord
from astock_lens.factors.builtin import RETURN_FACTOR_PREFIX
from astock_lens.factors.config import FactorConfig

# The Universe owns the name of the factor its liquidity rule consumes. It is
# imported rather than restated so the bootstrap can never measure a different
# quantity from the one the Universe compares against its floor.
from astock_lens.universe.builder import LIQUIDITY_FACTOR

# The dataset name the Universe's liquidity factor is bootstrapped from; bars
# land in the same file the rest of the pipeline reads.
BAR_DATASET = DEFAULT_BAR_DATASET

# What the strategy enrichment is called in its own result record. It is not a
# factor name: the requirement comes from the longest window across factors.
PRICE_HISTORY_LABEL = "strategy_price_history"

# How many calendar days to ask for per required bar. A calendar window of the
# same length as the requirement cannot hold that many *trading* days — a week
# brings 5 of them, holidays fewer — so an initial window of `required` calendar
# days makes nearly every symbol come back short and forces a second full pass
# over the market (measured 2026-09-18: 4,584 of 5,008 symbols landed at ~15
# bars when 20 were required). Two calendar days per bar leaves room for
# weekends and holidays; the extension loop below still covers genuinely sparse
# instruments. This is a technical multiplier, not a product threshold.
CALENDAR_DAYS_PER_REQUIRED_BAR = 2

# 取数结果里"没有数据可落"的状态。它们不是错误，但也不是成功：一律记成 EMPTY，
# 绝不写成 0 根 bar 的成功——那正是"静默兜底"。
_EMPTY_SOURCE_STATUSES: frozenset[DataStatus] = frozenset(
    {DataStatus.VALUE, DataStatus.NULL, DataStatus.NOT_APPLICABLE}
)

# How long the bounded scheduler waits for one fallback operation before it
# gives up on it. Measured 2026-09-18: a resume run sat with 0% CPU, one open TCP
# connection and an empty log for minutes because a network call never returned
# and the chunk waited for every future. With this bound the round always
# finishes and persists what answered; the straggler is recorded as a failure
# and retried by the next round. This is a scheduler wall-clock bound, never a
# claim about the transport's own timeout. Technical bound, not a product
# threshold.
SYMBOL_TIMEOUT_SECONDS = 60.0

# How many symbols one batch request may ask for. The batch contract has no live
# provider yet (2026-09-18 probe: `NO_BATCH_PRIMARY_AVAILABLE`), so this only
# bounds how large a single request to a future bulk endpoint gets. Technical
# bound, not a product threshold.
BATCH_REQUEST_SIZE = 100


class BootstrapRequirementNotConfigured(RuntimeError):
    """Raised when no reviewed liquidity window can be resolved from config."""


class BootstrapRequirement(DomainRecord):
    """How much price history the liquidity rule needs before it can be applied."""

    factor_name: str
    required_valid_bars: int


class ChunkSyncResult(DomainRecord):
    """What one chunked landing run did, symbol by symbol."""

    requested_symbols: tuple[str, ...]
    completed_symbols: tuple[str, ...]
    failed_symbols: tuple[str, ...]
    rows_written: int


class BootstrapSymbolCoverage(DomainRecord):
    """How much usable history one symbol ended up with."""

    symbol: str
    valid_bars: int
    satisfied: bool


class BootstrapSyncResult(DomainRecord):
    """The cold-start verdict for a set of symbols."""

    as_of: datetime
    requirement: BootstrapRequirement
    coverage: tuple[BootstrapSymbolCoverage, ...]
    failed_symbols: tuple[str, ...] = ()

    @property
    def satisfied_symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.coverage if item.satisfied)

    @property
    def short_symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.coverage if not item.satisfied)


class EnrichmentRequirement(DomainRecord):
    """The expensive enrichment a set of symbols still owes the strategy layer.

    Kept together with its symbol list so a caller cannot widen the population
    by accident: the requirement is about *these* symbols, and a run that
    enriches more than the Research Universe has stopped being the flow the
    approved semantics describe.
    """

    required_price_bars: int
    symbols: tuple[str, ...]


def strategy_history_requirement(factor_configs: Sequence[FactorConfig]) -> int:
    """Bars of history the *strategy* layer needs, from the configured windows.

    The answer is the longest trailing window any configured factor declares,
    with the extra bar a return factor needs for its starting point. Nothing
    here is a literal: adding a factor with a longer window raises the
    requirement the next time it is asked for.
    """
    required = 0
    for config in factor_configs:
        if "window" not in config.params:
            continue
        window = config.params["window"]
        if window is None:
            raise BootstrapRequirementNotConfigured(
                f"{config.name} declares no window (its 'window' parameter is "
                "null): the enrichment length cannot be derived and must not "
                "be guessed"
            )
        if window <= 0:
            raise BootstrapRequirementNotConfigured(
                f"{config.name} declares window {window}, which cannot describe "
                "a trailing window of bars"
            )
        needed = window + 1 if config.name.startswith(RETURN_FACTOR_PREFIX) else window
        required = max(required, needed)

    if required == 0:
        raise BootstrapRequirementNotConfigured(
            "no configured factor declares a price window, so there is no "
            "history requirement to satisfy"
        )
    return required


def _chunks(items: Sequence[str], size: int) -> Iterator[tuple[str, ...]]:
    for start in range(0, len(items), size):
        yield tuple(items[start : start + size])


def _bar_counts(path: Path, *, end_date: date, column: str) -> dict[str, int]:
    """Count every symbol's usable bars in **one** pass over the landed file.

    Reading the file once per symbol is what made the whole-market bootstrap
    spend half an hour in pure CPU after its fetches had finished: 5,301 symbols
    × a 97,641-row parse. Counting all symbols in a single pass is the same
    answer for the price of one read.
    """
    columns, rows = read_raw_rows(path)
    needed = (SYMBOL_COLUMN, TRADE_DATE_COLUMN, column)
    if not all(column in columns for column in needed):
        return {}
    symbol_at = columns.index(SYMBOL_COLUMN)
    date_at = columns.index(TRADE_DATE_COLUMN)
    value_at = columns.index(column)
    limit = end_date.isoformat()

    counts: dict[str, int] = {}
    for row in rows:
        if row[date_at] > limit or not row[value_at].strip():
            continue
        symbol = row[symbol_at]
        if symbol:
            counts[symbol] = counts.get(symbol, 0) + 1
    return counts


def _count_bars(path: Path, symbol: str, *, end_date: date, column: str) -> int:
    """One symbol's usable bar count, up to `end_date`."""
    return _bar_counts(path, end_date=end_date, column=column).get(symbol, 0)


def valid_amount_bars(path: Path, symbol: str, *, end_date: date) -> int:
    """Count the symbol's landed bars that carry an amount, up to `end_date`.

    The liquidity factor needs the amount column; a bar without it cannot
    contribute to the average. This is the count the bootstrap measures itself
    against — a calendar window never decides success.
    """
    return _count_bars(path, symbol, end_date=end_date, column="amount")


def _read_staged_parts(checkpoint: BootstrapCheckpoint) -> dict[str, RawPayload]:
    """Read the run's already-staged parts, keyed by the part's symbol.

    读分片是"每只标的小文件读一次"（O(标的数 × 单只行数)），与失败复盘里的
    "每只标的都把整份 `daily_bars.csv` 读一遍"是两件事：整份文件只在末尾合并时读写一次。
    """
    staged: dict[str, RawPayload] = {}
    for path in checkpoint.iter_part_files():
        columns, rows = read_raw_rows(path)
        if columns and rows:
            staged[path.stem] = RawPayload(columns=columns, rows=rows)
    return staged


def _payload_covers(payload: RawPayload, *, start_date: date, end_date: date) -> bool:
    """Whether a staged part already spans the requested window.

    判据与 `covered_symbols` 同源：分片里既有不晚于 `start_date` 的行、又有不早于
    `end_date` 的行。窗口加宽后这个条件不再成立，"续跑跳过"于是不会挡掉扩展抓取。
    """
    if TRADE_DATE_COLUMN not in payload.columns:
        return False
    index = payload.columns.index(TRADE_DATE_COLUMN)
    days = [row[index] for row in payload.rows if index < len(row) and row[index]]
    if not days:
        return False
    return min(days) <= start_date.isoformat() and max(days) >= end_date.isoformat()


def _is_staged_success(checkpoint: BootstrapCheckpoint, symbol: str) -> bool:
    entry = checkpoint.entry_for(symbol)
    return entry is not None and entry.status is BootstrapSymbolState.SUCCESS


def _attempt_landed(attempt: FallbackAttempt) -> bool:
    """一次 fallback 调用是否拿到了可以落盘的行。"""
    dataset = attempt.dataset
    return (
        not attempt.timed_out
        and dataset is not None
        and dataset.status is DataStatus.VALUE
        and dataset.payload is not None
        and bool(dataset.payload.rows)
    )


def _attempt_state(attempt: FallbackAttempt) -> BootstrapSymbolState:
    """Translate one attempt into its manifest state; a failure is never a success."""
    if attempt.timed_out:
        return BootstrapSymbolState.TIMEOUT
    if attempt.dataset is not None and attempt.dataset.status in _EMPTY_SOURCE_STATUSES:
        return BootstrapSymbolState.EMPTY
    return BootstrapSymbolState.SOURCE_ERROR


def _attempt_reason(attempt: FallbackAttempt) -> str:
    if attempt.error:
        return attempt.error
    if attempt.dataset is not None:
        return attempt.dataset.message or attempt.dataset.status.value
    return "no answer and no reason reported"


def _batch_rows_by_symbol(
    dataset: RawDataset,
) -> tuple[tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]], ...]:
    """一组批量数据集里按 symbol 归行的结果。

    批量接口的一份 payload 可能同时装着多只标的的行，所以归属只能看 `symbol` 列。没有这一
    列就无法把行归给谁，于是返回空——这些标的会落进缺口、由逐标的补缺再取一次，而不是被
    当成"批量已经覆盖"。
    """
    payload = dataset.payload
    if (
        dataset.status is not DataStatus.VALUE
        or payload is None
        or not payload.rows
        or SYMBOL_COLUMN not in payload.columns
    ):
        return ()
    index = payload.columns.index(SYMBOL_COLUMN)
    grouped: dict[str, list[tuple[str, ...]]] = {}
    for row in payload.rows:
        if index >= len(row) or not row[index]:
            continue
        grouped.setdefault(row[index], []).append(row)
    return tuple(
        (symbol, payload.columns, tuple(rows)) for symbol, rows in grouped.items()
    )


def _land_batch_round(
    *,
    batch_source: BatchMarketBarSource | None,
    checkpoint: BootstrapCheckpoint,
    pending: Sequence[str],
    as_of: datetime,
    start_date: date,
    end_date: date,
    batch_size: int,
) -> tuple[str, ...]:
    """Try the batch source first, staging every symbol it actually answered for.

    A batch answer is partial by nature (`missing_symbols` is explicit), so the
    return value is the set of symbols this round's batches covered. Everything
    the batch did not answer for — and everything it answered for outside the
    request — stays a gap for the per-symbol fallback. Nothing here ever
    fabricates a value for a symbol the source stayed silent about.
    """
    if batch_source is None or not pending:
        return ()

    covered: list[str] = []
    for chunk in _chunks(pending, batch_size):
        request = BootstrapBatchRequest(
            symbols=chunk, start_date=start_date, end_date=end_date, as_of=as_of
        )
        result = validate_bootstrap_batch_result(
            batch_source.fetch_recent_bars(request), as_of=as_of
        )
        asked = set(chunk)
        for dataset in result.datasets:
            for symbol, columns, rows in _batch_rows_by_symbol(dataset):
                if symbol not in asked:
                    continue
                checkpoint.record_success(
                    symbol, columns=columns, rows=rows, flush=False
                )
                covered.append(symbol)
        checkpoint.flush()
    return tuple(covered)


def land_bar_chunks(
    *,
    fallback_source: SymbolBarFallbackSource,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    checkpoint: BootstrapCheckpoint,
    batch_source: BatchMarketBarSource | None = None,
    batch_size: int = BATCH_REQUEST_SIZE,
    max_inflight: int = 1,
    operation_timeout_seconds: float = SYMBOL_TIMEOUT_SECONDS,
    tracker: BootstrapProgressTracker | None = None,
) -> ChunkSyncResult:
    """Land one range of bars for many symbols: batch first, then only the gaps.

    Each symbol's bars are staged as its own part file the moment it answers
    (`data/raw/bootstrap/<as-of>/parts/<symbol>.csv`) and its state goes into the
    run manifest, so a crash costs at most the symbols still in flight and a
    rerun resumes from what is already staged instead of re-fetching it. A
    symbol the source could not answer for is named in `failed_symbols`, gets a
    manifest entry with its reason, and lands no part: a failure never becomes an
    empty row, and it never discards the symbols that already succeeded.

    The batch source is tried first because a market-wide answer is the cheap
    path; the per-symbol fallback runs for the gaps only. There is no live batch
    provider in this repository (the 2026-09-18 probe concluded
    `NO_BATCH_PRIMARY_AVAILABLE`), so `batch_source=None` is the honest default
    and the fallback covers everything.

    The fallback runs on the bounded completion-order scheduler: at most
    `max_inflight` operations are active, results are consumed in completion
    order, and each result is checkpointed before the scheduler forgets it.
    `max_inflight` defaults to 1 — serial — because the source's rate-limit
    policy is `Deferred` in the design: turning concurrency on is an explicit,
    reviewed decision, not a default this function may take on its own.

    The canonical `daily_bars.csv` is merged **once per call**, from the run's
    successfully staged parts, not once per chunk. Rewriting the whole file after every chunk
    is what made the 2026-09-18 full-market run burn its time in I/O while the
    row count stood still; the merge cost must scale with the run, not with the
    chunk count.

    `tracker` 是整轮扩展共用的进度累计器：消化一只标的、in-flight 变化都从这条执行路径
    自己上报，心跳因此永远和真正在跑的流程一致。
    """
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    if max_inflight <= 0:
        raise ValueError(f"max_inflight must be positive, got {max_inflight}")
    if operation_timeout_seconds <= 0:
        raise ValueError(
            "operation_timeout_seconds must be positive, got "
            f"{operation_timeout_seconds}"
        )

    path = root / f"{BAR_DATASET}.csv"
    requested = tuple(dict.fromkeys(symbols))
    already = covered_symbols(path, start_date=start_date, end_date=end_date)
    staged = _read_staged_parts(checkpoint)
    # 续跑看的是"清单 + 已落盘分片"：清单说这只标的上一轮成功了、分片说它覆盖了本次窗口，
    # 才跳过；窗口加宽时分片不再覆盖，于是照常重抓。
    resumed = {
        symbol
        for symbol, payload in staged.items()
        if _is_staged_success(checkpoint, symbol)
        and _payload_covers(payload, start_date=start_date, end_date=end_date)
    }
    pending = [
        symbol
        for symbol in requested
        if symbol not in already and symbol not in resumed
    ]

    completed: list[str] = []
    failed: list[str] = []

    # 先批量。批量没覆盖到的（含它明确报的 missing_symbols）才是缺口。
    covered = _land_batch_round(
        batch_source=batch_source,
        checkpoint=checkpoint,
        pending=pending,
        as_of=as_of,
        start_date=start_date,
        end_date=end_date,
        batch_size=batch_size,
    )
    completed.extend(covered)
    if tracker is not None and covered:
        tracker.record(processed=len(covered))
    gaps = [symbol for symbol in pending if symbol not in set(covered)]

    if gaps:
        # 补缺走有界完成顺序调度：结果一到就落分片/记失败，调度器随后才提交下一只标的。
        def record(attempt: FallbackAttempt) -> None:
            if _attempt_landed(attempt):
                dataset = attempt.dataset
                assert dataset is not None and dataset.payload is not None
                checkpoint.record_success(
                    attempt.symbol,
                    columns=dataset.payload.columns,
                    rows=dataset.payload.rows,
                    flush=False,
                )
                completed.append(attempt.symbol)
                if tracker is not None:
                    tracker.record(processed=1)
                return
            checkpoint.record_failure(
                attempt.symbol,
                state=_attempt_state(attempt),
                error=_attempt_reason(attempt),
                flush=False,
            )
            failed.append(attempt.symbol)
            if tracker is not None:
                tracker.record(processed=1, failed=1)

        report_inflight: Callable[[int], None] | None = None
        if tracker is not None:

            def report(count: int) -> None:
                tracker.record(inflight=count)

            report_inflight = report

        fetch_symbols_bounded(
            source=fallback_source,
            symbols=gaps,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
            max_inflight=max_inflight,
            operation_timeout_seconds=operation_timeout_seconds,
            on_result=record,
            on_inflight=report_inflight,
        )

    # 落地调用结束前一定把清单落盘：跨轮、跨进程的续跑都只看磁盘上的清单。
    checkpoint.flush()

    # 整份文件只在这里被写一次，而且走 Task 7 的确定性压实（唯一 canonical 合并路径）：
    # 行数是本次合并写进去的行（含续跑补回的历史分片）。
    rows_written, _ = compact_bootstrap_run(checkpoint=checkpoint, canonical_path=path)

    return ChunkSyncResult(
        requested_symbols=requested,
        completed_symbols=tuple(completed),
        failed_symbols=tuple(failed),
        rows_written=rows_written,
    )


def bootstrap_liquidity_history(
    *,
    batch_source: BatchMarketBarSource | None,
    fallback_source: SymbolBarFallbackSource,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    requirement: BootstrapRequirement,
    end_date: date,
    batch_size: int = BATCH_REQUEST_SIZE,
    max_inflight: int = 1,
    operation_timeout_seconds: float = SYMBOL_TIMEOUT_SECONDS,
    progress: ProgressSink | None = None,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> BootstrapSyncResult:
    """Fetch the least history that lets the liquidity factor be measured."""
    return _extend_history(
        batch_source=batch_source,
        fallback_source=fallback_source,
        root=root,
        as_of=as_of,
        symbols=symbols,
        requirement=requirement,
        end_date=end_date,
        batch_size=batch_size,
        column="amount",
        max_inflight=max_inflight,
        operation_timeout_seconds=operation_timeout_seconds,
        progress=progress,
        heartbeat_seconds=heartbeat_seconds,
    )


def bootstrap_strategy_history(
    *,
    batch_source: BatchMarketBarSource | None,
    fallback_source: SymbolBarFallbackSource,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    required_price_bars: int,
    end_date: date,
    batch_size: int = BATCH_REQUEST_SIZE,
    max_inflight: int = 1,
    operation_timeout_seconds: float = SYMBOL_TIMEOUT_SECONDS,
    progress: ProgressSink | None = None,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> BootstrapSyncResult:
    """Fetch the price history the strategy layer needs, for these symbols only.

    Same resumable machinery as the liquidity bootstrap, counting bars that
    carry a close instead of an amount. Called with the Research Universe,
    which is what keeps expensive history off symbols that were never going to
    be researched.
    """
    return _extend_history(
        batch_source=batch_source,
        fallback_source=fallback_source,
        root=root,
        as_of=as_of,
        symbols=symbols,
        requirement=BootstrapRequirement(
            factor_name=PRICE_HISTORY_LABEL, required_valid_bars=required_price_bars
        ),
        end_date=end_date,
        batch_size=batch_size,
        column="close",
        max_inflight=max_inflight,
        operation_timeout_seconds=operation_timeout_seconds,
        progress=progress,
        heartbeat_seconds=heartbeat_seconds,
    )


def _extend_history(
    *,
    batch_source: BatchMarketBarSource | None,
    fallback_source: SymbolBarFallbackSource,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    requirement: BootstrapRequirement,
    end_date: date,
    column: str,
    batch_size: int = BATCH_REQUEST_SIZE,
    max_inflight: int = 1,
    operation_timeout_seconds: float = SYMBOL_TIMEOUT_SECONDS,
    progress: ProgressSink | None = None,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> BootstrapSyncResult:
    """Fetch a range, then widen it for whatever is still short.

    The first request is deliberately narrow — one calendar day per required
    bar — and the loop widens it for whichever symbols still fall short. The
    right-hand side of that sentence is a measured bar count, never a calendar
    span: weekends, holidays and gaps make the two different, and only the bar
    count is the quantity the factor actually consumes.

    The loop stops when a widening round adds nothing: the source has no more
    history to give, and the symbol is reported short rather than padded.
    """
    windows = requirement.required_valid_bars
    step = timedelta(days=windows * CALENDAR_DAYS_PER_REQUIRED_BAR)
    path = root / f"{BAR_DATASET}.csv"
    start_date = end_date - step

    # "要不要抓"看的是**实测 bar 数**，不是窗口边界。按窗口边界判会让一只标的
    # 永远判缺：窗口起点可能落在非交易日（例如周六），而标的的第一根 bar 只能是
    # 之后的第一个交易日，`earliest <= start` 于是永远不成立——实测中 400 只早已
    # 够数的标的因此被反复重抓，抓回来的数据文件里本来就有。
    # 检查点由调用方决定 `as_of` 与所需 bar 数，整轮扩展共用同一个：
    # 分片与清单跨轮累积，续跑与崩溃恢复都从"已落盘的那份"开始。
    checkpoint = BootstrapCheckpoint(
        root, as_of=as_of.date(), required_valid_bars=windows
    )
    # 进度只由本次 invocation 推导：总数就是这个调用点收到的标的集合。
    tracker = BootstrapProgressTracker(
        total=len(dict.fromkeys(symbols)),
        sink=progress,
        heartbeat_seconds=heartbeat_seconds,
    )
    counts = _bar_counts(path, end_date=end_date, column=column)
    short = [
        symbol for symbol in dict.fromkeys(symbols) if counts.get(symbol, 0) < windows
    ]
    failed: list[str] = []
    tracker.measure(
        satisfied=sum(
            1 for symbol in dict.fromkeys(symbols) if counts.get(symbol, 0) >= windows
        )
    )

    while short:
        result = land_bar_chunks(
            batch_source=batch_source,
            fallback_source=fallback_source,
            root=root,
            as_of=as_of,
            symbols=short,
            start_date=start_date,
            end_date=end_date,
            batch_size=batch_size,
            checkpoint=checkpoint,
            max_inflight=max_inflight,
            operation_timeout_seconds=operation_timeout_seconds,
            tracker=tracker,
        )
        failed.extend(item for item in result.failed_symbols if item not in failed)

        previous = {symbol: counts.get(symbol, 0) for symbol in short}
        counts = _bar_counts(path, end_date=end_date, column=column)
        tracker.measure(
            satisfied=sum(
                1
                for symbol in dict.fromkeys(symbols)
                if counts.get(symbol, 0) >= windows
            )
        )
        measured = {symbol: counts.get(symbol, 0) for symbol in short}
        still_short = [symbol for symbol, count in measured.items() if count < windows]
        if not still_short or measured == previous:
            break
        short = still_short
        start_date -= step

    tracker.finish()
    coverage = tuple(
        BootstrapSymbolCoverage(
            symbol=symbol,
            valid_bars=counts.get(symbol, 0),
            satisfied=counts.get(symbol, 0) >= windows,
        )
        for symbol in dict.fromkeys(symbols)
    )
    return BootstrapSyncResult(
        as_of=as_of,
        requirement=requirement,
        coverage=coverage,
        failed_symbols=tuple(failed),
    )


def liquidity_bootstrap_requirement(
    factor_configs: Sequence[FactorConfig],
) -> BootstrapRequirement:
    """Derive the bootstrap window from the configured liquidity factor.

    Only the factor's own window is consulted; the threshold it will be compared
    against lives in `configs/universe.yaml` and is not this module's business.
    """
    for config in factor_configs:
        if config.name != LIQUIDITY_FACTOR:
            continue
        window = config.params.get("window")
        if window is None:
            raise BootstrapRequirementNotConfigured(
                f"{LIQUIDITY_FACTOR} declares no window (its 'window' parameter "
                "is null): no reviewed window exists, so the bootstrap length "
                "cannot be derived and must not be guessed"
            )
        if window <= 0:
            raise BootstrapRequirementNotConfigured(
                f"{LIQUIDITY_FACTOR} declares window {window}, which cannot "
                "describe a trailing average"
            )
        return BootstrapRequirement(factor_name=config.name, required_valid_bars=window)

    raise BootstrapRequirementNotConfigured(
        f"no factor configuration for {LIQUIDITY_FACTOR}: the Universe's "
        "liquidity rule cannot be bootstrapped without the window its factor "
        "is defined over"
    )
