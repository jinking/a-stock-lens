"""入选判定到候选动作的翻译。

这个模块只做最后一步：被批准的 Candidate Policy 说"入选"，候选动作就是
`WATCH`；说"不入选"，就是 `IGNORE`。

它**不再**从分数推出动作。旧规则「eligible 且带分数 → WATCH」把"这个策略
拿到了输入"当成了产品结论，等于用一个没人批准过的阈值取代入选规则；本阶段
删除了它，判定责任整体移交给 `CandidatePolicy`。

`DEEP_RESEARCH` 与 `TRACK_SIGNAL` 依赖 Signal 层，而该层至今没有实现：让它
们不可达是诚实的，猜一个触发条件是替项目所有者做决定。
"""

from astock_lens.candidates.policy import CandidateQualification
from astock_lens.domain.enums import NextAction


def next_action_for(qualification: CandidateQualification) -> NextAction:
    """把一次入选判定翻译成候选动作。"""
    return NextAction.WATCH if qualification.qualified else NextAction.IGNORE
