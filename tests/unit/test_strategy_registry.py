"""Strategy registry tests.

`spec §8` names seven scanners. Four have implementations today; three do not,
and the registry's job is to say *which* and *why* — an operator reading "no
implementation" must not have to guess whether it is a missing build or a
missing data source.
"""

from pathlib import Path

import pytest

from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.eligibility import EligibilityScanner
from astock_lens.strategies.momentum import MomentumScanner
from astock_lens.strategies.registry import (
    IMPLEMENTATIONS,
    UNIMPLEMENTED_REASONS,
    StrategyNotImplementedError,
    build_scanner,
    load_scanners,
    strategy_paths,
    unimplemented_reasons,
    unimplemented_scanners,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs" / "strategies"


def _config(strategy_id: str, **overrides: object) -> StrategyConfig:
    payload: dict[str, object] = {
        "id": strategy_id,
        "version": "v1",
        "description": strategy_id,
    }
    payload.update(overrides)
    return StrategyConfig.model_validate(payload)


def test_every_configured_scanner_is_either_built_or_explained() -> None:
    """The two sets must partition the configurations — no silent gaps."""
    configured = {path.stem for path in strategy_paths(CONFIGS)}

    built = set(IMPLEMENTATIONS)
    explained = set(UNIMPLEMENTED_REASONS)

    assert built | explained >= configured
    assert built & explained == set()


def test_four_scanners_run_and_three_report_what_they_wait_for() -> None:
    assert set(IMPLEMENTATIONS) == {"momentum", "growth", "quality", "dividend"}
    assert set(unimplemented_scanners(CONFIGS)) == {"garp", "value", "industry_trend"}


def test_the_blocked_scanners_name_a_missing_input() -> None:
    reasons = dict(unimplemented_reasons(CONFIGS))

    assert "valuation factors" in reasons["value"]
    assert "valuation" in reasons["garp"]
    assert "industry data" in reasons["industry_trend"]


def test_a_blocked_scanner_says_why_when_it_is_asked_to_run() -> None:
    with pytest.raises(StrategyNotImplementedError) as raised:
        build_scanner(_config("value"))

    message = str(raised.value)
    assert "no implementation" in message
    assert "share-count" in message


def test_the_built_scanners_bind_to_the_implementation_their_config_needs() -> None:
    loaded = {item.config.id: item.plugin for item in load_scanners(CONFIGS)}

    assert isinstance(loaded["momentum"], MomentumScanner)
    for strategy_id in ("growth", "quality", "dividend"):
        assert isinstance(loaded[strategy_id], EligibilityScanner)
        assert loaded[strategy_id].required_factors()


def test_loading_skips_a_blocked_scanner_instead_of_failing() -> None:
    """A blocked scanner must not stop the scanners that do run."""
    assert {item.config.id for item in load_scanners(CONFIGS)} == {
        "dividend",
        "growth",
        "momentum",
        "quality",
    }


def test_a_disabled_scanner_is_not_reported_as_blocked() -> None:
    """Switching a scanner off is a choice, not a missing implementation."""
    disabled = _config("quality", enabled=False)
    assert disabled.enabled is False
