"""Provider and normalization contracts."""

from datetime import date, datetime
from typing import Protocol

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import (
    DailyBar,
    DomainRecord,
    FinancialObservation,
)


class RawDataset(DomainRecord):
    """Fetch metadata for one provider dataset.

    Raw payloads keep the source shape and are stored by the raw storage layer;
    this record carries only the metadata that the architecture requires
    alongside them.
    """

    provider: str
    dataset: str
    fetched_at: datetime
    provider_version: str
    status: DataStatus
    row_count: int
    trade_date: date | None = None
    report_period: date | None = None


class FetchRequest(DomainRecord):
    """A point-in-time request for one provider dataset."""

    dataset: str
    as_of: datetime
    symbols: tuple[str, ...] | None = None
    start_date: date | None = None
    end_date: date | None = None


class NormalizedDataset(DomainRecord):
    """Canonical-schema output of the Data Quality Gate."""

    dataset: str
    as_of: datetime
    daily_bars: tuple[DailyBar, ...] = ()
    observations: tuple[FinancialObservation, ...] = ()


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
