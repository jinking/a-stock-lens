"""估值覆盖报告：研究池分母上，估值字段与策略估值侧因子各覆盖了多少只。

它存在的理由很具体：`value` 在 2,303 只研究池里只有 2 只可打分，`garp` 只有 1 只，
而在此之前没有任何产物能回答"差在哪几个字段、差在哪几只标的"。

三条纪律：

1. **分母必须是显式传入的研究池。** 拿"已落地的标的"当分母会把覆盖率算成 100%，
   那正是这份报告要防的错觉；缺名单直接报错。
2. **有值才算覆盖，缺失永不写成 0。** 只有 `available_at <= as_of` 且
   `value is not None` 的观测才算数。
3. **因子级判定复用 `ValuationFactor`，不在报告里重写符号规则。** 源站的 PEG 会出现
   负值，因子层把它判成 `NOT_APPLICABLE`（"这个量不存在"，不是"更便宜"）；报告若自己
   按"有值"数，就会报出比打分器多一倍的 GARP 覆盖。报告与打分器必须说同一句话。

本模块只读：不写数据集、不碰策略结果、不重算快照。
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from astock_lens.data.contracts import NormalizedDataset
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord, ValuationObservation
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorContext
from astock_lens.factors.valuation import VALUATION_FACTORS, ValuationFactor
from astock_lens.strategies.config import StrategyConfig


class MetricCoverage(DomainRecord):
    """一个估值字段在研究池上的覆盖：有值的标的与占比。"""

    metric: str
    symbols_with_value: tuple[str, ...]
    ratio: float


class ValuationFactorCoverage(DomainRecord):
    """一个估值因子在研究池上的覆盖（已应用因子的语义规则）。"""

    factor: str
    symbols_with_value: tuple[str, ...]
    ratio: float


class StrategyValuationCoverage(DomainRecord):
    """一个策略的估值侧覆盖。

    `valuation_factors` 是必需因子里属于估值域的；`non_valuation_factors`
    是其余必需因子（财报、行情），它们不由本报告判定，必须显式列出来，
    免得读者把"估值侧全覆盖"误读成"这个策略可以打分了"。

    没有估值侧必需因子的策略（例如 Momentum）在报告里 `scoreable_symbols` 为空：
    "估值侧不需要判定"不等于"2303 只都能靠估值打分"，空交集必须是空的。
    """

    strategy_id: str
    valuation_factors: tuple[str, ...]
    non_valuation_factors: tuple[str, ...]
    scoreable_symbols: tuple[str, ...]
    ratio: float
    blocking_factors: tuple[tuple[str, int], ...]


class ValuationCoverageReport(DomainRecord):
    """一次覆盖核对的全部结论。"""

    as_of: datetime
    universe_size: int
    covered_symbols: tuple[str, ...]
    uncovered_symbols: tuple[str, ...]
    metrics: tuple[MetricCoverage, ...]
    factors: tuple[ValuationFactorCoverage, ...]
    strategies: tuple[StrategyValuationCoverage, ...]

    def to_payload(self) -> dict[str, object]:
        """给 CLI / 缺口清单用的 JSON 形状。"""
        return self.model_dump(mode="json")


def valuation_coverage(
    observations: Sequence[ValuationObservation],
    *,
    as_of: datetime,
    universe: Sequence[str],
    strategy_configs: Sequence[StrategyConfig] = (),
    factor_configs: Sequence[FactorConfig] = (),
) -> ValuationCoverageReport:
    """在研究池分母上核对估值字段与策略估值侧因子的覆盖。"""
    symbols = tuple(dict.fromkeys(universe))
    if not symbols:
        raise ValueError(
            "估值覆盖报告需要显式的研究池名单；用已落地的标的当分母会把覆盖率"
            "算成 100%，那不是研究池的覆盖率"
        )

    dataset = NormalizedDataset(
        dataset="valuation", as_of=as_of, valuations=tuple(observations)
    )
    known = set(symbols)
    available = tuple(
        item
        for item in observations
        if item.available_at <= as_of and item.symbol in known
    )

    metrics = _metric_coverage(available, symbols=symbols)
    factors, factor_values = _factor_coverage(
        dataset=dataset, as_of=as_of, symbols=symbols, factor_configs=factor_configs
    )
    strategies = _strategy_coverage(
        symbols=symbols,
        strategy_configs=strategy_configs,
        factor_values=factor_values,
        declared_factors={config.name for config in factor_configs},
    )

    covered = tuple(
        symbol
        for symbol in symbols
        if any(item.value is not None and item.symbol == symbol for item in available)
    )
    covered_set = set(covered)
    return ValuationCoverageReport(
        as_of=as_of,
        universe_size=len(symbols),
        covered_symbols=covered,
        uncovered_symbols=tuple(
            symbol for symbol in symbols if symbol not in covered_set
        ),
        metrics=metrics,
        factors=factors,
        strategies=strategies,
    )


def _metric_coverage(
    available: Sequence[ValuationObservation], *, symbols: Sequence[str]
) -> tuple[MetricCoverage, ...]:
    """字段层覆盖：只看"这个指标有没有值"，不做语义判断。"""
    by_metric: dict[str, list[str]] = {}
    for item in available:
        if item.value is None:
            continue
        bucket = by_metric.setdefault(item.metric, [])
        if item.symbol not in bucket:
            bucket.append(item.symbol)
    return tuple(
        MetricCoverage(
            metric=metric,
            symbols_with_value=tuple(
                symbol for symbol in symbols if symbol in set(with_value)
            ),
            ratio=len(with_value) / len(symbols),
        )
        for metric, with_value in sorted(by_metric.items())
    )


def _factor_coverage(
    *,
    dataset: NormalizedDataset,
    as_of: datetime,
    symbols: Sequence[str],
    factor_configs: Sequence[FactorConfig],
) -> tuple[tuple[ValuationFactorCoverage, ...], Mapping[str, Mapping[str, DataStatus]]]:
    """因子层覆盖：把每个估值因子在全池跑一遍，记录真实状态。"""
    implemented = {
        config.name: ValuationFactor(config)
        for config in factor_configs
        if config.name in VALUATION_FACTORS
    }
    statuses: dict[str, dict[str, DataStatus]] = {}
    coverage: list[ValuationFactorCoverage] = []
    for name, factor in sorted(implemented.items()):
        per_symbol: dict[str, DataStatus] = {}
        with_value: list[str] = []
        for symbol in symbols:
            result = factor.compute(
                FactorContext(symbol=symbol, as_of=as_of, dataset=dataset)
            )
            per_symbol[symbol] = result.status
            if result.status is DataStatus.VALUE:
                with_value.append(symbol)
        statuses[name] = per_symbol
        coverage.append(
            ValuationFactorCoverage(
                factor=name,
                symbols_with_value=tuple(with_value),
                ratio=len(with_value) / len(symbols),
            )
        )
    return tuple(coverage), statuses


def _strategy_coverage(
    *,
    symbols: Sequence[str],
    strategy_configs: Sequence[StrategyConfig],
    factor_values: Mapping[str, Mapping[str, DataStatus]],
    declared_factors: set[str],
) -> tuple[StrategyValuationCoverage, ...]:
    """策略覆盖：估值侧必需因子的交集，缺一个就不可打分。"""
    reports: list[StrategyValuationCoverage] = []
    for config in strategy_configs:
        valuation_factors = tuple(
            name for name in config.required_factors if name in VALUATION_FACTORS
        )
        non_valuation = tuple(
            name for name in config.required_factors if name not in VALUATION_FACTORS
        )
        missing_config = [
            name
            for name in valuation_factors
            if name not in declared_factors or name not in factor_values
        ]
        if missing_config:
            raise ValueError(
                f"策略 {config.id!r} 需要的估值因子缺少因子配置：{sorted(missing_config)}；"
                "没有配置就没有判定依据，不用'有值'近似替代"
            )
        if not valuation_factors:
            reports.append(
                StrategyValuationCoverage(
                    strategy_id=config.id,
                    valuation_factors=(),
                    non_valuation_factors=non_valuation,
                    scoreable_symbols=(),
                    ratio=0.0,
                    blocking_factors=(),
                )
            )
            continue
        scoreable = tuple(
            symbol
            for symbol in symbols
            if all(
                factor_values[name][symbol] is DataStatus.VALUE
                for name in valuation_factors
            )
        )
        blocking = tuple(
            (
                name,
                sum(
                    1
                    for symbol in symbols
                    if factor_values[name][symbol] is not DataStatus.VALUE
                ),
            )
            for name in valuation_factors
        )
        reports.append(
            StrategyValuationCoverage(
                strategy_id=config.id,
                valuation_factors=valuation_factors,
                non_valuation_factors=non_valuation,
                scoreable_symbols=scoreable,
                ratio=len(scoreable) / len(symbols),
                blocking_factors=blocking,
            )
        )
    return tuple(reports)
