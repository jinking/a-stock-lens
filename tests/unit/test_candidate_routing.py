"""入选判定到候选动作的翻译。

这里只做最后一步映射：被批准的 Candidate Policy 说"入选"，候选动作才是
`WATCH`；说"不入选"，就是 `IGNORE`。动作**不再**由分数推出来——旧规则
「有分数就 WATCH」已经在 Task 7 被删除，本文件同时钉住它不许回来。

`DEEP_RESEARCH` 与 `TRACK_SIGNAL` 需要 Signal 层，而该层至今没有实现，所以
它们依然不可达：猜一个触发条件等于替项目所有者做产品决定。
"""

from datetime import UTC, datetime

import pytest

from astock_lens.candidates import routing
from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.policy import CandidateQualification
from astock_lens.candidates.routing import next_action_for
from astock_lens.domain.enums import NextAction
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _result(*, eligible: bool, score: float | None) -> StrategyResult:
    return StrategyResult(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
    )


def test_a_qualified_verdict_routes_to_watch() -> None:
    qualification = CandidateQualification(qualified=True, reasons=("policy",))

    assert next_action_for(qualification) is NextAction.WATCH


def test_an_unqualified_verdict_routes_to_ignore() -> None:
    qualification = CandidateQualification(qualified=False, reasons=("policy",))

    assert next_action_for(qualification) is NextAction.IGNORE


def test_only_two_of_the_four_actions_are_reachable() -> None:
    """另外两个动作需要 Signal 层，这一阶段没有建它。"""
    reached = {
        next_action_for(CandidateQualification(qualified=True)),
        next_action_for(CandidateQualification(qualified=False)),
    }

    assert reached == {NextAction.WATCH, NextAction.IGNORE}


def test_the_routed_action_reaches_a_candidate() -> None:
    result = _result(eligible=True, score=87.5)

    candidate = CandidateBuilder().build(
        "600000.SH",
        as_of=AS_OF,
        strategy_results=(result,),
        lineage=SnapshotLineage(strategy_version="v1"),
        next_action=next_action_for(CandidateQualification(qualified=True)),
    )

    assert candidate.next_action is NextAction.WATCH
    assert candidate.strategy_results == (result,)


def test_the_translation_is_pure() -> None:
    """同样的判定永远得到同样的动作，不累积任何状态。"""
    qualification = CandidateQualification(qualified=True)

    assert next_action_for(qualification) == next_action_for(qualification)


@pytest.mark.parametrize("score", [0.0, 0.001, 50.0, 99.999, 100.0])
def test_no_score_range_can_produce_a_candidate_action(score: float) -> None:
    """分数不再是任何一个动作的输入，任何一个区间都不例外。"""
    del score

    assert not hasattr(routing, "route_next_action")
    assert not hasattr(routing, "route_candidate_actions")
