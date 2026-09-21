"""Unit tests for deterministic primary qualified strategy context.

Spec: docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md
Plan: docs/superpowers/plans/2026-09-21-candidate-correctness-safety-gate.md Task 2
"""

from datetime import UTC, datetime

import pytest

from astock_lens.candidates.context import primary_qualified_strategy
from astock_lens.candidates.models import Candidate
from astock_lens.domain.enums import NextAction
from astock_lens.domain.models import SnapshotLineage
from astock_lens.qualifications.models import StrategyQualification

AS_OF = datetime(2026, 9, 21, 15, 0, tzinfo=UTC)


def _qual(
    strategy_id: str, percentile: float, is_qualified: bool
) -> StrategyQualification:
    return StrategyQualification(
        symbol="600000.SH",
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version="v1",
        as_of=AS_OF,
        rank_percentile=percentile,
        rank=1,
        total_evaluable=100,
        percentile_pass=percentile >= 0.90,
        absolute_pass=is_qualified,
        qualified=is_qualified,
    )


def test_highest_qualified_percentile_wins() -> None:
    """Step 1: 最高百分位的合格策略获胜。"""
    quals = [
        _qual("value", 0.92, True),
        _qual("growth", 0.95, True),
    ]
    assert primary_qualified_strategy(quals) == "growth"


def test_equal_percentile_resolves_by_strategy_id_ascending() -> None:
    """Step 2: 百分位相同按 strategy_id 字母升序决胜。"""
    quals = [
        _qual("value", 0.95, True),
        _qual("growth", 0.95, True),
        _qual("garp", 0.95, True),
    ]
    assert primary_qualified_strategy(quals) == "garp"


def test_unqualified_strategy_never_wins_even_with_higher_percentile() -> None:
    """Step 3: 未合格策略即使百分位更高也绝不获胜。"""
    quals = [
        _qual("momentum", 0.99, False),
        _qual("value", 0.91, True),
    ]
    assert primary_qualified_strategy(quals) == "value"


def test_no_qualified_strategy_raises_explicit_value_error() -> None:
    """Step 4: 无任何合格策略时抛出明确的 ValueError。"""
    unqualified = [
        _qual("momentum", 0.85, False),
        _qual("growth", 0.70, False),
    ]
    with pytest.raises(ValueError, match="no qualified strategy"):
        primary_qualified_strategy(unqualified)

    with pytest.raises(ValueError, match="no qualified strategy"):
        primary_qualified_strategy([])


def test_candidate_model_carries_primary_strategy_id() -> None:
    """Step 6: Candidate 模型持久化 primary_strategy_id 字段。"""
    candidate = Candidate(
        symbol="600000.SH",
        as_of=AS_OF,
        next_action=NextAction.WATCH,
        lineage=SnapshotLineage(candidate_policy_version="v1"),
        primary_strategy_id="growth",
    )
    assert candidate.primary_strategy_id == "growth"
    dumped = candidate.model_dump(mode="json")
    assert dumped["primary_strategy_id"] == "growth"
