"""Factor configuration.

Parameters live in YAML, per `docs/ARCHITECTURE.md` §8.3: algorithms are code,
weights and thresholds are configuration. This module supplies no default value
for any parameter, so a configuration that omits one fails loudly instead of
producing a number nobody asked for.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from astock_lens.domain.enums import FactorDomain


class FactorConfig(BaseModel):
    """One factor definition as written under `configs/factors/`."""

    model_config = ConfigDict(frozen=True)

    name: str
    domain: FactorDomain
    description: str
    inputs: tuple[str, ...]
    frequency: str
    direction: str
    null_policy: str
    version: str
    # A parameter may be explicitly `null`: that is how a configuration records
    # "this threshold has not been reviewed yet" without inventing a number.
    # `configs/universe.yaml` uses the same convention for its deferred rules.
    params: dict[str, int | None] = Field(default_factory=dict)


def load_factor_config(path: Path) -> FactorConfig:
    """Load and validate one factor definition from YAML."""
    with path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004
            f"Factor configuration root must be a mapping: {path}"
        )
    return FactorConfig.model_validate(payload)
