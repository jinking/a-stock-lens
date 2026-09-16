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

# Financial statements are keyed the way their source keys them: the CLI's
# instrument code and the report period. `EndDate` is the period the numbers
# describe, which is what makes a re-landed statement replace its own row
# instead of appending a second copy of the same quarter.
FINANCIAL_KEYS: tuple[str, ...] = ("code", "EndDate")

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
    symbols_missing: tuple[str, ...] = ()
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


def landed_symbols(
    path: Path,
    *,
    as_of: datetime,
    symbol_column: str = SYMBOL_COLUMN,
    date_column: str = TRADE_DATE_COLUMN,
) -> frozenset[str]:
    """Return the symbols that already carry a row for the target date.

    A file without the columns needed to answer the question answers with
    nothing: guessing would either re-fetch everything or skip the wrong rows.
    """
    columns, rows = read_raw_rows(path)
    if symbol_column not in columns or date_column not in columns:
        return frozenset()

    symbol_index = columns.index(symbol_column)
    date_index = columns.index(date_column)
    day = as_of.date().isoformat()
    return frozenset(row[symbol_index] for row in rows if row[date_index] == day)


def read_symbols(path: Path, *, column: str = SYMBOL_COLUMN) -> tuple[str, ...]:
    """Return the symbols a landed file carries, deduplicated and ordered."""
    columns, rows = read_raw_rows(path)
    if column not in columns:
        return ()
    index = columns.index(column)
    return tuple(
        sorted({row[index] for row in rows if len(row) > index and row[index]})
    )


def land_financial_statements(
    *,
    provider: DataProvider,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    datasets: Sequence[str],
) -> SyncResult:
    """Land financial statements for the given symbols.

    Unlike the daily bars, a statement is not fetched for one date: the source
    answers with its most recent periods, and the publication date each row
    carries is what places it in time. So there is no "already landed" skip
    here. Re-landing is still safe: rows merge on `(code, EndDate)`, so a
    repeated run replaces the periods it fetched and appends the new ones.

    A freshness-based skip (for example "not again within N days") would need a
    cadence decision the design does not make, so it is left out rather than
    invented.
    """
    if not symbols:
        raise ValueError("landing financial statements needs at least one symbol")

    landings: list[DatasetLanding] = []
    for dataset in datasets:
        path = root / f"{dataset}.csv"
        raw = provider.fetch(
            FetchRequest(dataset=dataset, as_of=as_of, symbols=tuple(symbols))
        )
        payload = raw.payload
        if raw.status is not DataStatus.VALUE or payload is None or not payload.rows:
            landings.append(
                DatasetLanding(
                    dataset=dataset,
                    path=path,
                    status=raw.status,
                    rows_written=0,
                    rows_total=len(read_raw_rows(path)[1]),
                    symbols_missing=raw.missing_symbols or tuple(symbols),
                    # The provider's reason travels with the landing: a
                    # whole-market run that failed must be diagnosable without
                    # re-running it.
                    note=raw.message or raw.status.value,
                )
            )
            continue

        written, total = _write_merged(path, payload, keys=FINANCIAL_KEYS)
        landings.append(
            DatasetLanding(
                dataset=dataset,
                path=path,
                status=DataStatus.VALUE,
                rows_written=written,
                rows_total=total,
                symbols_missing=raw.missing_symbols,
                note=raw.message,
            )
        )

    return SyncResult(as_of=as_of, landings=tuple(landings))


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
        # A listing holds one row per instrument, so the instrument is its key.
        # Keying on every cell would append a second row whenever a field the
        # source reformats (a name, a listing date) changes.
        keys=(SYMBOL_COLUMN,),
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
    keys: Sequence[str] = (SYMBOL_COLUMN, TRADE_DATE_COLUMN),
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

    written, total = _write_merged(path, payload, keys=keys)
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


def _write_merged(
    path: Path,
    payload: RawPayload,
    *,
    keys: Sequence[str] = (SYMBOL_COLUMN, TRADE_DATE_COLUMN),
) -> tuple[int, int]:
    """Merge one payload into a raw file, replacing rows it already covers.

    The file widens to the union of both column sets. This source's shape
    depends on the instruments involved — a batch holding a bank carries
    balance-sheet columns a batch of manufacturers does not, and one holding an
    insurer carries a third set — so a whole-market file legitimately ends up
    with columns only some instruments report. A cell the row's own shape did
    not carry stays empty, which the normalizer reads as a missing value.

    What is still refused is mixing two *instruments of different kinds*: if
    the file and the payload do not share the key columns, one of them is not
    the dataset the other one is, and appending would corrupt both.
    """
    columns, rows = read_raw_rows(path)
    missing_keys = [key for key in keys if key not in payload.columns]
    if missing_keys:
        raise ValueError(
            f"the provider delivered {list(payload.columns)}, which lacks the "
            f"key columns {missing_keys}, so rows cannot be merged into {path}"
        )
    if columns:
        file_missing_keys = [key for key in keys if key not in columns]
        if file_missing_keys:
            raise ValueError(
                f"{path} has shape {list(columns)}, which lacks the key columns "
                f"{file_missing_keys}; refusing to merge a different dataset "
                "into it"
            )

    union = list(columns)
    union.extend(column for column in payload.columns if column not in union)
    if len(union) != len(set(union)):
        raise ValueError(
            f"the merged column set for {path} would contain duplicates: {union}"
        )

    widened = tuple(_pad(row, columns, union) for row in rows) if columns else ()
    incoming = tuple(_pad(row, payload.columns, union) for row in payload.rows)

    key_columns = _key_columns(tuple(union), keys)
    seen = {_key(row, key_columns) for row in incoming}
    kept = tuple(row for row in widened if _key(row, key_columns) not in seen)
    merged = (*kept, *incoming)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(union)
        writer.writerows(merged)

    return len(incoming), len(merged)


def _pad(
    row: tuple[str, ...], current: Sequence[str], target: Sequence[str]
) -> tuple[str, ...]:
    """Re-order one row onto a wider column set, filling what it never had."""
    if tuple(current) == tuple(target):
        return row
    position = {column: index for index, column in enumerate(target)}
    padded = [""] * len(target)
    for index, column in enumerate(current):
        if index < len(row):
            padded[position[column]] = row[index]
    return tuple(padded)


def _key_columns(columns: tuple[str, ...], keys: Sequence[str]) -> tuple[int, ...]:
    """Key a row by the named columns when they all exist, else by every cell."""
    if all(key in columns for key in keys):
        return tuple(columns.index(key) for key in keys)
    return tuple(range(len(columns)))


def _key(row: tuple[str, ...], indexes: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(row[index] for index in indexes)


def _listed_symbols(payload: RawPayload | None) -> tuple[str, ...]:
    """Return the symbols a listing carried, deduplicated and ordered."""
    if payload is None or SYMBOL_COLUMN not in payload.columns:
        return ()
    index = payload.columns.index(SYMBOL_COLUMN)
    return tuple(sorted({row[index] for row in payload.rows}))
