"""GARP Scanner：成长与价格是否匹配。

类边界独立：资格与因子要求由这个类拥有，分数算术委托给共享评分组件。

**待所有者决定（不得自行发明）**：PEG 的值域。源站 PEG 实测在 83–1503（常见口径
0–5）且出现负值，方向（越低越匹配）可用但绝对值不能与外口径比较。

**本阶段刻意不做的事**：设计要求 GARP 最终复用 Growth 的结果，但真实
`GrowthResult` 依赖与阈值尚未完成业务改造，因此这里只建立独立类边界并保持输出
parity；把它改成复用 Growth 属于后续 Owner-approved 的策略升级。
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


class GarpScanner:
    """Score growth quality against valuation; PEG handling is still open."""

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
