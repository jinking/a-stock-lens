"""Strategy plugin contracts.

Seven independent V1 scanners share this contract. Strategies never call a data
provider directly and never collapse into one cross-strategy global score.
"""

from datetime import datetime
from typing import Protocol

from astock_lens.domain.enums import MarketRegime
from astock_lens.domain.models import DomainRecord, SnapshotLineage
from astock_lens.factors.contracts import FactorResult


class StrategyContext(DomainRecord):
    """Inputs available to a strategy evaluation."""

    symbol: str
    as_of: datetime
    factors: tuple[FactorResult, ...] = ()
    market_regime: MarketRegime | None = None


class EligibilityResult(DomainRecord):
    """Whether a symbol may enter a strategy, with the reasons why."""

    eligible: bool
    reasons: tuple[str, ...] = ()


class StrategyResult(DomainRecord):
    """One strategy outcome for one symbol at one point in time."""

    symbol: str
    strategy_id: str
    strategy_version: str
    as_of: datetime
    eligible: bool
    lineage: SnapshotLineage
    score: float | None = None
    rank_percentile: float | None = None
    confidence: float | None = None
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    factor_snapshot: tuple[FactorResult, ...] = ()


class FactorExplanation(DomainRecord):
    """Factor-level note that makes a score expandable."""

    factor: str
    note: str


class Explanation(DomainRecord):
    """Human-readable explanation of one strategy result."""

    symbol: str
    strategy_id: str
    as_of: datetime
    summary: str
    factors: tuple[FactorExplanation, ...] = ()


class StrategyPlugin(Protocol):
    """A V1 scanner."""

    def required_factors(self) -> set[str]:
        """Return the factor names this strategy needs."""
        ...

    def eligibility(self, context: StrategyContext) -> EligibilityResult:
        """Decide whether the symbol qualifies without scoring it."""
        ...

    def score(self, context: StrategyContext) -> StrategyResult:
        """Score an eligible symbol using factors only."""
        ...

    def explain(self, result: StrategyResult) -> Explanation:
        """Explain a result at factor level."""
        ...
