"""Universe configuration.

Thresholds live in YAML, per `docs/ARCHITECTURE.md` §6 and §8.3. Two keys are
required with no default — the liquidity floor and the minimum listing age —
so deleting either is an error rather than a silent fallback. A key whose value
is genuinely undecided is expressed as `null` and paired with a rule that
reports itself as deferred.
"""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class UniverseConfig(BaseModel):
    """One Universe definition as written in `configs/universe.yaml`.

    `extra="forbid"` is deliberate: a mistyped threshold key would otherwise be
    ignored, and the run would quietly use the previous value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    exchanges: tuple[str, ...]
    min_average_turnover_20d: float
    min_listing_days: int
    exclude_st: bool = True
    exclude_delisting_board: bool = True
    exclude_long_suspension: bool = True
    long_suspension_days: int | None = None
    require_valid_market_data: bool = True

    def digest(self) -> str:
        """Return a stable content hash of this configuration.

        Part of every snapshot id, so two runs that used different thresholds
        cannot be mistaken for the same snapshot.
        """
        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_universe_config(path: Path) -> UniverseConfig:
    """Load and validate the Universe configuration from YAML."""
    with path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004
            f"Universe configuration root must be a mapping: {path}"
        )
    return UniverseConfig.model_validate(payload)
