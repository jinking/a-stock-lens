"""Factor engine."""

from astock_lens.factors.builtin import AverageAmountFactor
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.factors.contracts import (
    Factor,
    FactorContext,
    FactorMetadata,
    FactorResult,
)
from astock_lens.factors.registry import FactorRegistry

__all__ = [
    "AverageAmountFactor",
    "Factor",
    "FactorConfig",
    "FactorContext",
    "FactorMetadata",
    "FactorRegistry",
    "FactorResult",
    "load_factor_config",
]
