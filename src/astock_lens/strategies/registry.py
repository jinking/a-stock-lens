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
from astock_lens.strategies.eligibility import EligibilityScanner
from astock_lens.strategies.momentum import MomentumScanner
from astock_lens.strategies.weighted import WeightedPercentileScanner

IMPLEMENTATIONS: Mapping[str, Callable[[StrategyConfig], StrategyPlugin]] = {
    # 只有自带算法的 Scanner 需要在这里登记：动量有自己的横截面评分实现。
    "momentum": MomentumScanner,
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
    """按声明选择实现：有权重就打分，只有要求就先做资格判定。

    三条规则让"权重评审"成为纯配置动作：

    1. `IMPLEMENTATIONS` 里登记过的 id，用它自己的算法（目前只有动量）；
    2. 声明了 `required_factors` 的配置：有权重 → `WeightedPercentileScanner`，
       没有权重 → `EligibilityScanner`（只判资格、不打分）；
    3. 既没登记、也没声明要求的配置 → 报错并写明它等待的输入。
    """
    factory = IMPLEMENTATIONS.get(config.id)
    if factory is None:
        if config.required_factors:
            return (
                WeightedPercentileScanner(config)
                if config.weights
                else EligibilityScanner(config)
            )
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
    """是否可运行：登记过实现，或声明了要求（于是能判资格、也可能能打分）。"""
    return config.id in IMPLEMENTATIONS or bool(config.required_factors)


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
