"""Strategy plugins."""

from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import (
    EligibilityResult,
    Explanation,
    FactorExplanation,
    StrategyContext,
    StrategyPlugin,
    StrategyResult,
)
from astock_lens.strategies.momentum import MomentumScanner

__all__ = [
    "EligibilityResult",
    "Explanation",
    "FactorExplanation",
    "MomentumScanner",
    "StrategyConfig",
    "StrategyContext",
    "StrategyPlugin",
    "StrategyResult",
    "load_strategy_config",
]
