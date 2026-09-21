"""候选股票发现查询服务。

权威顺序以已存储的 Candidate 快照中的顺序为准，不发明任何新的排序；
提取主策略与全部合格策略，透传技术信号与风险警示。
"""

from collections.abc import Sequence
from datetime import datetime

from astock_lens.candidates.models import Candidate
from astock_lens.discovery.models import CandidateScreenItem, CandidateScreenResult


def screen_candidates(
    records: Sequence[Candidate],
    *,
    as_of: datetime | None = None,
    limit: int | None = None,
) -> CandidateScreenResult:
    """按存储权威顺序返回候选股票发现结果。

    - 严禁重新计算评分或自创跨策略排序；
    - 完整保留主策略与全部合格策略标识；
    - 风险信号与警告保持显式透传，不掩盖不降权。
    """
    effective_as_of = as_of
    if effective_as_of is None:
        if records:
            effective_as_of = records[0].as_of
        else:
            raise ValueError("as_of must be provided when records is empty")

    items: list[CandidateScreenItem] = []
    total_count = len(records)
    selected = records[:limit] if limit is not None and limit > 0 else records

    for rank, cand in enumerate(selected, start=1):
        qualified_ids = tuple(
            q.strategy_id for q in cand.strategy_qualifications if q.qualified
        )
        if not qualified_ids:
            qualified_ids = tuple(
                r.strategy_id
                for r in cand.strategy_results
                if r.rank_percentile is not None and r.rank_percentile >= 0.90
            )

        pcts = [
            q.rank_percentile
            for q in cand.strategy_qualifications
            if q.qualified and q.rank_percentile is not None
        ]
        if not pcts:
            pcts = [
                r.rank_percentile
                for r in cand.strategy_results
                if r.rank_percentile is not None
            ]
        best_pct = max(pcts) if pcts else 0.0

        items.append(
            CandidateScreenItem(
                rank=rank,
                symbol=cand.symbol,
                primary_strategy_id=cand.primary_strategy_id,
                qualified_strategy_ids=qualified_ids,
                best_rank_percentile=round(float(best_pct), 4),
                market_validation=cand.market_validation,
                signal=cand.signal,
                next_action=cand.next_action,
                reasons=cand.reasons,
                risks=cand.risks,
            )
        )

    return CandidateScreenResult(
        as_of=effective_as_of,
        total_count=total_count,
        items=tuple(items),
    )
