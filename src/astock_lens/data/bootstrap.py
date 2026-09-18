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

from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from astock_lens.data.bootstrap_checkpoint import (
    BootstrapCheckpoint,
    BootstrapSymbolState,
)
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.sync import (
    DEFAULT_BAR_DATASET,
    SYMBOL_COLUMN,
    TRADE_DATE_COLUMN,
    covered_symbols,
    read_raw_rows,
    write_merged,
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

# How long one symbol's fetch may occupy a worker before the chunk gives up on
# it. Measured 2026-09-18: a resume run sat with 0% CPU, one open TCP connection
# and an empty log for minutes because a network call never returned and the
# chunk waited for every future. With this bound the chunk always finishes and
# persists what answered; the straggler is recorded as a failure and retried by
# the next round. Technical bound, not a product threshold.
SYMBOL_TIMEOUT_SECONDS = 60.0


class BootstrapRequirementNotConfigured(RuntimeError):
    """Raised when no reviewed liquidity window can be resolved from config."""


class BootstrapRequirement(DomainRecord):
    """How much price history the liquidity rule needs before it can be applied."""

    factor_name: str
    required_valid_bars: int


@runtime_checkable
class SymbolBarFetcher(Protocol):
    """A provider that can answer for one symbol at a time.

    The bootstrap needs this narrower contract than `DataProvider`: isolation
    between symbols is only possible when a provider reports one symbol's
    failure without discarding its neighbours.
    """

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        """Fetch one symbol's bars for a range, reporting failure as a status."""
        ...


class ChunkSyncResult(DomainRecord):
    """What one chunked landing run did, symbol by symbol."""

    requested_symbols: tuple[str, ...]
    completed_symbols: tuple[str, ...]
    failed_symbols: tuple[str, ...]
    rows_written: int


@dataclass(frozen=True)
class _SymbolFetch:
    """一块里一只标的的取数结果：数据本身，以及它是不是超时的那一只。

    超时与来源报错都表现为失败数据集，但清单状态不同（`TIMEOUT` / `SOURCE_ERROR`），
    所以"为什么失败"必须跟着结果一起传下去，不能靠消息文本反推。
    """

    symbol: str
    dataset: RawDataset
    timed_out: bool = False


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


def _union_payloads(payloads: Sequence[RawPayload]) -> RawPayload | None:
    """Fold several staged parts into one payload: column union, rows in order.

    列取并集（供应商对不同标的的字段形状可能不同，缺的格子留空，由规范化阶段读作缺失），
    行按分片顺序拼接；同一标的只会出现一次，所以不会把同一根 bar 写进两份。
    """
    parts: list[RawPayload] = []
    union: list[str] = []
    for payload in payloads:
        if not payload.rows:
            continue
        for column in payload.columns:
            if column not in union:
                union.append(column)
        parts.append(payload)
    if not parts:
        return None

    columns = tuple(union)
    position = {column: index for index, column in enumerate(columns)}
    rows: list[tuple[str, ...]] = []
    for payload in parts:
        for row in payload.rows:
            folded = [""] * len(columns)
            for index, column in enumerate(payload.columns):
                if index < len(row):
                    folded[position[column]] = row[index]
            rows.append(tuple(folded))
    return RawPayload(columns=columns, rows=tuple(rows))


def _is_staged_success(checkpoint: BootstrapCheckpoint, symbol: str) -> bool:
    entry = checkpoint.entry_for(symbol)
    return entry is not None and entry.status is BootstrapSymbolState.SUCCESS


def _failure_state(fetch: _SymbolFetch) -> BootstrapSymbolState:
    """Translate one fetch into its manifest state; a failure is never a success."""
    if fetch.timed_out:
        return BootstrapSymbolState.TIMEOUT
    if fetch.dataset.status in _EMPTY_SOURCE_STATUSES:
        return BootstrapSymbolState.EMPTY
    return BootstrapSymbolState.SOURCE_ERROR


def _failure_reason(fetch: _SymbolFetch) -> str:
    return fetch.dataset.message or fetch.dataset.status.value


def land_bar_chunks(
    *,
    provider: SymbolBarFetcher,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    chunk_size: int,
    checkpoint: BootstrapCheckpoint,
    max_workers: int = 1,
    symbol_timeout_seconds: float = SYMBOL_TIMEOUT_SECONDS,
) -> ChunkSyncResult:
    """Land one range of bars for many symbols, one chunk at a time.

    Each symbol's bars are staged as its own part file the moment it answers
    (`data/raw/bootstrap/<as-of>/parts/<symbol>.csv`) and its state goes into the
    run manifest, so a crash costs at most the symbols still in flight and a
    rerun resumes from what is already staged instead of re-fetching it. A
    symbol the source could not answer for is named in `failed_symbols`, gets a
    manifest entry with its reason, and lands no part: a failure never becomes an
    empty row, and it never discards the symbols that already succeeded.

    The canonical `daily_bars.csv` is merged **once per call**, from the run's
    staged parts, not once per chunk. Rewriting the whole file after every chunk
    is what made the 2026-09-18 full-market run burn its time in I/O while the
    row count stood still; the merge cost must scale with the run, not with the
    chunk count.

    `max_workers` fetches a chunk's symbols concurrently. It defaults to 1 —
    serial — because the source's rate-limit policy is `Deferred` in the design:
    turning concurrency on is an explicit, reviewed decision, not a default this
    function may take on its own. Concurrency changes only how fast a chunk is
    fetched; each symbol still has to answer for itself, and failures are still
    recorded per symbol.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    if max_workers <= 0:
        raise ValueError(f"max_workers must be positive, got {max_workers}")
    if symbol_timeout_seconds <= 0:
        raise ValueError(
            f"symbol_timeout_seconds must be positive, got {symbol_timeout_seconds}"
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

    for chunk in _chunks(pending, chunk_size):
        fetched = _fetch_chunk(
            provider=provider,
            chunk=chunk,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
            max_workers=max_workers,
            symbol_timeout_seconds=symbol_timeout_seconds,
        )
        for fetch in fetched:
            payload = fetch.dataset.payload
            # 只有"没超时、状态是 VALUE、而且真的带了行"才算成功；其余一律记账。
            columns = payload.columns if payload is not None else ()
            rows = payload.rows if payload is not None else ()
            if (
                not fetch.timed_out
                and fetch.dataset.status is DataStatus.VALUE
                and columns
                and rows
            ):
                checkpoint.record_success(fetch.symbol, columns=columns, rows=rows)
                staged[fetch.symbol] = RawPayload(columns=columns, rows=rows)
                completed.append(fetch.symbol)
                continue
            checkpoint.record_failure(
                fetch.symbol,
                state=_failure_state(fetch),
                error=_failure_reason(fetch),
            )
            failed.append(fetch.symbol)

    rows_written = 0
    # 整份文件只在这里被写一次：行数是本次合并写进去的行（含续跑补回的历史分片）。
    merged = _union_payloads(list(staged.values()))
    if merged is not None:
        rows_written, _ = write_merged(path, merged)

    return ChunkSyncResult(
        requested_symbols=requested,
        completed_symbols=tuple(completed),
        failed_symbols=tuple(failed),
        rows_written=rows_written,
    )


def _fetch_chunk(
    *,
    provider: SymbolBarFetcher,
    chunk: Sequence[str],
    as_of: datetime,
    start_date: date,
    end_date: date,
    max_workers: int,
    symbol_timeout_seconds: float,
) -> tuple[_SymbolFetch, ...]:
    """Fetch one chunk, in the chunk's own symbol order.

    The order is what keeps the landed file stable: the same inputs produce the
    same rows in the same sequence whether the chunk was fetched serially or
    concurrently.
    """
    # 不用 `with`：上下文管理器退出时会 join 所有线程，挂住的请求会把整块拖回原样。
    # 这里显式 shutdown(wait=False)：被放弃的请求留在线程里自生自灭，块照常结束。
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {
            symbol: pool.submit(
                provider.fetch_symbol_bars,
                symbol,
                as_of=as_of,
                start_date=start_date,
                end_date=end_date,
            )
            for symbol in chunk
        }
        results: list[_SymbolFetch] = []
        for symbol in chunk:
            try:
                results.append(
                    _SymbolFetch(
                        symbol,
                        futures[symbol].result(timeout=symbol_timeout_seconds),
                    )
                )
            except TimeoutError:
                # 这一只没有按时回答：按超时记账，块照常结束（绝不是网络 timeout 的声明）。
                results.append(
                    _SymbolFetch(symbol, _timeout_dataset(symbol), timed_out=True)
                )
            except Exception as error:  # noqa: BLE001 — one symbol's failure
                results.append(
                    _SymbolFetch(
                        symbol,
                        RawDataset(
                            provider="unknown",
                            dataset=BAR_DATASET,
                            fetched_at=datetime.now(UTC),
                            provider_version="unknown",
                            status=DataStatus.SOURCE_ERROR,
                            row_count=0,
                            message=f"{symbol} raised while fetching: {error}",
                        ),
                    )
                )
        return tuple(results)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def bootstrap_liquidity_history(
    *,
    provider: SymbolBarFetcher,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    requirement: BootstrapRequirement,
    end_date: date,
    chunk_size: int,
    max_workers: int = 1,
) -> BootstrapSyncResult:
    """Fetch the least history that lets the liquidity factor be measured."""
    return _extend_history(
        provider=provider,
        root=root,
        as_of=as_of,
        symbols=symbols,
        requirement=requirement,
        end_date=end_date,
        chunk_size=chunk_size,
        column="amount",
        max_workers=max_workers,
    )


def bootstrap_strategy_history(
    *,
    provider: SymbolBarFetcher,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    required_price_bars: int,
    end_date: date,
    chunk_size: int,
    max_workers: int = 1,
) -> BootstrapSyncResult:
    """Fetch the price history the strategy layer needs, for these symbols only.

    Same resumable machinery as the liquidity bootstrap, counting bars that
    carry a close instead of an amount. Called with the Research Universe,
    which is what keeps expensive history off symbols that were never going to
    be researched.
    """
    return _extend_history(
        provider=provider,
        root=root,
        as_of=as_of,
        symbols=symbols,
        requirement=BootstrapRequirement(
            factor_name=PRICE_HISTORY_LABEL, required_valid_bars=required_price_bars
        ),
        end_date=end_date,
        chunk_size=chunk_size,
        column="close",
        max_workers=max_workers,
    )


def _extend_history(
    *,
    provider: SymbolBarFetcher,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    requirement: BootstrapRequirement,
    end_date: date,
    chunk_size: int,
    column: str,
    max_workers: int = 1,
    symbol_timeout_seconds: float = SYMBOL_TIMEOUT_SECONDS,
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
    counts = _bar_counts(path, end_date=end_date, column=column)
    short = [
        symbol for symbol in dict.fromkeys(symbols) if counts.get(symbol, 0) < windows
    ]
    failed: list[str] = []

    while short:
        result = land_bar_chunks(
            provider=provider,
            root=root,
            as_of=as_of,
            symbols=short,
            start_date=start_date,
            end_date=end_date,
            chunk_size=chunk_size,
            checkpoint=checkpoint,
            max_workers=max_workers,
            symbol_timeout_seconds=symbol_timeout_seconds,
        )
        failed.extend(item for item in result.failed_symbols if item not in failed)

        previous = {symbol: counts.get(symbol, 0) for symbol in short}
        counts = _bar_counts(path, end_date=end_date, column=column)
        measured = {symbol: counts.get(symbol, 0) for symbol in short}
        still_short = [symbol for symbol, count in measured.items() if count < windows]
        if not still_short or measured == previous:
            break
        short = still_short
        start_date -= step

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


def _timeout_dataset(symbol: str) -> RawDataset:
    """一个标的超过时限仍未返回：按失败记账，交给下一轮重试。"""
    return RawDataset(
        provider="unknown",
        dataset=BAR_DATASET,
        fetched_at=datetime.now(UTC),
        provider_version="unknown",
        status=DataStatus.SOURCE_ERROR,
        row_count=0,
        message=(
            f"{symbol} did not answer within the fetch time bound; recorded as a "
            "failure so the chunk can finish and the next round can retry it"
        ),
    )
