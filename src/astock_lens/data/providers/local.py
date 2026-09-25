"""Local CSV provider.

The offline counterpart of a network provider: every dataset is one CSV file
under a raw root, so the whole pipeline can be exercised with no network access
and the test suite never depends on a third-party service.

Two failure modes are kept apart on purpose:

- a **data** problem (missing file, empty file, undecodable bytes) is reported
  through `RawDataset.status` and never raised, because `ARCHITECTURE.md` §16
  requires provider problems to stay visible in Data Health instead of killing
  a scan;
- a **caller** problem (asking to filter on a column the file does not have) is
  a programming error and raises `ValueError`.
"""

import csv
from datetime import UTC, date, datetime
from pathlib import Path

from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.domain.enums import DataStatus

SYMBOL_COLUMN = "symbol"
TRADE_DATE_COLUMN = "trade_date"


class LocalCsvProvider:
    """Read one CSV file per dataset from a local raw directory."""

    def __init__(
        self,
        root: Path,
        *,
        provider: str = "local-csv",
        version: str = "v1",
    ) -> None:
        self._root = root
        self._provider = provider
        self._version = version

    def health(self) -> ProviderHealth:
        """Report whether the raw root exists. Reads nothing else."""
        checked_at = datetime.now(UTC)
        if not self._root.is_dir():
            return ProviderHealth(
                provider=self._provider,
                healthy=False,
                status=DataStatus.SOURCE_ERROR,
                checked_at=checked_at,
                message=f"raw root does not exist: {self._root}",
            )
        return ProviderHealth(
            provider=self._provider,
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=checked_at,
        )

    def fetch(
        self,
        request: FetchRequest,
        *,
        prior_landed: int = 0,
    ) -> RawDataset:
        """Read one dataset, applying only the filters the caller asked for.

        `prior_landed` is accepted for protocol compatibility; the local
        reader does not emit progress callbacks, so the value is unused.
        """
        del prior_landed  # unused: local reader does not report progress
        fetched_at = datetime.now(UTC)
        path = self._root / f"{request.dataset}.csv"

        if not path.is_file():
            return self._empty(request, fetched_at, DataStatus.SOURCE_ERROR)

        try:
            columns, rows = self._read(path)
        except (OSError, UnicodeDecodeError, csv.Error):
            return self._empty(request, fetched_at, DataStatus.SOURCE_ERROR)

        if not columns:
            return self._empty(request, fetched_at, DataStatus.NULL)

        if request.symbols is not None:
            index = self._column_index(
                columns,
                SYMBOL_COLUMN,
                dataset=request.dataset,
                purpose="symbol filtering",
            )
            wanted = set(request.symbols)
            rows = tuple(row for row in rows if row[index] in wanted)

        if request.start_date is not None or request.end_date is not None:
            rows = self._filter_by_date(rows, columns, request)

        report_period = None
        trade_date = self._single_value(columns, rows, TRADE_DATE_COLUMN)
        status = DataStatus.VALUE if rows else DataStatus.NULL

        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=status,
            row_count=len(rows),
            trade_date=trade_date,
            report_period=report_period,
            payload=RawPayload(columns=columns, rows=rows),
        )

    def _empty(
        self,
        request: FetchRequest,
        fetched_at: datetime,
        status: DataStatus,
        *,
        message: str | None = None,
    ) -> RawDataset:
        """Build the metadata-only record used for every empty outcome.

        `message` is not part of `RawDataset`; the status and `row_count` are
        what downstream health reporting reads.
        """
        del message
        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=status,
            row_count=0,
        )

    @staticmethod
    def _read(path: Path) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
        """Read every cell verbatim, with no type inference at all."""
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, None)
            if header is None:
                return (), ()
            return tuple(header), tuple(tuple(row) for row in reader)

    @staticmethod
    def _column_index(
        columns: tuple[str, ...],
        name: str,
        *,
        dataset: str,
        purpose: str,
    ) -> int:
        try:
            return columns.index(name)
        except ValueError as error:
            raise ValueError(
                f"dataset {dataset!r} has no {name!r} column, so {purpose} "
                f"cannot be applied; columns are {list(columns)}"
            ) from error

    @classmethod
    def _filter_by_date(
        cls,
        rows: tuple[tuple[str, ...], ...],
        columns: tuple[str, ...],
        request: FetchRequest,
    ) -> tuple[tuple[str, ...], ...]:
        """Filter on ISO dates.

        Trade dates are stored as `YYYY-MM-DD`, so lexicographic order is
        chronological order and no parsing is needed here.
        """
        index = cls._column_index(
            columns,
            TRADE_DATE_COLUMN,
            dataset=request.dataset,
            purpose="date filtering",
        )
        start = request.start_date.isoformat() if request.start_date else None
        end = request.end_date.isoformat() if request.end_date else None

        def keep(row: tuple[str, ...]) -> bool:
            value = row[index]
            if start is not None and value < start:
                return False
            return not (end is not None and value > end)

        return tuple(row for row in rows if keep(row))

    @staticmethod
    def _single_value(
        columns: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
        name: str,
    ) -> date | None:
        """Return the column value when every row agrees, else `None`.

        This never invents a date: a dataset spanning many trade dates reports
        no single `trade_date` rather than the first or last one.
        """
        if name not in columns:
            return None
        index = columns.index(name)
        values = {row[index] for row in rows}
        if len(values) != 1:
            return None
        try:
            return date.fromisoformat(next(iter(values)))
        except ValueError:
            return None
