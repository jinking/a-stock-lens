"""Dataset freshness.

`docs/DATA_SOURCES.md` §4 requires Provider and Dataset freshness to be visible
in Data Health and in `astock doctor`. This module answers the dataset half of
that question from what is on disk: how many rows a raw file holds and the
range of trade dates it covers. It never fetches anything, so running it costs
nothing and cannot disturb a provider.

A file with no `trade_date` column reports no date range rather than a guessed
one — the securities listing is exactly that case.
"""

from datetime import date
from pathlib import Path

from astock_lens.data.sync import TRADE_DATE_COLUMN, read_raw_rows
from astock_lens.domain.models import DomainRecord

CSV_SUFFIX = ".csv"


class DatasetFreshness(DomainRecord):
    """How much data a raw dataset holds, and how recent it is.

    `unreadable_trade_dates` counts rows whose date could not be parsed. They
    are excluded from the range rather than silently dropped: a file with bad
    dates is a data problem worth seeing, and it must not quietly shorten the
    span the dataset appears to cover.
    """

    dataset: str
    path: Path
    rows: int
    first_trade_date: date | None = None
    last_trade_date: date | None = None
    unreadable_trade_dates: int = 0

    @property
    def covers_dates(self) -> bool:
        """Whether the file could name a date range at all."""
        return self.first_trade_date is not None


def dataset_freshness(root: Path, dataset: str) -> DatasetFreshness:
    """Report one dataset's size and date range, reading only the raw file."""
    path = root / f"{dataset}{CSV_SUFFIX}"
    columns, rows = read_raw_rows(path)
    if TRADE_DATE_COLUMN not in columns:
        return DatasetFreshness(dataset=dataset, path=path, rows=len(rows))

    index = columns.index(TRADE_DATE_COLUMN)
    parsed: list[date] = []
    unreadable = 0
    for row in rows:
        raw = row[index]
        if not raw:
            unreadable += 1
            continue
        try:
            parsed.append(date.fromisoformat(raw))
        except ValueError:
            unreadable += 1

    return DatasetFreshness(
        dataset=dataset,
        path=path,
        rows=len(rows),
        first_trade_date=min(parsed) if parsed else None,
        last_trade_date=max(parsed) if parsed else None,
        unreadable_trade_dates=unreadable,
    )


def raw_datasets(root: Path) -> tuple[DatasetFreshness, ...]:
    """Report every raw dataset under a root, in a stable order.

    An absent directory reports nothing rather than an error: "no raw data has
    been landed yet" is a state a fresh install is legitimately in.
    """
    if not root.is_dir():
        return ()
    return tuple(
        dataset_freshness(root, path.stem)
        for path in sorted(root.glob(f"*{CSV_SUFFIX}"))
    )
