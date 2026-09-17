"""候选资格判定（Candidate Qualification）的显式边界。

Candidate 是研究对象，不是推荐；"哪些标的值得进入研究"因此是一个产品判断，
而不是一个工程默认值。本模块只提供这个判断的**接口**与它的缺席方式：

* `CandidatePolicy` 是一个 Protocol：调用方注入一个已批准的规则；
* `CandidateQualification` 带着判定结果与理由；
* `CandidatePolicyNotConfigured` 是"还没有批准过任何规则"的声音。

本阶段**不提供任何实现**。Top-N、每策略百分位、绝对阈值、以及它们的混合，
都是 Owner Decision Gate（见 `docs/ROADMAP.md` 第一节），写进代码就等于替
项目所有者做了产品决定。`astock daily` 在没有 policy 时把 `BUILD_CANDIDATES`
记为 `BLOCKED` 并引用下面这句话，而不是悄悄产出一批候选。
"""

from collections.abc import Sequence
from typing import Protocol

from astock_lens.domain.enums import MarketValidation, Signal
from astock_lens.domain.models import DomainRecord
from astock_lens.strategies.contracts import StrategyResult

CANDIDATE_POLICY_DEFERRED = (
    "candidate qualification policy is Deferred: no approved rule exists, so no "
    "Candidate may be published (a measured score is not a qualification)"
)


class CandidateQualification(DomainRecord):
    """一次入选判定的结果，以及它为什么这么判。"""

    qualified: bool
    reasons: tuple[str, ...] = ()


class CandidatePolicy(Protocol):
    """把策略、市场与信号证据翻译成一次入选判定的规则。"""

    def qualify(
        self,
        *,
        strategy_results: Sequence[StrategyResult],
        market_validation: MarketValidation | None,
        signal: Signal | None,
    ) -> CandidateQualification:
        """决定一只股票是否值得成为 Candidate，并说明理由。"""
        ...


class CandidatePolicyNotConfigured(RuntimeError):
    """没有已批准入选规则时抛出的错误。

    这不是"今天没有标的入选"：前者是流程缺一个决定，后者是一个结论。把两者
    混成同一个空集，读的人无从分辨。
    """
