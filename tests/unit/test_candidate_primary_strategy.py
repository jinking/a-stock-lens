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


# 「合格策略的决胜规则」三行：行序与原用例一致，label 即原测试名，
# 原 docstring 逐字保留为行注释。
# 列 = label, quals, expected：
#   - `quals` 逐行保留原 `_qual(...)` 列表；
#   - `expected` 即原 `primary_qualified_strategy(quals) == "<策略 id>"` 的字面量，
#     比对方式同为 `==`。
PRIMARY_STRATEGY_CASES = (
    # test_highest_qualified_percentile_wins:
    #   Step 1: 最高百分位的合格策略获胜。
    (
        "test_highest_qualified_percentile_wins",
        [
            _qual("value", 0.92, True),
            _qual("growth", 0.95, True),
        ],
        "growth",
    ),
    # test_equal_percentile_resolves_by_strategy_id_ascending:
    #   Step 2: 百分位相同按 strategy_id 字母升序决胜。
    (
        "test_equal_percentile_resolves_by_strategy_id_ascending",
        [
            _qual("value", 0.95, True),
            _qual("growth", 0.95, True),
            _qual("garp", 0.95, True),
        ],
        "garp",
    ),
    # test_unqualified_strategy_never_wins_even_with_higher_percentile:
    #   Step 3: 未合格策略即使百分位更高也绝不获胜。
    (
        "test_unqualified_strategy_never_wins_even_with_higher_percentile",
        [
            _qual("momentum", 0.99, False),
            _qual("value", 0.91, True),
        ],
        "value",
    ),
)


def test_primary_qualified_strategy_selection_rules() -> None:
    """三个决胜步骤各自选出预期策略 id。

    原 3 条「Step 1/2/3」用例逐条成行；循环只收集，断言在表外一次完成，
    失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, quals, expected in PRIMARY_STRATEGY_CASES:
        selected = primary_qualified_strategy(quals)
        if selected != expected:
            wrong.append(f"{label}: 选出 {selected!r}，期望 {expected!r}")
    assert not wrong, "primary 策略选择不符合决胜规则:\n" + "\n".join(wrong)


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
