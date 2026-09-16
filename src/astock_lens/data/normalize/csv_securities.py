"""Normalize the securities master file into `SecurityProfile` records.

Every field here is an identity field. An unreadable exchange, listing date, or
board flag means the symbol cannot be aged or classified, so the whole row is
rejected and the reason recorded — a profile carrying a guessed `is_st` would
be indistinguishable from a checked one, and ST exclusion is not a rule anyone
wants applied on a guess.
"""

from datetime import date, datetime

from astock_lens.data.contracts import (
    NormalizedDataset,
    ParseFailure,
    RawDataset,
)
from astock_lens.domain.models import SecurityProfile

REQUIRED_COLUMNS = (
    "symbol",
    "name",
    "exchange",
    "list_date",
    "is_st",
    "is_delisting_board",
    "suspended_trading_days",
)

TRUE_FLAGS = frozenset({"true", "1", "yes", "y", "是"})
FALSE_FLAGS = frozenset({"false", "0", "no", "n", "否"})


class CsvSecurityNormalizer:
    """Turn a raw securities payload into canonical profiles."""

    def normalize(self, dataset: RawDataset, *, as_of: datetime) -> NormalizedDataset:
        """Convert one raw payload, rejecting rows it cannot fully read."""
        _require_timezone(as_of)

        payload = dataset.payload
        if payload is None or not payload.rows:
            return NormalizedDataset(dataset=dataset.dataset, as_of=as_of)

        missing = [name for name in REQUIRED_COLUMNS if name not in payload.columns]
        if missing:
            raise ValueError(
                f"securities payload is missing columns {missing}; "
                f"it declares {list(payload.columns)}"
            )

        index = {name: payload.columns.index(name) for name in REQUIRED_COLUMNS}

        profiles: list[SecurityProfile] = []
        failures: list[ParseFailure] = []

        for row_index, row in enumerate(payload.rows):
            profile, row_failures = _parse_row(row, index, row_index)
            if row_failures:
                failures.extend(row_failures)
            elif profile is not None:
                profiles.append(profile)

        return NormalizedDataset(
            dataset=dataset.dataset,
            as_of=as_of,
            securities=tuple(profiles),
            parse_failures=tuple(failures),
        )


def _parse_row(
    row: tuple[str, ...],
    index: dict[str, int],
    row_index: int,
) -> tuple[SecurityProfile | None, list[ParseFailure]]:
    """Parse one row, collecting every unreadable cell."""
    failures: list[ParseFailure] = []

    def read(column: str) -> str:
        return row[index[column]]

    def fail(column: str) -> None:
        failures.append(
            ParseFailure(
                row_index=row_index,
                column=column,
                raw_value=read(column),
                reason=f"{column} could not be read as its declared type",
            )
        )

    symbol = read("symbol").strip()
    if not symbol:
        fail("symbol")

    name = read("name").strip()
    if not name:
        fail("name")

    exchange = read("exchange").strip()
    if not exchange:
        fail("exchange")

    list_date = _parse_date(read("list_date"))
    if list_date is None:
        fail("list_date")

    is_st = _parse_flag(read("is_st"))
    if is_st is None:
        fail("is_st")

    is_delisting_board = _parse_flag(read("is_delisting_board"))
    if is_delisting_board is None:
        fail("is_delisting_board")

    suspended = _parse_int(read("suspended_trading_days"))
    if suspended is None:
        fail("suspended_trading_days")

    if failures:
        return None, failures

    # The reads above only reach here when every value parsed, so the narrowing
    # is a consequence of the checks rather than an assumption.
    assert list_date is not None
    assert is_st is not None
    assert is_delisting_board is not None
    assert suspended is not None

    return (
        SecurityProfile(
            symbol=symbol,
            name=name,
            exchange=exchange,
            list_date=list_date,
            is_st=is_st,
            is_delisting_board=is_delisting_board,
            suspended_trading_days=suspended,
        ),
        [],
    )


def _parse_date(raw: str) -> date | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_flag(raw: str) -> bool | None:
    text = raw.strip().lower()
    if text in TRUE_FLAGS:
        return True
    if text in FALSE_FLAGS:
        return False
    return None


def _parse_int(raw: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _require_timezone(as_of: datetime) -> None:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError(
            "as_of must be timezone-aware so normalization cannot hide an "
            "implicit offset"
        )
