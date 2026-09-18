"""决策级校准证据：因子分布与边界样本。

所有者要批的是"每个策略的绝对质量门槛"，所以证据必须能回答两个问题：

1. 这个因子在全池的真实分布长什么样（分位数、极值、以及多少标的根本没有值）；
2. 0.90 分位线上下各是谁，他们的实际因子值是多少——门槛往前挪一格会改变谁。

两条纪律写在实现里：

- **分位数只由有值的观测算**。`NULL` / `STALE` / `SOURCE_ERROR` 单独计数，绝不混进分布，
  也绝不当 0——那会把"没人测过"伪装成"测出来是 0"。
- **样本必须自带证据**：每个样本带上策略分数、分位、以及它真实用到的因子值与各自状态，
  这样读报告的人不用回去查快照。
"""

from collections.abc import Mapping, Sequence

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult

# 计划点名的六个分位。它们只是描述分布的坐标，不是产品阈值。
QUANTILE_LABELS: tuple[tuple[str, float], ...] = (
    ("p10", 0.10),
    ("p25", 0.25),
    ("p50", 0.50),
    ("p75", 0.75),
    ("p90", 0.90),
    ("p95", 0.95),
)

RANK_FLOOR = 0.90


class FactorDistribution(DomainRecord):
    """一个因子在全池的分布，加上每种"没有值"分别有多少。"""

    factor: str
    value_count: int
    null_count: int
    stale_count: int
    source_error_count: int
    quantiles: tuple[tuple[str, float], ...]
    min_value: float | None
    max_value: float | None


class BoundarySample(DomainRecord):
    """一个具体标的：它的分数、分位，以及它真实用到的因子值与状态。"""

    symbol: str
    strategy_id: str
    score: float | None
    rank_percentile: float
    factor_values: tuple[tuple[str, float | None, str], ...]


class CalibrationPopulation(DomainRecord):
    """报告覆盖的总体，以及产生它的口径。

    校准的总体必须与正式策略扫描一致，所以这里把三个计数和配置指纹一起记下来：
    读报告的人可以核对"这次校准用的是研究池，而不是全名单"。
    """

    broad_listing_count: int
    prefilter_count: int
    research_count: int
    research_ratio: float
    universe_config_digest: str | None = None
    min_average_turnover_20d: float | None = None
    min_listing_days: int | None = None
    factor_versions: tuple[tuple[str, str], ...] = ()
    strategy_versions: tuple[tuple[str, str], ...] = ()


def _quantile(values: Sequence[float], fraction: float) -> float:
    """最近秩法取分位：只在有值观测里选一个真实观测，不插值造点。"""
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[position]


def factor_distributions(
    factor_results: Sequence[FactorResult],
) -> tuple[FactorDistribution, ...]:
    """按因子汇总分布，因子名排序保证确定性。"""
    by_factor: dict[str, list[FactorResult]] = {}
    for result in factor_results:
        by_factor.setdefault(result.factor, []).append(result)

    distributions: list[FactorDistribution] = []
    for factor in sorted(by_factor):
        rows = by_factor[factor]
        values = [
            row.raw_value
            for row in rows
            if row.status is DataStatus.VALUE and row.raw_value is not None
        ]
        quantiles = (
            tuple(
                (label, _quantile(values, fraction))
                for label, fraction in QUANTILE_LABELS
            )
            if values
            else ()
        )
        distributions.append(
            FactorDistribution(
                factor=factor,
                value_count=len(values),
                null_count=sum(1 for row in rows if row.status is DataStatus.NULL),
                stale_count=sum(1 for row in rows if row.status is DataStatus.STALE),
                source_error_count=sum(
                    1 for row in rows if row.status is DataStatus.SOURCE_ERROR
                ),
                quantiles=quantiles,
                min_value=min(values) if values else None,
                max_value=max(values) if values else None,
            )
        )
    return tuple(distributions)


def strategy_factor_names(result: StrategyResult) -> tuple[str, ...]:
    """这个策略真正用到的因子名，取自它自己的证据而不是第二份手写映射。"""
    names = {contribution.factor for contribution in result.contributions}
    names.update(snapshot.factor for snapshot in result.factor_snapshot)
    return tuple(sorted(names))


def boundary_samples(
    results: Sequence[StrategyResult],
    *,
    strategy_id: str,
    top: int = 5,
    above: int = 5,
    below: int = 5,
) -> tuple[BoundarySample, ...]:
    """Top 样本 + 0.90 线上下各若干，按"头部 → 线上 → 线下"给出。

    排序键固定为 (分位降序, 分数降序, 代码升序)，因此同样的输入永远得到同样的样本。
    """
    ranked = [
        result
        for result in results
        if result.strategy_id == strategy_id
        and result.eligible
        and result.rank_percentile is not None
        and result.score is not None
    ]
    ranked.sort(key=lambda item: (-item.rank_percentile, -item.score, item.symbol))  # type: ignore[operator]

    head = ranked[:top]
    on_or_above = [
        item
        for item in ranked
        if item.rank_percentile >= RANK_FLOOR  # type: ignore[operator]
    ]
    lower = [
        item
        for item in ranked
        if item.rank_percentile < RANK_FLOOR  # type: ignore[operator]
    ]
    chosen = head + on_or_above[-above:] + lower[:below]

    samples: list[BoundarySample] = []
    seen: set[tuple[str, str]] = set()
    for item in chosen:
        key = (item.strategy_id, item.symbol)
        if key in seen:
            continue
        seen.add(key)
        samples.append(
            BoundarySample(
                symbol=item.symbol,
                strategy_id=item.strategy_id,
                score=item.score,
                rank_percentile=item.rank_percentile,  # type: ignore[arg-type]
                factor_values=tuple(
                    (snapshot.factor, snapshot.raw_value, snapshot.status.value)
                    for snapshot in sorted(
                        item.factor_snapshot, key=lambda snap: snap.factor
                    )
                ),
            )
        )
    return tuple(samples)


def factor_index(
    factor_results: Sequence[FactorResult],
) -> Mapping[tuple[str, str], FactorResult]:
    """(symbol, factor) → 结果，供样本回填使用。"""
    return {(result.symbol, result.factor): result for result in factor_results}
