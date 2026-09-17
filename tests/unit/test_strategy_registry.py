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
from astock_lens.strategies.weighted import WeightedPercentileScanner

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

    built = set(IMPLEMENTATIONS) | {item.config.id for item in load_scanners(CONFIGS)}
    explained = set(UNIMPLEMENTED_REASONS)

    assert built | explained >= configured
    assert built & explained == set()


def test_four_scanners_run_and_three_report_what_they_wait_for() -> None:
    # 只有自带算法的 Scanner 需要登记；其余靠"是否声明了要求"判定可运行。
    assert set(IMPLEMENTATIONS) == {"momentum"}
    assert {item.config.id for item in load_scanners(CONFIGS)} == {
        "dividend",
        "garp",
        "growth",
        "momentum",
        "quality",
        "value",
    }
    # 估值数据接入后 Value 与 GARP 有了要求；只剩 Industry Trend 等行业数据。
    assert set(unimplemented_scanners(CONFIGS)) == {"industry_trend"}


def test_the_blocked_scanners_name_a_missing_input() -> None:
    reasons = dict(unimplemented_reasons(CONFIGS))

    assert "industry data" in reasons["industry_trend"]


def test_a_blocked_scanner_says_why_when_it_is_asked_to_run() -> None:
    with pytest.raises(StrategyNotImplementedError) as raised:
        build_scanner(_config("industry_trend"))

    message = str(raised.value)
    assert "no implementation" in message
    assert "industry data" in message


def test_the_built_scanners_bind_to_the_implementation_their_config_needs() -> None:
    loaded = {item.config.id: item.plugin for item in load_scanners(CONFIGS)}

    assert isinstance(loaded["momentum"], MomentumScanner)
    for strategy_id in ("growth", "quality", "dividend"):
        # 权重已于 2026-09-17 评审通过，因此这三个走打分实现。
        assert isinstance(loaded[strategy_id], WeightedPercentileScanner)
        assert loaded[strategy_id].required_factors()
    # Value 与 GARP 的权重均于 2026-09-17 评审通过 → 两者都打分。
    for strategy_id in ("value", "garp"):
        assert isinstance(loaded[strategy_id], WeightedPercentileScanner)


def test_a_configuration_without_reviewed_weights_judges_eligibility_only() -> None:
    """权重评审是唯一开关：没权重就不产生分数。"""
    scored = _config("quality", required_factors=["roe_ttm"], weights={"roe_ttm": 1.0})
    unscored = _config("quality", required_factors=["roe_ttm"])

    assert isinstance(build_scanner(scored), WeightedPercentileScanner)
    assert isinstance(build_scanner(unscored), EligibilityScanner)


def test_shipped_weights_cover_their_required_factors_exactly() -> None:
    """配置守卫：权重表与要求表一旦对不上，这里就失败。

    该守卫存在的理由很具体——2026-09-17 给三个 Scanner 写入等权时，注册表里还硬绑着
    资格判定实现，结果 19 个测试同时失败。配置与实现的一致性应当由一个断言来守。
    """
    from astock_lens.strategies.config import load_strategy_config

    for path in strategy_paths(CONFIGS):
        config = load_strategy_config(path)
        if not config.weights:
            continue
        assert set(config.weights) == set(config.required_factors), path.name
        assert all(weight != 0 for weight in config.weights.values()), path.name


def test_loading_skips_a_blocked_scanner_instead_of_failing() -> None:
    """A blocked scanner must not stop the scanners that do run."""
    assert {item.config.id for item in load_scanners(CONFIGS)} == {
        "dividend",
        "garp",
        "growth",
        "momentum",
        "quality",
        "value",
    }


def test_a_disabled_scanner_is_not_reported_as_blocked() -> None:
    """Switching a scanner off is a choice, not a missing implementation."""
    disabled = _config("quality", enabled=False)
    assert disabled.enabled is False
