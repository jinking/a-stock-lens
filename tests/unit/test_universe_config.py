"""Universe configuration loading.

`configs/universe.yaml` is the only place the Universe thresholds live. These
tests pin the two rulings this slice records: the liquidity floor came from the
project owner (20,000,000 CNY), and the long-suspension day count is explicitly
deferred rather than guessed.
"""

from pathlib import Path

import pytest
import yaml

from astock_lens.universe.config import UniverseConfig, load_universe_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "universe.yaml"


def _load() -> UniverseConfig:
    return load_universe_config(CONFIG_PATH)


def test_repository_config_loads() -> None:
    config = _load()

    assert config.exchanges == ("SSE", "SZSE", "BSE")
    assert config.min_listing_days == 120


def test_liquidity_floor_carries_the_owner_supplied_value() -> None:
    """20,000,000 CNY is a human decision, recorded in the config, not in code."""
    assert _load().min_average_turnover_20d == 20_000_000.0


def test_long_suspension_is_deferred_not_defaulted() -> None:
    """The rule is switched on, but no day count has been reviewed."""
    config = _load()

    assert config.exclude_long_suspension is True
    assert config.long_suspension_days is None


def test_a_missing_liquidity_floor_is_an_error_not_a_fallback() -> None:
    """Deleting the key must fail loudly; there is no code default."""
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    del payload["min_average_turnover_20d"]

    with pytest.raises(ValueError, match="min_average_turnover_20d"):
        UniverseConfig.model_validate(payload)


def test_a_missing_listing_age_is_an_error_not_a_fallback() -> None:
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    del payload["min_listing_days"]

    with pytest.raises(ValueError, match="min_listing_days"):
        UniverseConfig.model_validate(payload)


def test_an_unknown_key_is_rejected() -> None:
    """A typo in the config must not be silently ignored."""
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["min_average_turnover_2d"] = 5_000_000

    with pytest.raises(ValueError):
        UniverseConfig.model_validate(payload)


def test_digest_is_stable_and_content_sensitive() -> None:
    config = _load()

    assert config.digest() == _load().digest()
    assert (
        config.digest() != config.model_copy(update={"min_listing_days": 121}).digest()
    )
