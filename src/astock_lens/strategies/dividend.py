"""Dividend Scanner：股息是否高、可持续、能被现金流覆盖。

类边界独立：资格与因子要求由这个类拥有，分数算术委托给共享评分组件。

**待所有者决定（不得自行发明）**：支付率的形状。实测榜首出现 1950% / 274% 的
支付率（动用留存收益或特别分红），当前线性加权把 1950% 与 90% 同等对待。
设上限 / 区间偏好 / 接受现状，三种都要项目所有者裁决。
"""

from collections.abc import Sequence

from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import (
    EligibilityResult,
    Explanation,
    StrategyContext,
    StrategyResult,
)
from astock_lens.strategies.percentile_scorer import (
    WeightedPercentileScorer,
    evidence_result,
    explain_result,
    required_values_are_present,
    validated_weights,
)


class DividendScanner:
    """Score dividend sustainability and cash-flow coverage, not yield alone."""

    def __init__(self, strategy_config: StrategyConfig) -> None:
        self._config = strategy_config
        self._weights = validated_weights(strategy_config)
        self._scorer = WeightedPercentileScorer()

    def required_factors(self) -> set[str]:
        """Return the factor names this scanner needs."""
        return set(self._config.required_factors)

    def eligibility(self, context: StrategyContext) -> EligibilityResult:
        """Require every configured factor to carry an actual value."""
        return required_values_are_present(context, self._weights)

    def score(self, context: StrategyContext) -> StrategyResult:
        """Report evidence for one symbol; a percentile needs a population."""
        return evidence_result(
            context=context,
            verdict=self.eligibility(context),
            strategy_id=self._config.id,
            strategy_version=self._config.version,
        )

    def score_cross_section(
        self, contexts: Sequence[StrategyContext]
    ) -> tuple[StrategyResult, ...]:
        """Rank the eligible population with the reviewed weights."""
        return self._scorer.score_cross_section(
            strategy_id=self._config.id,
            strategy_version=self._config.version,
            contexts=contexts,
            weights=self._weights,
            eligibility=self.eligibility,
        )

    def explain(self, result: StrategyResult) -> Explanation:
        """Make the score expandable to factor level."""
        return explain_result(result)
