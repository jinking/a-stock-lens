"""WeStock CLI provider for bulk financial statements.

Source decision (design spec §24, 2026-09-16): the Tencent WeStock CLI is the
only tested source that pairs a report period (`EndDate`) with a reliable
publication date (`InfoPublDate`) — `spec §5.1` requires both — and it fetches
a whole batch per call. Measured: 100 symbols in ~11s with full coverage, so a
whole-market quarterly refresh lands near the §21 target.

The CLI is an external command (`ARCHITECTURE.md` §4.1: no Python dependency on
`a-share-deep-research`, no reading of its internal state). Two details of that
command are load-bearing and are therefore pinned here rather than left to the
caller:

- `--fields all` is required. The default `core` field set omits
  `InfoPublDate`, and a financial record without a publication date cannot
  enter a point-in-time factor (`DATA_MODEL.md` §2).
- The CLI's own batch summary line is not trustworthy — it reports
  `成功: 1` whether one code or a hundred came back, and stays `success` when
  every code in the batch is invalid. Coverage is therefore established by
  comparing the codes requested with the codes present in the returned table,
  and the difference is reported through `RawDataset.missing_symbols`.
- **The source's shape depends on what is in the batch.** A batch containing a
  bank returns six extra columns (`Deposit`, `NonPerformingRatio`,
  `Level1CoreCapitalAdequacyRatio`, …) that a batch of manufacturers does not —
  measured on 2026-09-16 as 88 columns against 82. Batches are therefore merged
  on the *union* of their columns, and a cell the batch's shape did not carry
  stays an empty string: a missing value, never a zero. Treating that
  difference as corruption would throw away a whole statement because one batch
  happened to contain a bank, which is exactly what the first whole-market run
  did before this was measured.
- **A failed batch does not discard the others.** A batch that still fails
  after one retry is recorded in `message` and its symbols are named in
  `missing_symbols`; the rows the other batches delivered are landed anyway.

Failure modes, kept apart on purpose:

- a **caller** problem (unknown dataset, no symbols, a symbol without an
  exchange suffix) raises `ValueError`;
- a **source** problem (binary missing, non-zero exit, unreadable or reshaped
  output, no rows) becomes `RawDataset.status` with a row count that matches
  reality — never a fabricated row;
- a **partial** answer is reported rather than smoothed over: `missing_symbols`
  names what did not come back.

Raw cells stay verbatim strings: the source's table shape is preserved and no
value is converted, rounded, or repaired on the way in.
"""

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.domain.enums import DataStatus

BINARY_ENV = "ASTOCK_WESTOCK_BIN"
DEFAULT_BINARY = Path("tools/bin/westock")

# Dataset name → the statement the CLI serves.
FINANCIAL_DATASETS: Mapping[str, str] = {
    "financial_income": "income",
    "financial_balance": "balance",
    "financial_cashflow": "cashflow",
}

# See the module docstring: `core` omits the publication date.
FIELDS = "all"

CODE_COLUMN = "code"
REPORT_PERIOD_COLUMN = "EndDate"
PUBLISHED_COLUMN = "InfoPublDate"

# Canonical suffix ↔ the CLI's lowercase exchange prefix.
EXCHANGE_PREFIXES: Mapping[str, str] = {
    "SH": "sh",
    "SZ": "sz",
    "BJ": "bj",
}

DEFAULT_PERIODS = 8
DEFAULT_BATCH_SIZE = 100
DEFAULT_TIMEOUT_SECONDS = 120.0
# A long batch run meets transient failures. One retry costs seconds and turns
# a lost table into a hiccup; more would spin on a real outage.
DEFAULT_ATTEMPTS = 2

_SEPARATOR = "-"


class MalformedTable(ValueError):
    """The command printed something this provider cannot read as one table."""


@dataclass(frozen=True)
class CommandResult:
    """What one CLI invocation produced."""

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Table:
    """One markdown table, cells verbatim."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


Runner = Callable[[Sequence[str]], CommandResult]


def to_westock_code(symbol: str) -> str:
    """Map a canonical symbol onto the CLI's code, e.g. `600519.SH` → `sh600519`."""
    head, _, suffix = symbol.partition(".")
    prefix = EXCHANGE_PREFIXES.get(suffix.upper())
    if not prefix:
        raise ValueError(
            f"{symbol!r} has no exchange suffix this provider knows; expected "
            f"one of {sorted(EXCHANGE_PREFIXES)} after a dot (e.g. 600519.SH)"
        )
    return f"{prefix}{head}"


def from_westock_code(code: str) -> str:
    """Map the CLI's code back onto a canonical symbol, e.g. `sh600519` → `600519.SH`."""
    prefix, digits = code[:2].lower(), code[2:]
    for suffix, known in EXCHANGE_PREFIXES.items():
        if prefix == known:
            return f"{digits}.{suffix}"
    raise ValueError(f"{code!r} does not start with a known exchange prefix")


def parse_tables(text: str) -> tuple[Table, ...]:
    """Read every markdown table the command printed.

    The CLI's preamble and status lines are ignored: they are prose about the
    request, not data. A row whose width disagrees with its header raises,
    because a table this provider cannot read faithfully must not be published
    as a partially parsed one.
    """
    lines = text.splitlines()
    tables: list[Table] = []
    index = 0

    while index < len(lines):
        if not _is_row(lines[index]):
            index += 1
            continue
        header = _cells(lines[index])
        if index + 1 >= len(lines) or not _is_separator(lines[index + 1]):
            index += 1
            continue

        rows: list[tuple[str, ...]] = []
        cursor = index + 2
        while cursor < len(lines) and _is_row(lines[cursor]):
            row = _cells(lines[cursor])
            if len(row) != len(header):
                raise MalformedTable(
                    f"row {cursor + 1} has {len(row)} cells but the header "
                    f"declares {len(header)}"
                )
            rows.append(row)
            cursor += 1
        tables.append(Table(columns=header, rows=tuple(rows)))
        index = cursor

    return tuple(tables)


class WestockCliProvider:
    """Bulk financial statements from the Tencent WeStock CLI."""

    def __init__(
        self,
        binary: Path | str | None = None,
        *,
        periods: int = DEFAULT_PERIODS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        attempts: int = DEFAULT_ATTEMPTS,
        runner: Runner | None = None,
        provider: str = "westock-cli",
        version: str = "v1",
    ) -> None:
        if periods <= 0:
            raise ValueError(f"periods must be positive, got {periods}")
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        if attempts <= 0:
            raise ValueError(f"attempts must be positive, got {attempts}")

        configured = binary if binary is not None else os.getenv(BINARY_ENV)
        self._binary = Path(configured) if configured else DEFAULT_BINARY
        self._periods = periods
        self._batch_size = batch_size
        self._timeout = timeout
        self._attempts = attempts
        self._runner: Runner = runner if runner is not None else self._run
        self._provider = provider
        self._version = version

    def health(self) -> ProviderHealth:
        """Report whether the CLI is present without running it.

        `doctor` must stay read-only and fast, and liveness is only proven by a
        real fetch — the same rule the AkShare provider follows.
        """
        checked_at = datetime.now(UTC)
        if not self._binary.is_file():
            return ProviderHealth(
                provider=self._provider,
                healthy=False,
                status=DataStatus.SOURCE_ERROR,
                checked_at=checked_at,
                message=(
                    f"WeStock CLI not found at {self._binary}; install it or "
                    f"point {BINARY_ENV} at the binary"
                ),
            )
        if not os.access(self._binary, os.X_OK):
            return ProviderHealth(
                provider=self._provider,
                healthy=False,
                status=DataStatus.SOURCE_ERROR,
                checked_at=checked_at,
                message=f"{self._binary} is not executable",
            )
        return ProviderHealth(
            provider=self._provider,
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=checked_at,
            message="binary is present; liveness is only proven by a fetch",
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        """Fetch one financial statement for the requested symbols."""
        statement = FINANCIAL_DATASETS.get(request.dataset)
        if statement is None:
            raise ValueError(
                f"unknown dataset {request.dataset!r}; this provider serves "
                f"{sorted(FINANCIAL_DATASETS)}"
            )
        if request.symbols is None:
            raise ValueError(
                f"dataset {request.dataset!r} requires explicit symbols: the "
                "CLI takes a code list, and choosing the market is the "
                "Universe's decision, not this provider's"
            )
        if not request.symbols:
            raise ValueError(f"dataset {request.dataset!r} got an empty symbol list")

        fetched_at = datetime.now(UTC)
        symbols = tuple(dict.fromkeys(request.symbols))
        codes = {symbol: to_westock_code(symbol) for symbol in symbols}

        merged_columns: list[str] = []
        merged_rows: list[list[str]] = []
        returned: set[str] = set()
        failures: list[str] = []

        batches = _chunks(tuple(codes.values()), self._batch_size)
        for index, batch in enumerate(batches, start=1):
            argv = [
                str(self._binary),
                "finance",
                ",".join(batch),
                "--type",
                statement,
                "--limit",
                str(self._periods),
                "--fields",
                FIELDS,
            ]
            completed, failure = self._invoke(argv)
            if failure is not None:
                failures.append(
                    f"batch {index}/{len(batches)} ({batch[0]}..{batch[-1]}): {failure}"
                )
                continue

            try:
                tables = parse_tables(completed.stdout)
            except MalformedTable as error:
                failures.append(f"batch {index}/{len(batches)}: {error}")
                continue

            for table in tables:
                _merge(merged_columns, merged_rows, table)
                returned.update(_codes_in(table))

        summary = "; ".join(failures)
        if not merged_rows:
            return self._emptied(
                request,
                fetched_at,
                DataStatus.SOURCE_ERROR if failures else DataStatus.NULL,
                summary or "the source returned no rows for any requested symbol",
                missing=tuple(symbols),
            )

        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=DataStatus.VALUE,
            row_count=len(merged_rows),
            missing_symbols=tuple(
                symbol for symbol, code in codes.items() if code not in returned
            ),
            message=summary or None,
            report_period=_single(
                tuple(merged_columns), merged_rows, REPORT_PERIOD_COLUMN
            ),
            payload=RawPayload(
                columns=tuple(merged_columns),
                rows=tuple(tuple(row) for row in merged_rows),
            ),
        )

    def _invoke(self, argv: Sequence[str]) -> tuple[CommandResult, str | None]:
        """Run one batch, retrying a failed command once."""
        result = CommandResult(returncode=0, stdout="", stderr="")
        for _ in range(self._attempts):
            result = self._runner(argv)
            if result.returncode == 0:
                return result, None
        detail = result.stderr.strip()[:200] or "(no stderr)"
        return result, f"exited {result.returncode}: {detail}"

    def _emptied(
        self,
        request: FetchRequest,
        fetched_at: datetime,
        status: DataStatus,
        message: str,
        *,
        missing: tuple[str, ...] = (),
    ) -> RawDataset:
        """Build the metadata-only record every empty outcome shares."""
        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=status,
            row_count=0,
            missing_symbols=missing,
            message=message,
        )

    def _run(self, argv: Sequence[str]) -> CommandResult:
        """Run the CLI, turning process-level failures into a result."""
        try:
            completed = subprocess.run(
                list(argv),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                returncode=-1,
                stdout="",
                stderr=f"timed out after {self._timeout}s",
            )
        except OSError as error:
            return CommandResult(returncode=-1, stdout="", stderr=str(error))

        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _chunks(codes: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    """Split codes into batches the CLI can take in one call."""
    return tuple(codes[start : start + size] for start in range(0, len(codes), size))


def _merge(columns: list[str], rows: list[list[str]], table: Table) -> None:
    """Append one table to the merged table, widening it when needed.

    The source answers in a shape that depends on what the batch contains — a
    batch of banks carries columns a batch of manufacturers does not — so the
    merged table takes the union. Rows already collected are padded with empty
    cells, which the normalizer reads as a missing value rather than a zero.
    """
    new_columns = [column for column in table.columns if column not in columns]
    if new_columns:
        columns.extend(new_columns)
        for row in rows:
            row.extend([""] * len(new_columns))

    position = {column: index for index, column in enumerate(columns)}
    for source_row in table.rows:
        merged = [""] * len(columns)
        for source_index, column in enumerate(table.columns):
            merged[position[column]] = source_row[source_index]
        rows.append(merged)


def _codes_in(table: Table) -> frozenset[str]:
    """Return the codes a table carries, or nothing when it has no code column."""
    if CODE_COLUMN not in table.columns:
        return frozenset()
    index = table.columns.index(CODE_COLUMN)
    return frozenset(row[index] for row in table.rows if len(row) > index)


def _single(
    columns: tuple[str, ...],
    rows: Sequence[Sequence[str]],
    name: str,
) -> date | None:
    """Report a column value only when every row agrees on it.

    A statement spanning several periods reports no single `report_period`:
    guessing the first or last one would invent a date nobody declared.
    """
    if name not in columns:
        return None
    index = columns.index(name)
    values = {row[index] for row in rows if len(row) > index}
    if len(values) != 1:
        return None
    try:
        return date.fromisoformat(next(iter(values))[:10])
    except ValueError:
        return None


def _is_row(line: str) -> bool:
    return line.strip().startswith("|")


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(
        set(cell) <= {_SEPARATOR, ":"} and _SEPARATOR in cell for cell in cells
    )


def _cells(line: str) -> tuple[str, ...]:
    """Split one markdown row into verbatim cells."""
    stripped = line.strip()
    stripped = stripped.removeprefix("|")
    stripped = stripped.removesuffix("|")
    return tuple(cell.strip() for cell in stripped.split("|"))
