"""Eligibility-only scanners.

`docs/STRATEGY_SYSTEM.md` §5 defers every scanner's weights, score thresholds,
`rank_percentile` and `confidence`. Momentum shipped with a draft weight set
explicitly marked `PENDING REVIEW`; the scanners built here go one step further
and report **eligibility only**, because they have no reviewed weights at all.

That is a deliberate half-step, not a stub. Eligibility is a real verdict —
"this symbol's evidence is complete enough for this scanner to consider it" —
it is the first half of the funnel the design describes, and it is falsifiable.
A score would require a number nobody has approved, and a made-up threshold
reads downstream as a product judgement.

One class serves the scanners bound to it because, with scoring deferred, the
only thing that distinguishes them today is *which factors they demand* — and
that lives in `configs/strategies/*.yaml`, not here. When a scanner's weights
are reviewed it gets its own scoring implementation, and the registry binding
is the seam where that swap happens.
"""

from collections.abc import Sequence

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

SCORING_IS_DEFERRED = (
    "no score: this scanner's weights and thresholds have not been reviewed "
    "(docs/STRATEGY_SYSTEM.md §5)"
)


class EligibilityScanner:
    """The eligibility half of a scanner whose scoring is deferred."""

    def __init__(self, strategy_config: StrategyConfig) -> None:
        if not strategy_config.required_factors:
            raise ValueError(
                f"strategy {strategy_config.id!r} must declare required_factors; "
                "without them a scanner cannot tell 'eligible' from 'no evidence'"
            )
        if strategy_config.weights:
            raise ValueError(
                f"strategy {strategy_config.id!r} declares weights, but this "
                "implementation does not score; bind a scoring scanner instead"
            )
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
        """Report one symbol's evidence, with the ranking fields left empty."""
        return self._result(context, self.eligibility(context))

    def score_cross_section(
        self, contexts: Sequence[StrategyContext]
    ) -> tuple[StrategyResult, ...]:
        """Verdicts for a population, with no ranking.

        A percentile is a statement about relative position, and position along
        what is exactly the thing the design has not decided yet.
        """
        return tuple(
            self._result(context, self.eligibility(context)) for context in contexts
        )

    def explain(self, result: StrategyResult) -> Explanation:
        """Make the verdict expandable to factor level."""
        verdict = "eligible" if result.eligible else "not eligible"
        return Explanation(
            symbol=result.symbol,
            strategy_id=result.strategy_id,
            as_of=result.as_of,
            summary=(
                f"{result.strategy_id} {result.strategy_version}: {verdict}; "
                f"{SCORING_IS_DEFERRED}"
            ),
            factors=_notes(result.factor_snapshot),
        )

    def _result(
        self, context: StrategyContext, verdict: EligibilityResult
    ) -> StrategyResult:
        return StrategyResult(
            symbol=context.symbol,
            strategy_id=self._config.id,
            strategy_version=self._config.version,
            as_of=context.as_of,
            eligible=verdict.eligible,
            lineage=SnapshotLineage(strategy_version=self._config.version),
            score=None,
            rank_percentile=None,
            confidence=None,
            reasons=_describe(context.factors),
            risks=verdict.reasons,
            factor_snapshot=context.factors,
        )


def _notes(factors: tuple[FactorResult, ...]) -> tuple[FactorExplanation, ...]:
    """One line per factor, never inventing a value."""
    return tuple(
        FactorExplanation(
            factor=item.factor,
            note=(
                f"{item.raw_value}"
                if item.raw_value is not None
                else f"no value ({item.status})"
            ),
        )
        for item in factors
    )


def _describe(factors: tuple[FactorResult, ...]) -> tuple[str, ...]:
    """Return one human-readable line per factor, never inventing a value."""
    return tuple(
        f"{item.factor}={item.raw_value}"
        if item.raw_value is not None
        else f"{item.factor} is {item.status}"
        for item in factors
    )
