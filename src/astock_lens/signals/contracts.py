"""Signal engine contracts.

Signals describe market state. They carry no valuation or fundamental
judgement and are not recommendations.
"""

from datetime import datetime
from typing import Protocol

from astock_lens.domain.enums import MarketRegime, Signal
from astock_lens.domain.models import DomainRecord, SnapshotLineage
from astock_lens.factors.contracts import FactorResult


class SignalContext(DomainRecord):
    """Inputs available to signal detection."""

    symbol: str
    as_of: datetime
    factors: tuple[FactorResult, ...] = ()
    market_regime: MarketRegime | None = None
    strategy_id: str | None = None


class SignalResult(DomainRecord):
    """Detected market state for one symbol at one point in time."""

    symbol: str
    signal: Signal
    as_of: datetime
    strategy_id: str
    lineage: SnapshotLineage
    reasons: tuple[str, ...] = ()


class SignalDetector(Protocol):
    """A signal detector."""

    def detect(self, context: SignalContext) -> SignalResult:
        """Detect the market state for a symbol."""
        ...
