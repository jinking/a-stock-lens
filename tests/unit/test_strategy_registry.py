"""Strategy registry tests.

`spec §8` names seven scanners. Four have implementations today; three do not,
and the registry's job is to say *which* and *why* — an operator reading "no
implementation" must not have to guess whether it is a missing build or a
missing data source.
"""

from pathlib import Path

import pytest

from astock_lens.strategies.config import StrategyConfig, load_strategy_config
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

# 每个策略解析到它自己的 Scanner 类。这不是命名偏好：一个由 YAML 权重决定的
# 通用实现，会让"Growth 的资格规则"和"Dividend 的资格规则"在代码里无处安放。
EXPECTED_SCANNERS: dict[str, str] = {
    "momentum": "MomentumScanner",
    "growth": "GrowthScanner",
    "quality": "QualityScanner",
    "dividend": "DividendScanner",
    "value": "ValueScanner",
    "garp": "GarpScanner",
}


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


def test_six_scanners_run_and_one_reports_what_it_waits_for() -> None:
    # 实现必须显式登记：不再靠"YAML 里有没有权重"来推断该用哪个类。
    assert set(IMPLEMENTATIONS) == set(EXPECTED_SCANNERS)
    assert {item.config.id for item in load_scanners(CONFIGS)} == {
        "dividend",
        "garp",
        "growth",
        "momentum",
        "quality",
        "value",
    }
    assert set(unimplemented_scanners(CONFIGS)) == {"industry_trend"}


def test_every_configured_strategy_resolves_to_its_own_scanner() -> None:
    """六个在打分的策略各自拥有独立 Scanner 边界。"""
    for strategy_id, class_name in EXPECTED_SCANNERS.items():
        config = load_strategy_config(CONFIGS / f"{strategy_id}.yaml")

        scanner = build_scanner(config)

        assert type(scanner).__name__ == class_name, strategy_id


def test_the_registry_no_longer_infers_an_implementation_from_weights() -> None:
    """权重是配置，不是类型判定器：有权重不再自动变成同一个类。"""
    config = load_strategy_config(CONFIGS / "growth.yaml")

    assert config.weights
    assert type(build_scanner(config)).__name__ == "GrowthScanner"


def test_the_blocked_scanners_name_a_missing_input() -> None:
    reasons = dict(unimplemented_reasons(CONFIGS))

    assert "industry data" in reasons["industry_trend"]


def test_a_blocked_scanner_says_why_when_it_is_asked_to_run() -> None:
    with pytest.raises(StrategyNotImplementedError) as raised:
        build_scanner(_config("industry_trend"))

    message = str(raised.value)
    assert "no implementation" in message
    assert "industry data" in message


def test_the_built_scanners_bind_to_the_class_the_registry_names() -> None:
    loaded = {item.config.id: item.plugin for item in load_scanners(CONFIGS)}

    assert isinstance(loaded["momentum"], MomentumScanner)
    for strategy_id, class_name in EXPECTED_SCANNERS.items():
        assert type(loaded[strategy_id]).__name__ == class_name
        assert loaded[strategy_id].required_factors()


def test_an_unregistered_strategy_is_refused_even_when_it_has_weights() -> None:
    """权重不再是"可运行"的依据：没登记实现就是没实现。"""
    unregistered = _config(
        "someone_elses_idea",
        required_factors=["roe_ttm"],
        weights={"roe_ttm": 1.0},
    )

    with pytest.raises(StrategyNotImplementedError):
        build_scanner(unregistered)


def test_a_registered_strategy_still_needs_reviewed_weights() -> None:
    """登记了类也不够：没有已评审的权重，打分无从谈起。"""
    without_weights = _config("quality", required_factors=["roe_ttm"])

    with pytest.raises(ValueError, match="declares no weights"):
        build_scanner(without_weights)


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
