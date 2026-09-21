"""今日盘后候选研究概览（Today Read Model）。

基于已存储的快照数据进行只读聚合，不调用 Provider，不重新计算任何因子或评分。
权威顺序以 Candidate 快照中存储的顺序为准。
"""

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from pydantic import Field

from astock_lens.candidates.models import Candidate
from astock_lens.discovery.candidates import screen_candidates
from astock_lens.discovery.models import CandidateScreenItem
from astock_lens.domain.enums import MarketRegime
from astock_lens.domain.models import DomainRecord


class TodayOverview(DomainRecord):
    """盘后候选研究概览只读聚合模型。"""

    as_of: datetime
    candidate_count: int
    market_regime: MarketRegime | None = None
    counts_by_primary_strategy: dict[str, int] = Field(default_factory=dict)
    counts_by_market_validation: dict[str, int] = Field(default_factory=dict)
    counts_by_signal: dict[str, int] = Field(default_factory=dict)
    top_candidates: tuple[CandidateScreenItem, ...] = ()


def build_today_overview(
    records: Sequence[Candidate],
    *,
    as_of: datetime,
    market_regime: MarketRegime | None = None,
    top_limit: int = 10,
) -> TodayOverview:
    """构建盘后候选研究概览。

    - 聚合统计严格基于传入的候选记录；
    - 维持快照中的原生权威顺序，展示前 top_limit 只标的；
    - 风险与各策略分布完全透明。
    """
    total = len(records)
    if total == 0:
        return TodayOverview(
            as_of=as_of,
            candidate_count=0,
            market_regime=market_regime,
            counts_by_primary_strategy={},
            counts_by_market_validation={},
            counts_by_signal={},
            top_candidates=(),
        )

    strat_counts = Counter(
        c.primary_strategy_id if c.primary_strategy_id else "unassigned"
        for c in records
    )

    mv_counts = Counter(
        c.market_validation.value if c.market_validation is not None else "NONE"
        for c in records
    )

    sig_counts = Counter(
        c.signal.value if c.signal is not None else "NO_SIGNAL" for c in records
    )

    screen_res = screen_candidates(records, as_of=as_of, limit=top_limit)

    return TodayOverview(
        as_of=as_of,
        candidate_count=total,
        market_regime=market_regime,
        counts_by_primary_strategy=dict(strat_counts),
        counts_by_market_validation=dict(mv_counts),
        counts_by_signal=dict(sig_counts),
        top_candidates=screen_res.items,
    )
