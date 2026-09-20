"""Contracts and protocols for strategy qualification."""

from typing import Protocol

from astock_lens.qualifications.models import (
    AbsoluteQualificationVerdict,
    QualificationContext,
    StrategyQualification,
)


class QualificationRuleNotConfigured(RuntimeError):
    """Raised when an enabled strategy does not have an approved absolute qualification rule."""


class AbsoluteQualificationRule(Protocol):
    """Protocol for an approved strategy-specific absolute quality rule."""

    version: str

    def evaluate(self, context: QualificationContext) -> AbsoluteQualificationVerdict:
        """Evaluate the symbol's full qualification evidence against absolute criteria."""
        ...


class StrategyQualifier(Protocol):
    """Protocol for evaluating whether a strategy result qualifies for research candidate status."""

    strategy_id: str
    qualification_version: str

    def qualify(self, context: QualificationContext) -> StrategyQualification:
        """Evaluate a symbol against both percentile and absolute quality gates."""
        ...
