"""Trading calendar contracts and protocols."""

from datetime import date
from typing import Protocol


class TradingCalendar(Protocol):
    """Protocol for trading calendar operations."""

    def is_trade_date(self, target: date) -> bool:
        """Check whether the given date is an active trading day."""
        ...

    def get_latest_trade_date(self, target: date) -> date:
        """Return the latest trade date on or before the target date."""
        ...
