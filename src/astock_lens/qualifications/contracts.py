"""Contracts and protocols for strategy qualification."""

from typing import Protocol

from astock_lens.qualifications.models import (
    AbsoluteQualificationVerdict,
    StrategyQualification,
)
from astock_lens.strategies.contracts import StrategyResult


class QualificationRuleNotConfigured(RuntimeError):
    """Raised when an enabled strategy does not have an approved absolute qualification rule."""


class AbsoluteQualificationRule(Protocol):
    """Protocol for an approved strategy-specific absolute quality rule."""

    version: str

    def evaluate(self, result: StrategyResult) -> AbsoluteQualificationVerdict:
        """Evaluate strategy result against absolute quality criteria."""
        ...


class StrategyQualifier(Protocol):
    """Protocol for evaluating whether a strategy result qualifies for research candidate status."""

    strategy_id: str
    qualification_version: str

    def qualify(self, result: StrategyResult) -> StrategyQualification:
        """Evaluate a strategy result against both percentile and absolute quality gates."""
        ...
