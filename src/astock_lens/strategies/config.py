"""Strategy configuration.

Same rule as factor configuration: algorithms are code, weights and thresholds
are YAML (`docs/ARCHITECTURE.md` §8.3). `required_factors` is declared per
strategy so a scanner never hardcodes the factor names it depends on, and
`weights` carries the scoring weights so a scanner never hardcodes those either.

An empty `weights` mapping means "no reviewed weights exist": the scanner then
reports eligibility and leaves the ranking fields `None`, which is exactly how
this repository behaved before scoring existed.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrategyConfig(BaseModel):
    """One scanner definition as written under `configs/strategies/`."""

    model_config = ConfigDict(frozen=True)

    id: str
    version: str
    required_factors: tuple[str, ...] = ()
    enabled: bool = True
    description: str = ""
    dimensions: tuple[str, ...] = ()
    weights: dict[str, float] = Field(default_factory=dict)


def load_strategy_config(path: Path) -> StrategyConfig:
    """Load and validate one strategy definition from YAML."""
    with path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004
            f"Strategy configuration root must be a mapping: {path}"
        )
    return StrategyConfig.model_validate(payload)
