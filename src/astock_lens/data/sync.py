"""Raw landing.

`spec §15` makes the first pipeline stage `SYNC_DATA` and requires it to be
incremental: "do not redownload full history every day when unchanged". This
module lands provider output into the raw directory the rest of the pipeline
reads, and it skips every symbol whose row for the target date is already
there.

Raw keeps the source's shape (`ARCHITECTURE.md` §4.2), so rows are written
exactly as delivered, in the provider's column order. Two rules keep the file
trustworthy:

- a provider failure writes nothing and is reported through the landing's
  status — a failed fetch never becomes an empty dataset on disk;
- a symbol whose row for the target date is already present is not fetched
  again, so the daily run stays incremental;
- when a payload is merged into a file, any row whose key the file already
  holds is replaced rather than appended, so replaying a payload cannot
  double-count.
"""

import csv
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from astock_lens.data.contracts import DataProvider, FetchRequest, RawPayload
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord

SYMBOL_COLUMN = "symbol"
TRADE_DATE_COLUMN = "trade_date"

DEFAULT_BAR_DATASET = "daily_bars"
DEFAULT_SECURITIES_DATASET = "securities"

# A landing is "done" when the data arrived, or when there was nothing new to
# fetch. Anything else — null, invalid, or a source error — is reported as an
# incomplete landing rather than a quiet success.
DONE_STATUSES: frozenset[DataStatus] = frozenset(
    {DataStatus.VALUE, DataStatus.NOT_APPLICABLE}
)


class DatasetLanding(DomainRecord):
    """What one dataset's landing did."""

    dataset: str
    path: Path
    status: DataStatus
    rows_written: int
    rows_total: int
    symbols_skipped: tuple[str, ...] = ()
    note: str | None = None


class SyncResult(DomainRecord):
    """What one sync run landed."""

    as_of: datetime
    landings: tuple[DatasetLanding, ...] = ()

    @property
    def failed_datasets(self) -> tuple[str, ...]:
        """Datasets that are not fully landed, in the order they were tried."""
        return tuple(
            landing.dataset
            for landing in self.landings
            if landing.status not in DONE_STATUSES
        )

    @property
    def is_complete(self) -> bool:
        """Whether every dataset is either landed or had nothing to fetch."""
        return not self.failed_datasets


def read_raw_rows(
    path: Path,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Read a raw CSV back verbatim; an absent file is empty, not an error."""
    if not path.is_file():
        return (), ()
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader, None)
        if header is None:
            return (), ()
        return tuple(header), tuple(tuple(row) for row in reader)


def landed_symbols(path: Path, *, as_of: datetime) -> frozenset[str]:
    """Return the symbols that already carry a row for the target date.

    A file without the columns needed to answer the question answers with
    nothing: guessing would either re-fetch everything or skip the wrong rows.
    """
    columns, rows = read_raw_rows(path)
    if SYMBOL_COLUMN not in columns or TRADE_DATE_COLUMN not in columns:
        return frozenset()

    symbol_index = columns.index(SYMBOL_COLUMN)
    date_index = columns.index(TRADE_DATE_COLUMN)
    day = as_of.date().isoformat()
    return frozenset(row[symbol_index] for row in rows if row[date_index] == day)


def land_raw(
    *,
    provider: DataProvider,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str] | None = None,
    bar_dataset: str = DEFAULT_BAR_DATASET,
    securities_dataset: str = DEFAULT_SECURITIES_DATASET,
) -> SyncResult:
    """Land the securities listing and one date of daily bars.

    When the caller names no symbols, the listing decides them: the probe and
    the request then come from the same source, so the scan cannot cover a
    different market than the one it says it covers.
    """
    listing = _land_dataset(
        provider=provider,
        root=root,
        as_of=as_of,
        dataset=securities_dataset,
        symbols=None,
    )
    wanted = tuple(symbols) if symbols is not None else _listed_symbols(listing.payload)

    bars = _land_dataset(
        provider=provider,
        root=root,
        as_of=as_of,
        dataset=bar_dataset,
        symbols=wanted,
    )
    return SyncResult(as_of=as_of, landings=(listing.landing, bars.landing))


class _Landed(DomainRecord):
    """One dataset's landing plus the payload the caller may read from it."""

    landing: DatasetLanding
    payload: RawPayload | None = None


def _land_dataset(
    *,
    provider: DataProvider,
    root: Path,
    as_of: datetime,
    dataset: str,
    symbols: Sequence[str] | None,
) -> _Landed:
    path = root / f"{dataset}.csv"
    requested = tuple(symbols) if symbols is not None else None
    skipped: tuple[str, ...] = ()

    if requested is not None:
        already = landed_symbols(path, as_of=as_of)
        skipped = tuple(sorted(already.intersection(requested)))
        requested = tuple(symbol for symbol in requested if symbol not in already)
        if not requested:
            return _Landed(
                landing=DatasetLanding(
                    dataset=dataset,
                    path=path,
                    status=DataStatus.NOT_APPLICABLE,
                    rows_written=0,
                    rows_total=len(read_raw_rows(path)[1]),
                    symbols_skipped=skipped,
                    note="every requested symbol already carries this date",
                )
            )

    raw = provider.fetch(FetchRequest(dataset=dataset, as_of=as_of, symbols=requested))
    payload = raw.payload
    if raw.status is not DataStatus.VALUE or payload is None or not payload.rows:
        return _Landed(
            landing=DatasetLanding(
                dataset=dataset,
                path=path,
                status=raw.status,
                rows_written=0,
                rows_total=len(read_raw_rows(path)[1]),
                symbols_skipped=skipped,
                note=(
                    raw.status.value
                    if raw.status is not DataStatus.VALUE
                    else DataStatus.NULL.value
                ),
            ),
            payload=payload,
        )

    written, total = _write_merged(path, payload)
    return _Landed(
        landing=DatasetLanding(
            dataset=dataset,
            path=path,
            status=DataStatus.VALUE,
            rows_written=written,
            rows_total=total,
            symbols_skipped=skipped,
        ),
        payload=payload,
    )


def _write_merged(path: Path, payload: RawPayload) -> tuple[int, int]:
    """Merge one payload into a raw file, replacing rows it already covers."""
    columns, rows = read_raw_rows(path)
    if columns and columns != payload.columns:
        raise ValueError(
            f"{path} has shape {list(columns)}, but the provider delivered "
            f"{list(payload.columns)}; refusing to mix two shapes in one file"
        )

    key_columns = _key_columns(payload.columns)
    seen = {_key(row, key_columns) for row in payload.rows}
    kept = tuple(row for row in rows if _key(row, key_columns) not in seen)
    merged = (*kept, *payload.rows)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(payload.columns)
        writer.writerows(merged)

    return len(payload.rows), len(merged)


def _key_columns(columns: tuple[str, ...]) -> tuple[int, ...]:
    """Key a row by symbol and date when both exist, else by every cell."""
    if SYMBOL_COLUMN in columns and TRADE_DATE_COLUMN in columns:
        return (columns.index(SYMBOL_COLUMN), columns.index(TRADE_DATE_COLUMN))
    return tuple(range(len(columns)))


def _key(row: tuple[str, ...], indexes: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(row[index] for index in indexes)


def _listed_symbols(payload: RawPayload | None) -> tuple[str, ...]:
    """Return the symbols a listing carried, deduplicated and ordered."""
    if payload is None or SYMBOL_COLUMN not in payload.columns:
        return ()
    index = payload.columns.index(SYMBOL_COLUMN)
    return tuple(sorted({row[index] for row in payload.rows}))
