"""入选判定到候选动作的翻译。

这个模块只做最后一步：被批准的 Candidate Policy 说"入选"（CandidateSelection），
候选动作就是 `WATCH`；未入选就是 `IGNORE`。
"""

from astock_lens.candidates.policy import CandidateQualification, CandidateSelection
from astock_lens.domain.enums import NextAction


def next_action_for(
    qualification: CandidateQualification | CandidateSelection | None,
) -> NextAction:
    """把一次入选判定翻译成候选动作。入选则为 WATCH，未入选则为 IGNORE。"""
    if qualification is None:
        return NextAction.IGNORE
    if isinstance(qualification, CandidateSelection):
        return NextAction.WATCH
    return NextAction.WATCH if getattr(qualification, "qualified", False) else NextAction.IGNORE
