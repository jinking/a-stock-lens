"""股票发现查询层服务逻辑。"""

from collections.abc import Sequence

from astock_lens.discovery.models import (
    StrategyCoverage,
    StrategyScreenItem,
    StrategyScreenQuery,
    StrategyScreenResult,
)
from astock_lens.strategies.contracts import StrategyResult


def _screen_sort_key(result: StrategyResult) -> tuple[int, float, int, float, str]:
    """确定性排序键：

    1. 有 percentile 的排在前面 (is None ASC: False -> 0, True -> 1)
    2. percentile DESC (-(percentile or 0.0))
    3. 有 score 的排在前面 (is None ASC: False -> 0, True -> 1)
    4. score DESC (-(score or 0.0))
    5. symbol ASC (字典序升序)

    0.0 仅在 is None 判别后参与 tie-breaker 占位，绝不作为实际观测值返回。
    """
    return (
        result.rank_percentile is None,
        -(result.rank_percentile or 0.0),
        result.score is None,
        -(result.score or 0.0),
        result.symbol,
    )


def screen_strategy(
    results: Sequence[StrategyResult],
    query: StrategyScreenQuery,
) -> StrategyScreenResult:
    """根据查询条件筛选并排序策略评估结果。"""
    if query.limit <= 0:
        raise ValueError(f"limit must be positive, got {query.limit}")
    if query.min_percentile is not None and not (0.0 <= query.min_percentile <= 1.0):
        raise ValueError(
            f"min_percentile must be between 0.0 and 1.0, got {query.min_percentile}"
        )

    # 仅提取匹配该策略的结果
    strategy_results = [r for r in results if r.strategy_id == query.strategy_id]

    # 覆盖率在应用 filter 与 limit 之前计算
    coverage = StrategyCoverage(
        strategy_id=query.strategy_id,
        total_count=len(strategy_results),
        eligible_count=sum(1 for r in strategy_results if r.eligible),
        scored_count=sum(1 for r in strategy_results if r.score is not None),
        ranked_count=sum(1 for r in strategy_results if r.rank_percentile is not None),
    )

    # 过滤
    filtered: list[StrategyResult] = []
    for r in strategy_results:
        if query.eligible_only and not r.eligible:
            continue
        if query.min_percentile is not None and (
            r.rank_percentile is None or r.rank_percentile < query.min_percentile
        ):
            continue
        filtered.append(r)

    # 排序
    filtered.sort(key=_screen_sort_key)

    # 截取 limit
    limited = filtered[: query.limit]

    # 构建结果条目
    items = tuple(
        StrategyScreenItem(
            rank=idx + 1,
            symbol=r.symbol,
            strategy_id=r.strategy_id,
            strategy_version=r.strategy_version,
            score=r.score,
            rank_percentile=r.rank_percentile,
            confidence=r.confidence,
            eligible=r.eligible,
            reasons=r.reasons,
            risks=r.risks,
        )
        for idx, r in enumerate(limited)
    )

    return StrategyScreenResult(
        strategy_id=query.strategy_id,
        coverage=coverage,
        items=items,
    )


def summarize_strategies(
    results: Sequence[StrategyResult],
) -> tuple[StrategyCoverage, ...]:
    """汇总快照中所有策略的覆盖度情况，按 strategy_id 字典序排序。"""
    by_strategy: dict[str, list[StrategyResult]] = {}
    for r in results:
        by_strategy.setdefault(r.strategy_id, []).append(r)

    coverages: list[StrategyCoverage] = []
    for strategy_id in sorted(by_strategy.keys()):
        group = by_strategy[strategy_id]
        coverages.append(
            StrategyCoverage(
                strategy_id=strategy_id,
                total_count=len(group),
                eligible_count=sum(1 for r in group if r.eligible),
                scored_count=sum(1 for r in group if r.score is not None),
                ranked_count=sum(1 for r in group if r.rank_percentile is not None),
            )
        )

    return tuple(coverages)
