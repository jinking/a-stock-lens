"""Value Scanner：相对自身历史、同行与现金流是否便宜。

类边界独立：资格与因子要求由这个类拥有，分数算术委托给共享评分组件。

**已知取舍（已评审、不是我的发明）**：估值倍数越低越便宜，所以 PE/PB/PS/历史分位/
市现率都取负权重；倍数非正时因子报 `NOT_APPLICABLE`，不会被当成"最便宜"。
股息率没有进入必需项：neodata 的滚动股息率列在实测抽样里整列为空，把它列为必需
会让 Value 永久不合格——那读起来像"市场没有便宜货"。
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


class ValueScanner:
    """Score cheapness relative to history, peers, and cash-flow quality."""

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
