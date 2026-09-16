"""Strategy plugins."""

from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import (
    EligibilityResult,
    Explanation,
    FactorContribution,
    FactorExplanation,
    StrategyContext,
    StrategyPlugin,
    StrategyResult,
)
from astock_lens.strategies.momentum import MomentumScanner
from astock_lens.strategies.scoring import percentile_ranks

__all__ = [
    "EligibilityResult",
    "Explanation",
    "FactorContribution",
    "FactorExplanation",
    "MomentumScanner",
    "StrategyConfig",
    "StrategyContext",
    "StrategyPlugin",
    "StrategyResult",
    "load_strategy_config",
    "percentile_ranks",
]
