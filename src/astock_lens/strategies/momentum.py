"""Momentum scanner.

Eligibility, cross-sectional ranking, and explanation — in that order.

`score(context)` answers for a single symbol, and a percentile needs a
population, so it reports eligibility and leaves the ranking fields `None`.
That is the honest answer rather than a constant dressed up as a measurement.
`score_cross_section(contexts)` performs the actual ranking, reading its
weights from configuration (`docs/ARCHITECTURE.md` §8.3).

`confidence` stays `None` on both paths. The design requires the field but
defines no algorithm for it, and because eligibility already demands every
configured factor, a "fraction of factors present" definition would return a
constant `1.0` — a field that looks informative and is not.
"""

from collections.abc import Sequence

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import (
    EligibilityResult,
    Explanation,
    FactorContribution,
    FactorExplanation,
    StrategyContext,
    StrategyResult,
)
from astock_lens.strategies.scoring import percentile_ranks

SCORING_NEEDS_A_POPULATION = (
    "scoring needs a cross-section; this result covers eligibility only"
)

SCORE_CEILING = 100.0


class MomentumScanner:
    """Eligibility, ranking, and explanation for the Momentum strategy."""

    def __init__(self, strategy_config: StrategyConfig) -> None:
        self._config = strategy_config
        self._weights = _validated_weights(strategy_config)

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
        return self._result(
            context,
            self.eligibility(context),
            score=None,
            rank_percentile=None,
            contributions=(),
        )

    def score_cross_section(
        self, contexts: Sequence[StrategyContext]
    ) -> tuple[StrategyResult, ...]:
        """Rank a population of symbols against each other.

        Only eligible symbols enter the population. A symbol with a missing
        factor would otherwise shift everyone else's percentile while never
        being scored itself, which is how a ranking quietly stops meaning what
        it says.
        """
        if not contexts:
            return ()

        symbols = [context.symbol for context in contexts]
        if len(set(symbols)) != len(symbols):
            raise ValueError(
                "score_cross_section expects at most one context per symbol; "
                f"got {symbols}"
            )

        verdicts = [self.eligibility(context) for context in contexts]

        if not self._weights:
            return tuple(
                self._result(
                    context,
                    verdict,
                    score=None,
                    rank_percentile=None,
                    contributions=(),
                )
                for context, verdict in zip(contexts, verdicts, strict=True)
            )

        population = [
            context
            for context, verdict in zip(contexts, verdicts, strict=True)
            if verdict.eligible
        ]

        percentiles = {
            name: percentile_ranks(
                {context.symbol: _value_of(context, name) for context in population}
            )
            for name in self._weights
        }
        total_weight = sum(self._weights.values())

        blends = {
            context.symbol: sum(
                self._weights[name] * percentiles[name][context.symbol]
                for name in self._weights
            )
            / total_weight
            for context in population
        }

        # A population of one has no one to be ranked against, so the rank
        # stays absent rather than defaulting to a flattering 1.0.
        ranks = percentile_ranks(blends) if len(blends) > 1 else {}

        results: list[StrategyResult] = []
        for context, verdict in zip(contexts, verdicts, strict=True):
            if verdict.eligible:
                results.append(
                    self._result(
                        context,
                        verdict,
                        score=SCORE_CEILING * blends[context.symbol],
                        rank_percentile=ranks.get(context.symbol),
                        contributions=self._contributions(context, percentiles),
                    )
                )
            else:
                results.append(
                    self._result(
                        context,
                        verdict,
                        score=None,
                        rank_percentile=None,
                        contributions=(),
                    )
                )
        return tuple(results)

    def explain(self, result: StrategyResult) -> Explanation:
        """Make the result expandable to factor level."""
        verdict = "eligible" if result.eligible else "not eligible"
        outcome = (
            f"score {result.score}"
            if result.score is not None
            else f"no score ({SCORING_NEEDS_A_POPULATION})"
        )
        rank = (
            f", rank_percentile {result.rank_percentile}"
            if result.rank_percentile is not None
            else ""
        )

        return Explanation(
            symbol=result.symbol,
            strategy_id=result.strategy_id,
            as_of=result.as_of,
            summary=(
                f"{result.strategy_id} {result.strategy_version}: {verdict}; "
                f"{outcome}{rank}"
            ),
            factors=_notes(result),
        )

    def _contributions(
        self,
        context: StrategyContext,
        percentiles: dict[str, dict[str, float]],
    ) -> tuple[FactorContribution, ...]:
        """Record each factor's share, in configuration order."""
        total_weight = sum(self._weights.values())
        return tuple(
            FactorContribution(
                factor=name,
                percentile=percentiles[name][context.symbol],
                weight=self._weights[name],
                weighted=self._weights[name]
                * percentiles[name][context.symbol]
                / total_weight,
            )
            for name in self._weights
        )

    def _result(
        self,
        context: StrategyContext,
        verdict: EligibilityResult,
        *,
        score: float | None,
        rank_percentile: float | None,
        contributions: tuple[FactorContribution, ...],
    ) -> StrategyResult:
        return StrategyResult(
            symbol=context.symbol,
            strategy_id=self._config.id,
            strategy_version=self._config.version,
            as_of=context.as_of,
            eligible=verdict.eligible,
            lineage=SnapshotLineage(strategy_version=self._config.version),
            score=score,
            rank_percentile=rank_percentile,
            confidence=None,
            reasons=_describe(context.factors),
            risks=verdict.reasons,
            factor_snapshot=context.factors,
            contributions=contributions,
        )


def _validated_weights(config: StrategyConfig) -> dict[str, float]:
    """Check that the weights describe exactly the factors the scanner needs.

    An empty mapping is not an error: it means no weights have been reviewed,
    and the scanner then reports no score at all.
    """
    weights = dict(config.weights)
    if not weights:
        return {}

    declared = set(config.required_factors)
    configured = set(weights)
    if declared != configured:
        raise ValueError(
            "weights must cover required_factors exactly: "
            f"missing={sorted(declared - configured)}, "
            f"unexpected={sorted(configured - declared)}"
        )

    negative = sorted(name for name, value in weights.items() if value < 0)
    if negative:
        raise ValueError(f"weights must not be negative: {negative}")

    if sum(weights.values()) <= 0:
        raise ValueError("weights must not sum to zero")

    return weights


def _value_of(context: StrategyContext, name: str) -> float:
    """Return a required factor's value, which eligibility has already checked."""
    for result in context.factors:
        if result.factor == name and result.raw_value is not None:
            return result.raw_value
    raise ValueError(
        f"{name} has no value for {context.symbol}; eligibility should have "
        "kept this context out of the population"
    )


def _notes(result: StrategyResult) -> tuple[FactorExplanation, ...]:
    """Return one line per factor, widening it when a score used it."""
    contributions = {item.factor: item for item in result.contributions}
    notes: list[FactorExplanation] = []

    for item in result.factor_snapshot:
        note = (
            f"{item.raw_value}"
            if item.raw_value is not None
            else f"no value ({item.status})"
        )
        contribution = contributions.get(item.factor)
        if contribution is not None:
            note = (
                f"{note} (percentile {contribution.percentile:.3f}, "
                f"weight {contribution.weight})"
            )
        notes.append(FactorExplanation(factor=item.factor, note=note))

    return tuple(notes)


def _describe(factors: tuple[FactorResult, ...]) -> tuple[str, ...]:
    """Return one human-readable line per factor, never inventing a value."""
    return tuple(
        f"{item.factor}={item.raw_value}"
        if item.raw_value is not None
        else f"{item.factor} is {item.status}"
        for item in factors
    )
