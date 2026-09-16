"""Strategy configuration.

Same rule as factor configuration: algorithms are code, weights and thresholds
are YAML (`docs/ARCHITECTURE.md` §8.3). `required_factors` is declared per
strategy so a scanner never hardcodes the factor names it depends on.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class StrategyConfig(BaseModel):
    """One scanner definition as written under `configs/strategies/`."""

    model_config = ConfigDict(frozen=True)

    id: str
    version: str
    required_factors: tuple[str, ...] = ()
    enabled: bool = True
    description: str = ""
    dimensions: tuple[str, ...] = ()


def load_strategy_config(path: Path) -> StrategyConfig:
    """Load and validate one strategy definition from YAML."""
    with path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004
            f"Strategy configuration root must be a mapping: {path}"
        )
    return StrategyConfig.model_validate(payload)
