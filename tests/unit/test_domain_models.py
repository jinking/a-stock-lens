from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from astock_lens.domain.enums import (
    ACTIVE_WATCHLIST_STATES,
    RESERVED_WATCHLIST_STATES,
    DataStatus,
    ErrorSeverity,
    WatchlistState,
)
from astock_lens.domain.models import FinancialObservation


def test_financial_observation_rejects_future_availability() -> None:
    with pytest.raises(ValidationError):
        FinancialObservation(
            symbol="000001.SZ",
            metric="roe",
            value=10.0,
            report_period=date(2026, 6, 30),
            announce_date=date(2026, 8, 20),
            available_at=datetime(2026, 8, 20, tzinfo=UTC),
            as_of=datetime(2026, 8, 19, tzinfo=UTC),
            source="fixture",
        )


def test_architecture_enums_are_explicit() -> None:
    assert {item.value for item in DataStatus} == {
        "VALUE",
        "NULL",
        "STALE",
        "INVALID",
        "SOURCE_ERROR",
        "NOT_APPLICABLE",
    }
    assert {item.value for item in ErrorSeverity} == {"P0", "P1", "P2", "P3"}
    assert WatchlistState.DEEP_RESEARCH.value == "DEEP_RESEARCH"


def test_missing_financial_value_stays_none() -> None:
    observation = FinancialObservation(
        symbol="000001.SZ",
        metric="roe",
        value=None,
        report_period=date(2026, 6, 30),
        announce_date=date(2026, 8, 20),
        available_at=datetime(2026, 8, 20, tzinfo=UTC),
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        source="fixture",
    )

    assert observation.value is None


def test_naive_timestamps_are_rejected() -> None:
    """Naive timestamps must fail instead of comparing on an implicit offset."""
    with pytest.raises(ValidationError):
        FinancialObservation(
            symbol="000001.SZ",
            metric="roe",
            value=10.0,
            report_period=date(2026, 6, 30),
            announce_date=date(2026, 8, 20),
            # Naive on purpose: these two lines are the subject of the test.
            available_at=datetime(2026, 8, 20),  # noqa: DTZ001
            as_of=datetime(2026, 9, 1),  # noqa: DTZ001
            source="fixture",
        )


def test_watchlist_states_keep_active_and_reserved_apart() -> None:
    assert ACTIVE_WATCHLIST_STATES == {
        WatchlistState.DISCOVERED,
        WatchlistState.WATCH,
        WatchlistState.DEEP_RESEARCH,
        WatchlistState.TRACK_SIGNAL,
    }
    assert RESERVED_WATCHLIST_STATES == {
        WatchlistState.READY,
        WatchlistState.HOLDING,
        WatchlistState.EXITED,
        WatchlistState.ARCHIVED,
    }
    assert ACTIVE_WATCHLIST_STATES | RESERVED_WATCHLIST_STATES == set(WatchlistState)
