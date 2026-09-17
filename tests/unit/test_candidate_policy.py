"""候选资格判定必须是显式策略，不能从分数推出来。

计划 `a-stock-lens-core-hardening-plan.md` Task 7 移除的旧规则是：

    只要有任何 Scanner 给出 eligible 且带分数的结果 → WATCH

"有分数"只说明这个策略拿到了输入，它是测量的存在性，不是任何一个被批准过的
入选规则。本文件钉住替代它的边界：

* 没有批准的 policy 时，Candidate 阶段**明确报错**，而不是安静地返回空集；
* policy 说入选，才有 Candidate；policy 说不入选，分数再高也没有 Candidate；
* Builder 不参与资格判定，它只组装证据。

本阶段**不提供**任何未经批准的 Top-N / 百分位 / 绝对阈值实现。
"""

from datetime import UTC, datetime

import pytest

from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.policy import (
    CandidatePolicyNotConfigured,
    CandidateQualification,
)
from astock_lens.domain.enums import NextAction
from astock_lens.domain.models import SnapshotLineage
from astock_lens.pipelines.stages import candidate_stage
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LINEAGE = SnapshotLineage(universe_snapshot="2026-09-04:abc", strategy_version="v1")


def _result(
    *, eligible: bool = True, score: float | None = 88.0, symbol: str = "600000.SH"
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id="momentum",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
    )


class _ApprovesNothing:
    """一个策略的示例：它什么都不批准。"""

    def qualify(
        self,
        *,
        strategy_results: tuple[StrategyResult, ...],
        market_validation: object | None,
        signal: object | None,
    ) -> CandidateQualification:
        del strategy_results, market_validation, signal
        return CandidateQualification(qualified=False, reasons=("no approved rule",))


class _ApprovesEverything:
    """只用于证明"资格来自 policy 的判定"，它不是任何被批准的业务规则。"""

    def qualify(
        self,
        *,
        strategy_results: tuple[StrategyResult, ...],
        market_validation: object | None,
        signal: object | None,
    ) -> CandidateQualification:
        del market_validation, signal
        return CandidateQualification(
            qualified=bool(strategy_results), reasons=("policy said so",)
        )


def test_no_reviewed_policy_is_an_error_not_an_empty_scan() -> None:
    """没有批准的规则时，Candidate 阶段必须明确报错。

    安静地返回空集会让"还没决定"和"今天没有标的入选"长得一模一样。
    """
    with pytest.raises(CandidatePolicyNotConfigured):
        candidate_stage(
            strategy_results=(_result(),),
            lineage=LINEAGE,
            as_of=AS_OF,
            policy=None,
        )


def test_a_policy_that_qualifies_nothing_produces_no_candidate() -> None:
    candidates = candidate_stage(
        strategy_results=(_result(score=100.0),),
        lineage=LINEAGE,
        as_of=AS_OF,
        policy=_ApprovesNothing(),
    )

    assert candidates == ()


def test_the_policy_is_what_makes_a_candidate() -> None:
    candidates = candidate_stage(
        strategy_results=(_result(score=12.0),),
        lineage=LINEAGE,
        as_of=AS_OF,
        policy=_ApprovesEverything(),
    )

    assert len(candidates) == 1
    assert candidates[0].symbol == "600000.SH"
    assert candidates[0].next_action is NextAction.WATCH


@pytest.mark.parametrize("score", [0.0, 50.0, 100.0])
def test_the_score_never_decides_the_action(score: float) -> None:
    """分数只影响排名，不影响入选：未入选的 policy 下没有候选。"""
    candidates = candidate_stage(
        strategy_results=(_result(score=score),),
        lineage=LINEAGE,
        as_of=AS_OF,
        policy=_ApprovesNothing(),
    )

    assert candidates == ()


def test_the_builder_does_not_derive_next_action_from_a_score() -> None:
    """Builder 拿不到 policy 的判定，所以它不可能替 policy 做决定。"""
    candidate = CandidateBuilder().build(
        "600000.SH",
        as_of=AS_OF,
        strategy_results=(_result(score=100.0),),
        lineage=LINEAGE,
    )

    assert candidate.next_action is NextAction.IGNORE


def test_a_policy_verdict_is_ineligible_without_eligible_evidence() -> None:
    """没有资格成立的结果时，policy 不会被问到"要不要入选"。"""
    candidates = candidate_stage(
        strategy_results=(_result(eligible=False, score=99.0),),
        lineage=LINEAGE,
        as_of=AS_OF,
        policy=_ApprovesEverything(),
    )

    assert candidates == ()
