"""双门槛合格股票发现纯函数服务。

只读发现层：对已存储的 FACTOR / STRATEGY 快照数据执行「Top10% +
已批准绝对门槛」双门槛判定（判定本身委托给注入的 ``StrategyQualifier``），
只返回双通过（qualified）的结果。本模块是纯函数，不做 I/O，也不得
import ``astock_lens.pipelines``。
"""

from collections.abc import Mapping, Sequence

from astock_lens.discovery.models import (
    QualifiedCoverage,
    QualifiedScreenItem,
    QualifiedScreenQuery,
    QualifiedScreenResult,
)
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.contracts import StrategyQualifier
from astock_lens.qualifications.models import (
    QualificationContext,
    StrategyQualification,
)
from astock_lens.strategies.contracts import StrategyResult


def _qualified_sort_key(
    pair: tuple[StrategyQualification, StrategyResult],
) -> tuple[float, int, float, str]:
    """确定性排序键：

    1. rank_percentile DESC（判定对象必有 percentile，直接取负）
    2. 有 score 的排在前面（is None ASC: False -> 0, True -> 1）
    3. score DESC（-(score or 0.0)；0.0 仅作 tie-breaker 占位，
       绝不把缺失的 score 静默变成观测值 0）
    4. symbol ASC（字典序升序）
    """
    qualification, result = pair
    return (
        -qualification.rank_percentile,
        result.score is None,
        -(result.score or 0.0),
        result.symbol,
    )


def screen_qualified(
    *,
    factor_results: Sequence[FactorResult],
    strategy_results: Sequence[StrategyResult],
    qualifiers: Mapping[str, StrategyQualifier],
    query: QualifiedScreenQuery,
) -> QualifiedScreenResult:
    """对指定策略执行双门槛合格判定，只返回双通过的结果。

    - qualifier 必须已注册：缺失时抛出 ``KeyError``，绝不返回「零合格」假装正常；
    - 覆盖度各计数在应用 limit 之前对该 strategy_id 的全量结果计算；
    - 仅 eligible 且 rank_percentile 非 None 的结果进入判定，
      其余只计入覆盖度；
    - 零合格时 ``warnings`` 非空，给出确定性的数据健康提示。
    """
    if query.limit <= 0:
        raise ValueError(f"limit must be positive, got {query.limit}")
    if query.strategy_id not in qualifiers:
        # fail loudly：禁止把未注册的策略伪装成「零合格」
        raise KeyError(f"no qualifier registered for strategy_id {query.strategy_id!r}")
    qualifier = qualifiers[query.strategy_id]

    # 一次遍历构建因子索引：symbol -> 该股票的完整 FactorResult 集合
    factors_by_symbol: dict[str, list[FactorResult]] = {}
    for factor in factor_results:
        factors_by_symbol.setdefault(factor.symbol, []).append(factor)

    # 仅提取匹配该策略的结果
    matched = [r for r in strategy_results if r.strategy_id == query.strategy_id]

    strategy_eligible_count = sum(1 for r in matched if r.eligible)
    ranked_count = sum(1 for r in matched if r.rank_percentile is not None)

    # 判定对象：eligible 且已排名，与快照口径一致
    judged = [r for r in matched if r.eligible and r.rank_percentile is not None]
    qualifications = [
        (
            qualifier.qualify(
                QualificationContext(
                    strategy_result=r,
                    factors=tuple(factors_by_symbol.get(r.symbol, ())),
                )
            ),
            r,
        )
        for r in judged
    ]

    coverage = QualifiedCoverage(
        strategy_id=query.strategy_id,
        strategy_eligible_count=strategy_eligible_count,
        ranked_count=ranked_count,
        percentile_pass_count=sum(1 for q, _ in qualifications if q.percentile_pass),
        absolute_pass_count=sum(1 for q, _ in qualifications if q.absolute_pass),
        qualified_count=sum(1 for q, _ in qualifications if q.qualified),
    )

    qualified_pairs = [(q, r) for q, r in qualifications if q.qualified]
    qualified_pairs.sort(key=_qualified_sort_key)
    limited = qualified_pairs[: query.limit]

    items = tuple(
        QualifiedScreenItem(
            rank=idx + 1,
            symbol=q.symbol,
            strategy_id=q.strategy_id,
            strategy_version=q.strategy_version,
            qualification_version=q.qualification_version,
            score=r.score,
            rank_percentile=q.rank_percentile,
            reasons=q.reasons,
            risks=q.risks,
        )
        for idx, (q, r) in enumerate(limited)
    )

    warnings: tuple[str, ...] = ()
    if coverage.qualified_count == 0:
        # 数据健康提示：确定性文案，同输入同输出；不构成任何推荐
        zero_qualified_warning = (
            f"策略 {query.strategy_id} 在当前快照中无任何双门槛通过标的"
            f"（eligible={coverage.strategy_eligible_count}，"
            f"ranked={coverage.ranked_count}，"
            f"percentile_pass={coverage.percentile_pass_count}，"
            f"absolute_pass={coverage.absolute_pass_count}）；"
            "请检查因子与策略快照的覆盖度及数据质量。"
        )
        warnings = (zero_qualified_warning,)

    return QualifiedScreenResult(
        strategy_id=query.strategy_id,
        coverage=coverage,
        items=items,
        warnings=warnings,
    )
