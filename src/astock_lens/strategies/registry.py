"""Strategy registry.

`spec §8` names seven V1 scanners. Only Momentum has an implementation today;
the other six configurations describe dimensions the factor engine cannot yet
measure, and their weights and thresholds are deferred. This registry resolves
an `id` to the code that implements it and refuses the rest by name, so a run
never reports "no candidates" when the truth is "no scanner".
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import StrategyPlugin
from astock_lens.strategies.momentum import MomentumScanner

IMPLEMENTATIONS: Mapping[str, Callable[[StrategyConfig], StrategyPlugin]] = {
    "momentum": MomentumScanner,
}


class StrategyNotImplementedError(ValueError):
    """A configured scanner that no code implements yet."""


@dataclass(frozen=True)
class RegisteredStrategy:
    """One configured scanner together with the code that runs it."""

    config: StrategyConfig
    plugin: StrategyPlugin


def build_scanner(config: StrategyConfig) -> StrategyPlugin:
    """Return the scanner implementation for one configuration."""
    factory = IMPLEMENTATIONS.get(config.id)
    if factory is None:
        raise StrategyNotImplementedError(
            f"strategy {config.id!r} has no implementation; implemented "
            f"scanners are {sorted(IMPLEMENTATIONS)}"
        )
    return factory(config)


def load_scanner(path: Path) -> RegisteredStrategy:
    """Load one scanner from its configuration file."""
    config = load_strategy_config(path)
    if not config.enabled:
        raise StrategyNotImplementedError(f"strategy {config.id!r} is disabled")
    return RegisteredStrategy(config=config, plugin=build_scanner(config))


def strategy_paths(directory: Path) -> tuple[Path, ...]:
    """Return every strategy configuration file, in a stable order."""
    return tuple(sorted(directory.glob("*.yaml")))


def load_scanners(directory: Path) -> tuple[RegisteredStrategy, ...]:
    """Load every enabled configuration that has an implementation.

    A configuration with no implementation is not silently skipped: its `id`
    is reported by `unimplemented_scanners`, and the stage that runs the
    scanners records it.
    """
    return tuple(
        RegisteredStrategy(config=config, plugin=build_scanner(config))
        for config in _enabled_configs(directory)
        if config.id in IMPLEMENTATIONS
    )


def unimplemented_scanners(directory: Path) -> tuple[str, ...]:
    """Return the enabled scanner ids that no code implements yet."""
    return tuple(
        config.id
        for config in _enabled_configs(directory)
        if config.id not in IMPLEMENTATIONS
    )


def _enabled_configs(directory: Path) -> Sequence[StrategyConfig]:
    return tuple(
        config
        for config in (load_strategy_config(path) for path in strategy_paths(directory))
        if config.enabled
    )
