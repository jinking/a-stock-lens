"""Quality Scanner：生意质量是否长期稳定。

类边界独立：资格与因子要求由这个类拥有，分数算术委托给共享评分组件。

**已知取舍（已评审、不是我的发明）**：`debt_to_asset` 取负权重，表示"越低越好"；
这四个维度等权是刻意的中性选择——实测显示"收益+现金流优先"与等权的 top-12 只
重合 3 个，在没有依据说哪个维度更重要之前不对它们排序。
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


class QualityScanner:
    """Score durable profitability, capital efficiency and balance-sheet quality."""

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
