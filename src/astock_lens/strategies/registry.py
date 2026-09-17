"""Strategy registry.

`spec §8` names seven V1 scanners. Six have an implementation; `industry_trend`
waits for industry data. The mapping from `id` to class is **explicit**: an
earlier version inferred "if the YAML carries weights, use the generic weighted
scanner", which made the implementation a property of the configuration file
and left each strategy's own eligibility rules with nowhere to live. The
registry now names each class, so a new strategy is a new class plus one line.

`build_scanner` refuses an id it has no class for, by name, so a run never
reports "no candidates" when the truth is "no scanner".
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import StrategyPlugin
from astock_lens.strategies.dividend import DividendScanner
from astock_lens.strategies.garp import GarpScanner
from astock_lens.strategies.growth import GrowthScanner
from astock_lens.strategies.momentum import MomentumScanner
from astock_lens.strategies.quality import QualityScanner
from astock_lens.strategies.value import ValueScanner

IMPLEMENTATIONS: Mapping[str, Callable[[StrategyConfig], StrategyPlugin]] = {
    "momentum": MomentumScanner,
    "growth": GrowthScanner,
    "quality": QualityScanner,
    "dividend": DividendScanner,
    "value": ValueScanner,
    "garp": GarpScanner,
}

# Why the remaining scanners are not built yet. Each reason names a missing
# input rather than a missing opinion, so nobody reads "unimplemented" as a
# data outage.
UNIMPLEMENTED_REASONS: Mapping[str, str] = {
    "industry_trend": (
        "it scores an industry first and then maps that score onto stocks; no "
        "industry data (sector membership, industry aggregates) has been landed"
    ),
}


class StrategyNotImplementedError(ValueError):
    """A configured scanner that no code implements yet."""


@dataclass(frozen=True)
class RegisteredStrategy:
    """One configured scanner together with the code that runs it."""

    config: StrategyConfig
    plugin: StrategyPlugin


def build_scanner(config: StrategyConfig) -> StrategyPlugin:
    """Return the class registered for this id, or say which input it waits for.

    There is no inference here: an id without a registered class is refused by
    name. Inferring the implementation from the presence of weights would make
    every strategy that happens to have weights the same strategy.
    """
    factory = IMPLEMENTATIONS.get(config.id)
    if factory is None:
        reason = UNIMPLEMENTED_REASONS.get(config.id, "no implementation is registered")
        raise StrategyNotImplementedError(
            f"strategy {config.id!r} has no implementation: {reason}; "
            f"implemented scanners are {sorted(IMPLEMENTATIONS)}"
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
        if _runnable(config)
    )


def unimplemented_scanners(directory: Path) -> tuple[str, ...]:
    """Return the enabled scanner ids that no code implements yet."""
    return tuple(
        config.id for config in _enabled_configs(directory) if not _runnable(config)
    )


def _runnable(config: StrategyConfig) -> bool:
    """可运行 = 登记过实现；配置里的权重不再决定这件事。"""
    return config.id in IMPLEMENTATIONS


def unimplemented_reasons(directory: Path) -> tuple[tuple[str, str], ...]:
    """Return each unbuilt scanner with the input it waits for."""
    return tuple(
        (
            strategy_id,
            UNIMPLEMENTED_REASONS.get(strategy_id, "no reason recorded"),
        )
        for strategy_id in unimplemented_scanners(directory)
    )


def _enabled_configs(directory: Path) -> Sequence[StrategyConfig]:
    return tuple(
        config
        for config in (load_strategy_config(path) for path in strategy_paths(directory))
        if config.enabled
    )
