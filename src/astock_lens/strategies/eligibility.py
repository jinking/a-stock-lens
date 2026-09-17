"""Eligibility-only scanners.

`docs/STRATEGY_SYSTEM.md` §5 defers every scanner's weights, score thresholds,
`rank_percentile` and `confidence`. A scanned symbol can therefore be judged on
eligibility alone when nobody has approved a weight set for it yet.

That is a deliberate half-step, not a stub. Eligibility is a real verdict —
"this symbol's evidence is complete enough for this scanner to consider it" —
it is the first half of the funnel the design describes, and it is falsifiable.
A score would require a number nobody has approved, and a made-up threshold
reads downstream as a product judgement.

**现状（2026-09-17 核心执行链硬化）**：六个策略的权重都已评审通过，各自有了
独立的 Scanner 类，`registry.IMPLEMENTATIONS` 里不再有自动落到这个类的规则，
因此本模块目前**不被任何生产路径引用**。保留它的理由是一个真实用途：某个策略
暂时只有资格规则、没有已评审的权重时，它仍然是一个可登记的 Plugin 实现——
登记处就在 `registry.IMPLEMENTATIONS`。若项目所有者认为这条退路不需要，删除
本模块与其测试即可，不影响任何现有策略。

早先的版本让这个类服务于"配置里有要求但没写权重"的一切策略，那等于让 YAML
决定用哪个实现；那条规则已经随 Task 6 移除。
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
