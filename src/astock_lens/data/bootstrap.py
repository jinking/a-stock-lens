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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

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
from astock_lens.factors.config import FactorConfig

# The Universe owns the name of the factor its liquidity rule consumes. It is
# imported rather than restated so the bootstrap can never measure a different
# quantity from the one the Universe compares against its floor.
from astock_lens.universe.builder import LIQUIDITY_FACTOR

# The dataset name the Universe's liquidity factor is bootstrapped from; bars
# land in the same file the rest of the pipeline reads.
BAR_DATASET = DEFAULT_BAR_DATASET


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


def _chunks(items: Sequence[str], size: int) -> Iterator[tuple[str, ...]]:
    for start in range(0, len(items), size):
        yield tuple(items[start : start + size])


def valid_amount_bars(path: Path, symbol: str, *, end_date: date) -> int:
    """Count the symbol's landed bars that carry an amount, up to `end_date`.

    The liquidity factor needs the amount column; a bar without it cannot
    contribute to the average. This is the count the bootstrap measures itself
    against — a calendar window never decides success.
    """
    columns, rows = read_raw_rows(path)
    needed = (SYMBOL_COLUMN, TRADE_DATE_COLUMN, "amount")
    if not all(column in columns for column in needed):
        return 0
    symbol_at = columns.index(SYMBOL_COLUMN)
    date_at = columns.index(TRADE_DATE_COLUMN)
    amount_at = columns.index("amount")
    limit = end_date.isoformat()

    return sum(
        1
        for row in rows
        if row[symbol_at] == symbol
        and row[date_at] <= limit
        and row[amount_at].strip() != ""
    )


def land_bar_chunks(
    *,
    provider: SymbolBarFetcher,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    chunk_size: int,
) -> ChunkSyncResult:
    """Land one range of bars for many symbols, one chunk at a time.

    A chunk is persisted as soon as it finishes, so a crash costs at most the
    chunk in flight. A symbol the source could not answer for is named in
    `failed_symbols` and lands nothing: a failure never becomes an empty row,
    and it never discards the symbols that already succeeded.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")

    path = root / f"{BAR_DATASET}.csv"
    requested = tuple(dict.fromkeys(symbols))
    already = covered_symbols(path, start_date=start_date, end_date=end_date)
    pending = [symbol for symbol in requested if symbol not in already]

    completed: list[str] = []
    failed: list[str] = []
    rows_written = 0

    for chunk in _chunks(pending, chunk_size):
        columns: tuple[str, ...] = ()
        rows: list[tuple[str, ...]] = []
        for symbol in chunk:
            dataset = provider.fetch_symbol_bars(
                symbol, as_of=as_of, start_date=start_date, end_date=end_date
            )
            payload = dataset.payload
            if (
                dataset.status is not DataStatus.VALUE
                or payload is None
                or not payload.rows
            ):
                failed.append(symbol)
                continue
            if not columns:
                columns = payload.columns
            rows.extend(payload.rows)
            completed.append(symbol)

        if rows and columns:
            written, _ = write_merged(
                path, RawPayload(columns=columns, rows=tuple(rows))
            )
            rows_written += written

    return ChunkSyncResult(
        requested_symbols=requested,
        completed_symbols=tuple(completed),
        failed_symbols=tuple(failed),
        rows_written=rows_written,
    )


def bootstrap_liquidity_history(
    *,
    provider: SymbolBarFetcher,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    requirement: BootstrapRequirement,
    end_date: date,
    chunk_size: int,
) -> BootstrapSyncResult:
    """Fetch the least history that lets the liquidity factor be measured.

    The first request is deliberately narrow — one calendar day per required
    bar — and the loop widens it for whichever symbols still fall short. The
    right-hand side of that sentence is a measured bar count, never a calendar
    span: weekends, holidays and gaps make the two different, and only the bar
    count is the quantity the factor actually consumes.

    The loop stops when a widening round adds nothing: the source has no more
    history to give, and the symbol is reported short rather than padded.
    """
    windows = requirement.required_valid_bars
    path = root / f"{BAR_DATASET}.csv"
    start_date = end_date - timedelta(days=windows)

    short = list(dict.fromkeys(symbols))
    failed: list[str] = []
    counted: dict[str, int] = {}

    while short:
        result = land_bar_chunks(
            provider=provider,
            root=root,
            as_of=as_of,
            symbols=short,
            start_date=start_date,
            end_date=end_date,
            chunk_size=chunk_size,
        )
        failed.extend(item for item in result.failed_symbols if item not in failed)

        measured = {
            symbol: valid_amount_bars(path, symbol, end_date=end_date)
            for symbol in short
        }
        if measured == counted:
            break
        counted = measured

        still_short = [symbol for symbol, count in measured.items() if count < windows]
        if not still_short:
            break
        short = still_short
        start_date -= timedelta(days=windows)

    coverage = tuple(
        BootstrapSymbolCoverage(
            symbol=symbol,
            valid_bars=count,
            satisfied=count >= windows,
        )
        for symbol, count in (
            (symbol, valid_amount_bars(path, symbol, end_date=end_date))
            for symbol in dict.fromkeys(symbols)
        )
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
