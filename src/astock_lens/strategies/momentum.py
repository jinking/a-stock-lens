"""Momentum scanner.

Scope of this slice, stated plainly: the scanner decides **eligibility** and
explains what it saw. It does not rank.

`docs/ARCHITECTURE.md` §8.3 puts weights in YAML, and no weight has been
reviewed yet, so `score`, `rank_percentile`, and `confidence` stay `None`. A
plausible-looking number here would be a product decision made by accident.
"""

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import (
    EligibilityResult,
    Explanation,
    FactorExplanation,
    StrategyContext,
    StrategyResult,
)

SCORING_NOT_IMPLEMENTED = (
    "scoring requires whole-market percentiles and reviewed weights; "
    "this slice implements eligibility only"
)


class MomentumScanner:
    """Eligibility and explanation for the Momentum strategy."""

    def __init__(self, strategy_config: StrategyConfig) -> None:
        self._config = strategy_config

    def required_factors(self) -> set[str]:
        """Return the factor names this scanner needs."""
        return set(self._config.required_factors)

    def eligibility(self, context: StrategyContext) -> EligibilityResult:
        """Require every configured factor to carry an actual value."""
        observed = {result.factor: result for result in context.factors}
        reasons: list[str] = []

        for name in self._config.required_factors:
            result = observed.get(name)
            if result is None:
                reasons.append(f"{name} was not computed for this symbol")
            elif result.status is not DataStatus.VALUE:
                reasons.append(f"{name} is {result.status}, not VALUE")

        return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))

    def score(self, context: StrategyContext) -> StrategyResult:
        """Report the evidence and leave the ranking fields explicitly empty."""
        eligibility = self.eligibility(context)

        return StrategyResult(
            symbol=context.symbol,
            strategy_id=self._config.id,
            strategy_version=self._config.version,
            as_of=context.as_of,
            eligible=eligibility.eligible,
            lineage=SnapshotLineage(strategy_version=self._config.version),
            score=None,
            rank_percentile=None,
            confidence=None,
            reasons=_describe(context.factors),
            risks=eligibility.reasons,
            factor_snapshot=context.factors,
        )

    def explain(self, result: StrategyResult) -> Explanation:
        """Make the result expandable to factor level."""
        verdict = "eligible" if result.eligible else "not eligible"
        return Explanation(
            symbol=result.symbol,
            strategy_id=result.strategy_id,
            as_of=result.as_of,
            summary=(
                f"{result.strategy_id} {result.strategy_version}: {verdict}; "
                f"{SCORING_NOT_IMPLEMENTED}"
            ),
            factors=tuple(
                FactorExplanation(
                    factor=item.factor,
                    note=(
                        f"{item.raw_value}"
                        if item.raw_value is not None
                        else f"no value ({item.status})"
                    ),
                )
                for item in result.factor_snapshot
            ),
        )


def _describe(factors: tuple[FactorResult, ...]) -> tuple[str, ...]:
    """Return one human-readable line per factor, never inventing a value."""
    return tuple(
        f"{item.factor}={item.raw_value}"
        if item.raw_value is not None
        else f"{item.factor} is {item.status}"
        for item in factors
    )
