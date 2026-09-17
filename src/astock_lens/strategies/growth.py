"""Growth Scanner：经营是否真的在增长。

类边界独立：`required_factors` / `eligibility` / `score_cross_section` / `explain`
都由这个类拥有；把"哪些因子构成 Growth"与"怎么把它们合成一个分数"分开，
后者委托给共享的 `WeightedPercentileScorer`。

**待所有者决定（不得自行发明）**：极值稳健化。实测全市场榜首的
`net_profit_parent_yoy` 达 71528%，百分位排名把 3000% 与 70000% 压成相邻名次。
缩尾 / 要求两端同时成立 / 接受现状，三种都要项目所有者裁决。
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


class GrowthScanner:
    """Score the growth dimension; the extreme-value policy is still open."""

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
