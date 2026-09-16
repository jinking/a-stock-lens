"""Immutable domain records shared by every pipeline stage."""

from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class DomainRecord(BaseModel):
    """Base class for immutable domain records."""

    model_config = ConfigDict(frozen=True)


class DailyBar(DomainRecord):
    """Canonical daily bar.

    Numeric fields stay optional so a missing value is `None` instead of `0`.
    Deciding whether a bar is usable belongs to the Data Quality Gate, not to
    this record.
    """

    symbol: str
    trade_date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    pre_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    turnover_rate: float | None = None
    pct_change: float | None = None
    adj_factor: float | None = None


class SecurityProfile(DomainRecord):
    """A listed instrument's identity, as the securities master reports it.

    This lives in `domain` rather than in `universe` because the normalizer in
    `data` produces it: a `data → universe` import would reverse the dependency
    direction the architecture fixes.
    """

    symbol: str
    name: str
    exchange: str
    list_date: date
    is_st: bool = False
    is_delisting_board: bool = False
    # `None` means the source does not report suspension at all — an absence,
    # never a zero. Zero would be a factual claim that the stock is trading,
    # which the "no silent fallback" rule forbids. The Universe skips the
    # long-suspension rule for such profiles, so giving that rule a threshold
    # requires a source that reports the count first.
    suspended_trading_days: int | None = None


class FinancialObservation(DomainRecord):
    """Point-in-time financial metric.

    This is the canonical schema that `docs/ARCHITECTURE.md` names
    `FinancialMetric`. A historical computation is only allowed to use a record
    whose `available_at` is at or before the `as_of` it computes for.
    """

    symbol: str
    metric: str
    report_period: date
    announce_date: date | None
    available_at: datetime
    as_of: datetime
    source: str
    value: float | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def _reject_look_ahead(self) -> Self:
        """Enforce `available_at <= as_of` and reject ambiguous naive times."""
        for field_name, moment in (
            ("available_at", self.available_at),
            ("as_of", self.as_of),
        ):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError(
                    f"{field_name} must be timezone-aware so look-ahead bias "
                    "cannot hide behind an implicit offset"
                )
        if self.available_at > self.as_of:
            raise ValueError(
                "available_at must not be later than as_of: "
                f"{self.available_at.isoformat()} > {self.as_of.isoformat()}"
            )
        return self


class SnapshotLineage(DomainRecord):
    """Version and snapshot references reserved for every derived artifact.

    Time is carried by the artifact that owns the lineage, so lineage itself
    records only what is needed to reproduce the decision context: which
    universe snapshot, factor version, and strategy version were used.
    """

    universe_snapshot: str | None = None
    factor_version: str | None = None
    strategy_version: str | None = None
