"""Common helpers for strategy qualification."""

from astock_lens.qualifications.contracts import AbsoluteQualificationRule
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

TOP_TEN_PERCENT_FLOOR = 0.90


def passes_percentile(result: StrategyResult) -> bool:
    """Return True if strategy result passes the Top-10% percentile gate."""
    percentile = result.rank_percentile
    if percentile is None:
        raise ValueError("rank_percentile is required for qualification")
    return percentile >= TOP_TEN_PERCENT_FLOOR


def build_qualification(
    *,
    result: StrategyResult,
    expected_strategy_id: str,
    qualification_version: str,
    absolute_rule: AbsoluteQualificationRule,
) -> StrategyQualification:
    """Assemble a StrategyQualification applying both percentile and absolute gates."""
    if result.strategy_id != expected_strategy_id:
        raise ValueError(
            f"Strategy ID mismatch: expected '{expected_strategy_id}', got '{result.strategy_id}'"
        )
    if not qualification_version or not qualification_version.strip():
        raise ValueError("qualification_version cannot be empty")

    percentile_pass = passes_percentile(result)
    assert result.rank_percentile is not None

    verdict = absolute_rule.evaluate(result)
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
        reasons=verdict.reasons,
        risks=verdict.risks,
    )
