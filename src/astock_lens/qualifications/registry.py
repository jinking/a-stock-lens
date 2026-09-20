"""Registry and factory for strategy qualifiers."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from astock_lens.qualifications.contracts import (
    AbsoluteQualificationRule,
    QualificationRuleNotConfigured,
    StrategyQualifier,
)
from astock_lens.qualifications.dividend import DividendQualifier
from astock_lens.qualifications.garp import GARPQualifier
from astock_lens.qualifications.growth import GrowthQualifier
from astock_lens.qualifications.momentum import MomentumQualifier
from astock_lens.qualifications.quality import QualityQualifier
from astock_lens.qualifications.rules import load_qualification_rule
from astock_lens.qualifications.value import ValueQualifier

QUALIFIER_CLASSES: dict[str, type[Any]] = {
    "value": ValueQualifier,
    "growth": GrowthQualifier,
    "garp": GARPQualifier,
    "quality": QualityQualifier,
    "dividend": DividendQualifier,
    "momentum": MomentumQualifier,
}

CANONICAL_STRATEGY_IDS: tuple[str, ...] = (
    "value",
    "growth",
    "garp",
    "quality",
    "dividend",
    "momentum",
)


def build_qualifiers(
    absolute_rules: Mapping[str, AbsoluteQualificationRule],
    *,
    enabled_strategy_ids: tuple[str, ...] = CANONICAL_STRATEGY_IDS,
    default_version: str = "v1",
) -> dict[str, StrategyQualifier]:
    """Build concrete qualifiers for enabled strategies.

    Raises QualificationRuleNotConfigured if an enabled strategy does not have
    an injected approved absolute rule.
    """
    qualifiers: dict[str, StrategyQualifier] = {}
    for strategy_id in enabled_strategy_ids:
        rule = absolute_rules.get(strategy_id)
        if rule is None:
            raise QualificationRuleNotConfigured(
                f"Missing approved absolute qualification rule for strategy '{strategy_id}'"
            )
        qualifier_cls = QUALIFIER_CLASSES.get(strategy_id)
        if qualifier_cls is None:
            raise ValueError(f"Unknown strategy ID '{strategy_id}' for qualification")
        qualifier = qualifier_cls(
            absolute_rule=rule,
            qualification_version=rule.version or default_version,
        )
        qualifiers[strategy_id] = qualifier
    return qualifiers


QUALIFICATION_CONFIG_DIR_ENV = "ASTOCK_QUALIFICATION_DIR"
DEFAULT_QUALIFICATION_CONFIG_DIR = Path("configs/qualifications")


def load_canonical_qualifiers(
    config_dir: Path | None = None,
    *,
    enabled_strategy_ids: tuple[str, ...] = CANONICAL_STRATEGY_IDS,
    known_factor_names: frozenset[str] | None = None,
) -> dict[str, StrategyQualifier]:
    """Load canonical qualifiers for enabled strategies from configuration directory.

    每个文件以严格模式加载：``expected_strategy_id`` 校验文件名与内容一致，
    ``known_factor_names``（若非 None）校验因子目录。

    - 任一启用策略缺少配置文件 → ``QualificationRuleNotConfigured``（= 未配置）；
    - 配置文件畸形或非法 → ``QualificationConfigInvalid``（= 配置损坏，向上抛出，绝不降级）。
    """
    if config_dir is not None:
        target_dir = config_dir
    else:
        env_val = os.getenv(QUALIFICATION_CONFIG_DIR_ENV)
        target_dir = Path(env_val) if env_val else DEFAULT_QUALIFICATION_CONFIG_DIR

    rules: dict[str, AbsoluteQualificationRule] = {}
    for strat_id in enabled_strategy_ids:
        cfg_file = target_dir / f"{strat_id}.yaml"
        if not cfg_file.is_file():
            raise QualificationRuleNotConfigured(
                f"Missing approved absolute qualification rule for strategy '{strat_id}': "
                f"expected file {cfg_file}"
            )
        rules[strat_id] = load_qualification_rule(
            cfg_file,
            expected_strategy_id=strat_id,
            known_factor_names=known_factor_names,
        )

    return build_qualifiers(rules, enabled_strategy_ids=enabled_strategy_ids)
