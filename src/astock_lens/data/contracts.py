"""Provider and normalization contracts."""

from datetime import date, datetime
from typing import Protocol, Self

from pydantic import model_validator

from astock_lens.data.dividends.models import DividendEvent
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import (
    DailyBar,
    DomainRecord,
    FinancialObservation,
    SecurityProfile,
    ValuationObservation,
)


class RawPayload(DomainRecord):
    """Source-shaped rows exactly as the provider delivered them.

    Every cell stays a string. `docs/ARCHITECTURE.md` requires the raw layer to
    preserve the source shape, and converting values is the normalizer's job —
    a provider that guessed types would be cleaning data it does not own.
    Columns and rows keep their source order so a row can be mapped back
    without a schema.
    """

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    @model_validator(mode="after")
    def _reject_ragged_rows(self) -> Self:
        """A short or long row means the file is not shaped as declared."""
        width = len(self.columns)
        for index, row in enumerate(self.rows):
            if len(row) != width:
                raise ValueError(
                    f"row {index} has {len(row)} cells but {width} columns are declared"
                )
        return self


class RawDataset(DomainRecord):
    """Fetch metadata for one provider dataset, plus its raw payload.

    Raw payloads keep the source shape; this record carries the metadata the
    architecture requires alongside them. `payload` is `None` when the fetch
    produced nothing — the `status` field then explains why, and callers must
    read it rather than assume an empty payload means an empty market.

    `missing_symbols` names the symbols the caller asked for that the source
    did not return. A source can quietly answer a batch partially — the
    WeStock CLI reports "success" even when some codes yielded nothing — so the
    gap is recorded here instead of being inferred from a row count.
    """

    provider: str
    dataset: str
    fetched_at: datetime
    provider_version: str
    status: DataStatus
    row_count: int
    missing_symbols: tuple[str, ...] = ()
    # Why a fetch is not complete, when that needs saying: a batch that failed,
    # a retry that gave up. `status` says *that* something is wrong; this says
    # what, so a long batch run is diagnosable without re-running it.
    message: str | None = None
    trade_date: date | None = None
    report_period: date | None = None
    payload: RawPayload | None = None


class FetchRequest(DomainRecord):
    """A point-in-time request for one provider dataset."""

    dataset: str
    as_of: datetime
    symbols: tuple[str, ...] | None = None
    start_date: date | None = None
    end_date: date | None = None


class ParseFailure(DomainRecord):
    """A raw cell or row the normalizer could not convert.

    Present so that "absent" and "corrupt" stay distinguishable: an empty cell
    is a missing value with no failure record, while unreadable text is a
    missing value *and* a record of why it is missing.
    """

    row_index: int
    column: str
    raw_value: str
    reason: str


class NormalizedDataset(DomainRecord):
    """Canonical-schema output of the Data Quality Gate.

    `parse_failures` records what the normalizer could not read. It is not a
    quality verdict — deciding whether a bar is usable belongs to the gate —
    only a statement about conversion.

    `securities` carries instrument identity rather than market data, so it is
    populated by the securities normalizer and left empty by the daily-bar
    normalizer. Keeping both on one record lets a single normalized dataset
    drive the Universe, which needs identity and prices together.
    """

    dataset: str
    as_of: datetime
    daily_bars: tuple[DailyBar, ...] = ()
    observations: tuple[FinancialObservation, ...] = ()
    valuations: tuple[ValuationObservation, ...] = ()
    securities: tuple[SecurityProfile, ...] = ()
    dividend_events: tuple[DividendEvent, ...] = ()
    parse_failures: tuple[ParseFailure, ...] = ()


class ProviderHealth(DomainRecord):
    """Provider availability and freshness report."""

    provider: str
    healthy: bool
    status: DataStatus
    checked_at: datetime
    message: str | None = None


class DataProvider(Protocol):
    """A bulk or research data source."""

    def health(self) -> ProviderHealth:
        """Report availability and freshness without fetching data."""
        ...

    def fetch(self, request: FetchRequest) -> RawDataset:
        """Fetch raw data for one request.

        Missing values must be returned as missing. A provider never
        substitutes a fabricated or zero value.
        """
        ...


class Normalizer(Protocol):
    """Convert raw provider output into canonical schemas."""

    def normalize(self, dataset: RawDataset, *, as_of: datetime) -> NormalizedDataset:
        """Normalize one raw dataset for a point in time.

        Records that cannot satisfy the time model are rejected, not silently
        repaired.
        """
        ...
