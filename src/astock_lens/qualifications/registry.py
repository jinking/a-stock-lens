"""Registry and factory for strategy qualifiers."""

from collections.abc import Mapping
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
