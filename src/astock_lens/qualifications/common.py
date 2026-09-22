"""Common helpers for strategy qualification."""

from astock_lens.qualifications.contracts import AbsoluteQualificationRule
from astock_lens.qualifications.models import (
    QualificationContext,
    StrategyQualification,
)
from astock_lens.strategies.contracts import StrategyResult

TOP_TEN_PERCENT_FLOOR = 0.90


class ConfiguredQualifier:
    """Use one configured implementation for every strategy qualifier."""

    def __init__(
        self,
        *,
        strategy_id: str,
        absolute_rule: AbsoluteQualificationRule,
        qualification_version: str,
    ) -> None:
        self.strategy_id = strategy_id
        self.absolute_rule = absolute_rule
        self.qualification_version = qualification_version

    def qualify(self, context: QualificationContext) -> StrategyQualification:
        return build_qualification(
            context=context,
            expected_strategy_id=self.strategy_id,
            qualification_version=self.qualification_version,
            absolute_rule=self.absolute_rule,
        )


def passes_percentile(result: StrategyResult) -> bool:
    """Return True if strategy result passes the Top-10% percentile gate."""
    percentile = result.rank_percentile
    if percentile is None:
        raise ValueError("rank_percentile is required for qualification")
    return percentile >= TOP_TEN_PERCENT_FLOOR


def build_qualification(
    *,
    context: QualificationContext,
    expected_strategy_id: str,
    qualification_version: str,
    absolute_rule: AbsoluteQualificationRule,
) -> StrategyQualification:
    """Assemble a StrategyQualification applying both percentile and absolute gates.

    百分位门槛读取策略结果本身；绝对资格门槛读取 ``context``，从而获得该股票
    完整 Factor 证据，而不仅是策略评分快照。
    """
    result = context.strategy_result
    if result.strategy_id != expected_strategy_id:
        raise ValueError(
            f"Strategy ID mismatch: expected '{expected_strategy_id}', got '{result.strategy_id}'"
        )
    if not qualification_version or not qualification_version.strip():
        raise ValueError("qualification_version cannot be empty")

    percentile_pass = passes_percentile(result)
    assert result.rank_percentile is not None

    verdict = absolute_rule.evaluate(context)
    qualified = percentile_pass and verdict.passed

    return StrategyQualification(
        symbol=result.symbol,
        strategy_id=result.strategy_id,
        strategy_version=result.strategy_version,
        qualification_version=qualification_version,
        qualified=qualified,
        percentile_pass=percentile_pass,
        absolute_pass=verdict.passed,
        rank_percentile=result.rank_percentile,
        as_of=result.as_of,
        reasons=verdict.reasons,
        risks=verdict.risks,
    )
