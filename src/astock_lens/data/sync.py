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
from datetime import date, datetime
from pathlib import Path

from astock_lens.data.contracts import DataProvider, FetchRequest, RawPayload
from astock_lens.data.industry import IndustryMembership, IndustrySource
from astock_lens.data.normalize.industry import (
    normalize_constituents,
    parse_sector_catalog,
)
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord

SYMBOL_COLUMN = "symbol"
TRADE_DATE_COLUMN = "trade_date"

DEFAULT_BAR_DATASET = "daily_bars"
DEFAULT_SECURITIES_DATASET = "securities"

# neodata 的落地根目录：`<raw_root>/neodata/<dataset>/<取数日>.csv`。
NEODATA_ROOT = "neodata"

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

        written, total = write_merged(path, payload, keys=FINANCIAL_KEYS)
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


INDUSTRY_ROOT = "westock/industry"
INDUSTRY_COLUMNS: tuple[str, ...] = (
    "symbol",
    "industry_id",
    "industry_name",
    "as_of",
    "provider",
    "source_ref",
)


def land_industry_memberships(
    *,
    source: "IndustrySource",
    root: Path,
    as_of: datetime,
) -> DatasetLanding:
    """把行业目录与成员关系落成一个按取数日命名的文件。

    目录先枚举再逐板块取成员，因此文件里的每一行都带着它是**哪个板块、哪一天**
    问来的。同一取数日重跑即覆盖，幂等。

    没有目录、或某个板块一行都没回来，都是失败而不是空文件：行业覆盖缺失会让
    校准报告少一整项证据。
    """
    catalog = parse_sector_catalog(source.catalog_text())
    if not catalog:
        raise ValueError("行业目录为空：没有可枚举的板块，无法建立成员映射")

    memberships: list[IndustryMembership] = []
    empty_boards: list[str] = []
    for entry in catalog:
        found = normalize_constituents(
            source.constituent_text(entry.industry_id),
            industry_id=entry.industry_id,
            industry_name=entry.industry_name,
            as_of=as_of,
            provider=source.provider,
        )
        if not found:
            empty_boards.append(entry.industry_id)
            continue
        memberships.extend(found)

    path = root / INDUSTRY_ROOT / f"{as_of.date().isoformat()}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(INDUSTRY_COLUMNS)
        for membership in memberships:
            writer.writerow(
                (
                    membership.symbol,
                    membership.industry_id,
                    membership.industry_name,
                    membership.as_of.isoformat(),
                    membership.provider,
                    membership.source_ref or "",
                )
            )

    note = None
    if empty_boards:
        note = (
            f"{len(empty_boards)} boards returned no constituents: {empty_boards[:5]}"
        )
    return DatasetLanding(
        dataset="industry",
        path=path,
        status=DataStatus.VALUE,
        rows_written=len(memberships),
        rows_total=len(memberships),
        note=note,
    )


def read_industry_memberships(path: Path) -> tuple["IndustryMembership", ...]:
    """读回一个已落地的行业文件，供映射与导出使用。"""
    columns, rows = read_raw_rows(path)
    if not columns:
        return ()
    missing = [column for column in INDUSTRY_COLUMNS if column not in columns]
    if missing:
        raise ValueError(f"{path} lacks the columns {missing}; it has {columns}")
    index = {column: columns.index(column) for column in INDUSTRY_COLUMNS}

    return tuple(
        IndustryMembership(
            symbol=row[index["symbol"]],
            industry_id=row[index["industry_id"]],
            industry_name=row[index["industry_name"]],
            as_of=datetime.fromisoformat(row[index["as_of"]]),
            provider=row[index["provider"]],
            source_ref=row[index["source_ref"]] or None,
        )
        for row in rows
    )


def land_neodata_blocks(
    *,
    provider: DataProvider,
    root: Path,
    dataset: str,
    values: Sequence[str],
    as_of: datetime,
) -> DatasetLanding:
    """把 neodata 的内容块按"数据集 + 取数日"落成一个文件。

    为什么按日而不是合并成一张大表：

    - 内容块是**逐字文本**（含多行 Markdown），合并进一张表会破坏溯源，
      也说不清"这一行是哪天问来的"；
    - 同一取数日重跑即覆盖，天然幂等；
    - 时点选择退化成"取不晚于 `as_of` 的最新一天"，与快照复现的原则一致。

    文件名即取数日，所以一次运行不会覆盖另一天的答案。
    """
    if not values:
        raise ValueError("落地 neodata 数据需要至少一个查询值")

    path = root / NEODATA_ROOT / dataset / f"{as_of.date().isoformat()}.csv"
    raw = provider.fetch(
        FetchRequest(dataset=dataset, as_of=as_of, symbols=tuple(values))
    )
    payload = raw.payload
    if raw.status is not DataStatus.VALUE or payload is None or not payload.rows:
        return DatasetLanding(
            dataset=dataset,
            path=path,
            status=raw.status,
            rows_written=0,
            rows_total=len(read_raw_rows(path)[1]),
            symbols_missing=raw.missing_symbols or tuple(values),
            note=raw.message or raw.status.value,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(payload.columns)
        writer.writerows(payload.rows)

    return DatasetLanding(
        dataset=dataset,
        path=path,
        status=DataStatus.VALUE,
        rows_written=len(payload.rows),
        rows_total=len(payload.rows),
        symbols_missing=raw.missing_symbols,
        note=raw.message,
    )


def latest_neodata_file(root: Path, dataset: str, *, as_of: datetime) -> Path | None:
    """不晚于 `as_of` 的最新一天的文件，没有则返回 `None`。

    文件名是 ISO 日期，字典序即时间序；未来日期的文件被排除，
    因此"今天不能看见明天的答案"这条规则由文件选择本身保证。
    """
    directory = root / NEODATA_ROOT / dataset
    if not directory.is_dir():
        return None
    limit = as_of.date().isoformat()
    candidates = sorted(
        path
        for path in directory.glob("*.csv")
        if _iso_day(path.stem) is not None and path.stem <= limit
    )
    return candidates[-1] if candidates else None


def _iso_day(value: str) -> str | None:
    """把文件名当作 ISO 日期校验，避免把杂物当成数据。"""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


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
    listing = _land_listing(
        provider=provider, root=root, as_of=as_of, dataset=securities_dataset
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


def land_securities_listing(
    *,
    provider: DataProvider,
    root: Path,
    as_of: datetime,
    dataset: str = DEFAULT_SECURITIES_DATASET,
) -> DatasetLanding:
    """Land the exchange listing alone, without fetching any per-symbol bars.

    A cold start needs the listing before it can decide which symbols deserve
    history, so the listing has to be landable on its own rather than only as
    the first half of `land_raw`.
    """
    return _land_listing(
        provider=provider, root=root, as_of=as_of, dataset=dataset
    ).landing


def _land_listing(
    *,
    provider: DataProvider,
    root: Path,
    as_of: datetime,
    dataset: str,
) -> "_Landed":
    """The listing landing, together with the payload the caller may read."""
    return _land_dataset(
        provider=provider,
        root=root,
        as_of=as_of,
        dataset=dataset,
        symbols=None,
        # A listing holds one row per instrument, so the instrument is its key.
        # Keying on every cell would append a second row whenever a field the
        # source reformats (a name, a listing date) changes.
        keys=(SYMBOL_COLUMN,),
    )


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

    written, total = write_merged(path, payload, keys=keys)
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


def covered_symbols(
    path: Path,
    *,
    start_date: date,
    end_date: date,
    symbol_column: str = SYMBOL_COLUMN,
    date_column: str = TRADE_DATE_COLUMN,
) -> frozenset[str]:
    """Symbols whose landed rows already span the requested range.

    Coverage is a question about the file, not about how the data got there: a
    symbol counts as covered when it holds a row on or before `start_date` and
    one on or after `end_date`. Asking for a wider window therefore makes every
    symbol honest again, which is what lets a bootstrap extend backward without
    re-fetching symbols that are already deep enough.
    """
    columns, rows = read_raw_rows(path)
    if symbol_column not in columns or date_column not in columns:
        return frozenset()
    symbol_at = columns.index(symbol_column)
    date_at = columns.index(date_column)

    earliest: dict[str, str] = {}
    latest: dict[str, str] = {}
    for row in rows:
        symbol, traded = row[symbol_at], row[date_at]
        if not symbol or not traded:
            continue
        earliest[symbol] = min(earliest.get(symbol, traded), traded)
        latest[symbol] = max(latest.get(symbol, traded), traded)

    first, last = start_date.isoformat(), end_date.isoformat()
    return frozenset(
        symbol
        for symbol in latest
        if earliest[symbol] <= first and latest[symbol] >= last
    )


def write_merged(
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
