"""Factor registry tests."""

from pathlib import Path

import pytest

from astock_lens.factors.builtin import AverageAmountFactor
from astock_lens.factors.config import load_factor_config
from astock_lens.factors.registry import FactorRegistry

CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "factors" / "avg_amount_20d.yaml"
)


def _factor() -> AverageAmountFactor:
    return AverageAmountFactor(load_factor_config(CONFIG_PATH))


def test_registration_preserves_order() -> None:
    registry = FactorRegistry()
    registry.register(_factor())

    assert registry.names() == ("avg_amount_20d",)


def test_duplicate_registration_is_rejected() -> None:
    registry = FactorRegistry()
    registry.register(_factor())

    with pytest.raises(ValueError, match="avg_amount_20d"):
        registry.register(_factor())


def test_unknown_lookup_is_rejected() -> None:
    registry = FactorRegistry()

    with pytest.raises(KeyError, match="nonexistent"):
        registry.get("nonexistent")


def test_registered_factor_is_returned_by_name() -> None:
    registry = FactorRegistry()
    factor = _factor()
    registry.register(factor)

    assert registry.get("avg_amount_20d") is factor
