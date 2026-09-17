"""Weighted percentile scoring, for strategies whose weights have been reviewed.

`docs/STRATEGY_SYSTEM.md` §5 defers every scanner's weights and score
thresholds. This module is the machine that turns a *reviewed* weight set into
a score, so approving weights is a configuration change rather than a coding
task. Until a configuration carries weights, `EligibilityScanner` is what runs
and no score is produced.

## How a weight is read

`weights` must cover exactly the factors the strategy requires, and the sign of
a weight carries the factor's polarity:

- **positive** — the higher the value, the better the standing (ROE, gross
  margin, growth);
- **negative** — the factor is oriented first, so the *lower* value ranks better
  (leverage, goodwill-to-equity).

Writing polarity as a sign rather than inventing a second vocabulary keeps one
number per factor, and it makes an ambiguous case visible: a weight whose
magnitude is irrelevant to a reviewer is a weight nobody has thought about.

The blend is `Σ(|w| · oriented_percentile) / Σ|w|`, scaled to 0–100. Percentiles
are cross-sectional over the eligible population only, so a symbol with missing
evidence shifts nobody's rank. `confidence` stays `None`: the design requires
the field but defines no algorithm, and eligibility already demands every
factor be present, so a "coverage ratio" would be a constant dressed up as a
measurement.
"""

from collections.abc import Mapping, Sequence

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
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

SCORE_CEILING = 100.0


class WeightedPercentileScanner:
    """Score a population with a reviewed weight set."""

    def __init__(self, strategy_config: StrategyConfig) -> None:
        if not strategy_config.required_factors:
            raise ValueError(
                f"strategy {strategy_config.id!r} must declare required_factors"
            )
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
        """Report evidence for one symbol; a percentile needs a population."""
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
        """Rank a population, orienting each factor by its weight's sign."""
        if not contexts:
            return ()

        verdicts = [self.eligibility(context) for context in contexts]
        population = [
            context
            for context, verdict in zip(contexts, verdicts, strict=True)
            if verdict.eligible
        ]

        oriented = {
            name: percentile_ranks(
                {
                    context.symbol: _oriented_value(context, name, self._weights[name])
                    for context in population
                }
            )
            for name in self._weights
        }
        total_weight = sum(abs(weight) for weight in self._weights.values())
        blends = {
            context.symbol: sum(
                abs(self._weights[name]) * oriented[name][context.symbol]
                for name in self._weights
            )
            / total_weight
            for context in population
        }
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
                        contributions=self._contributions(
                            context, oriented, total_weight
                        ),
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
        """Make the score expandable to factor level."""
        verdict = "eligible" if result.eligible else "not eligible"
        outcome = (
            f"score {result.score:.2f}"
            if result.score is not None
            else "no score (needs a cross-section)"
        )
        return Explanation(
            symbol=result.symbol,
            strategy_id=result.strategy_id,
            as_of=result.as_of,
            summary=(
                f"{result.strategy_id} {result.strategy_version}: {verdict}; {outcome}"
            ),
            factors=_notes(result),
        )

    def _contributions(
        self,
        context: StrategyContext,
        oriented: Mapping[str, Mapping[str, float]],
        total_weight: float,
    ) -> tuple[FactorContribution, ...]:
        """Record each factor's oriented share, in configuration order."""
        return tuple(
            FactorContribution(
                factor=name,
                percentile=oriented[name][context.symbol],
                weight=self._weights[name],
                weighted=abs(self._weights[name])
                * oriented[name][context.symbol]
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
            reasons=tuple(
                f"{result.factor}={result.raw_value}"
                if result.raw_value is not None
                else f"{result.factor} is {result.status}"
                for result in context.factors
            ),
            risks=verdict.reasons,
            factor_snapshot=context.factors,
            contributions=contributions,
        )


def _oriented_value(context: StrategyContext, name: str, weight: float) -> float:
    """Return a factor's value, negated when a lower value ranks better."""
    value = _value_of(context, name)
    return value if weight > 0 else -value


def _value_of(context: StrategyContext, name: str) -> float:
    """Return a required factor's value, which eligibility has already checked."""
    for result in context.factors:
        if result.factor == name and result.raw_value is not None:
            return result.raw_value
    raise ValueError(
        f"{name} has no value for {context.symbol}; eligibility should have "
        "kept this context out of the population"
    )


def _validated_weights(config: StrategyConfig) -> dict[str, float]:
    """Check that the reviewed weights describe exactly the required factors."""
    weights = dict(config.weights)
    if not weights:
        raise ValueError(
            f"strategy {config.id!r} declares no weights, so there is nothing "
            "to score; a strategy without reviewed weights runs "
            "EligibilityScanner instead"
        )

    declared = set(config.required_factors)
    configured = set(weights)
    if declared != configured:
        raise ValueError(
            "weights must cover required_factors exactly: "
            f"missing={sorted(declared - configured)}, "
            f"unexpected={sorted(configured - declared)}"
        )

    zero = sorted(name for name, value in weights.items() if value == 0)
    if zero:
        raise ValueError(
            f"a zero weight means the factor does not belong to the strategy: {zero}"
        )
    return weights


def _notes(result: StrategyResult) -> tuple[FactorExplanation, ...]:
    """One line per factor, showing its oriented percentile and weight."""
    contributions = {item.factor: item for item in result.contributions}
    notes: list[FactorExplanation] = []
    for item in result.factor_snapshot:
        contribution = contributions.get(item.factor)
        if contribution is None:
            notes.append(
                FactorExplanation(
                    factor=item.factor,
                    note=(
                        f"{item.raw_value}"
                        if item.raw_value is not None
                        else f"no value ({item.status})"
                    ),
                )
            )
            continue
        notes.append(
            FactorExplanation(
                factor=item.factor,
                note=(
                    f"{item.raw_value} (oriented percentile "
                    f"{contribution.percentile:.3f}, weight {contribution.weight})"
                ),
            )
        )
    return tuple(notes)
