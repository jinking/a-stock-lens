"""估值因子。

它们读 `ValuationObservation`（neodata 的估值事实），并且和基本面因子一样受时点约束：
只能用 `available_at <= as_of` 的最新观测。与基本面因子的两处差异都是刻意的：

- **时点是交易日，不是报告期**，所以没有"最近一次带值的报告期"那层语义——
  估值每天都在更新，缺就是缺；
- **缺失判定更简单**：该标的从未有过这个指标 → `NOT_APPLICABLE`（例如 B 股没有估值数据）；
  有观测但都晚于 `as_of` → `NULL`；有观测但值为空 → `NULL`；超过已评审的新鲜度 →
  `STALE`（机制就绪，`stale_after_days` 为 `null` 时不触发）。

极性仍由策略权重的符号表达：`pe_ttm`、`pb`、`pe_percentile`、`peg` 越低越便宜，
`dividend_yield_ttm` 越高回报越多，`pcf_operating_ttm` 是市现率（越低越便宜）。
"""

from collections.abc import Mapping
from dataclasses import dataclass

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage, ValuationObservation
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import (
    FactorContext,
    FactorInputRef,
    FactorMetadata,
    FactorResult,
)
from astock_lens.factors.fundamental import STALE_AFTER_DAYS


@dataclass(frozen=True)
class ValuationMetricSpec:
    """一个估值因子对应的规范指标与单位。"""

    metric: str
    unit: str


# 代码拥有"哪个指标"；YAML 拥有元数据与新鲜度阈值。
VALUATION_FACTORS: Mapping[str, ValuationMetricSpec] = {
    "pe_ttm": ValuationMetricSpec("pe_ttm", "x"),
    "pb": ValuationMetricSpec("pb", "x"),
    "ps_ttm": ValuationMetricSpec("ps_ttm", "x"),
    "pe_percentile": ValuationMetricSpec("pe_percentile", "%"),
    "dividend_yield_ttm": ValuationMetricSpec("dividend_yield_ttm", "%"),
    "pcf_operating_ttm": ValuationMetricSpec("pcf_operating_ttm", "x"),
    "peg": ValuationMetricSpec("peg", "x"),
}


class ValuationFactor:
    """把一条估值事实按给定时点取出来。"""

    def __init__(self, factor_config: FactorConfig) -> None:
        spec = VALUATION_FACTORS.get(factor_config.name)
        if spec is None:
            raise ValueError(
                f"{factor_config.name!r} 不是估值因子；已实现的估值因子为 "
                f"{sorted(VALUATION_FACTORS)}"
            )
        if set(factor_config.inputs) != {spec.metric}:
            raise ValueError(
                f"因子配置 {factor_config.name!r} 的 inputs 必须恰好是 "
                f"[{spec.metric!r}]，收到 {sorted(factor_config.inputs)}"
            )
        self._spec = spec
        self._stale_after_days = _configured_staleness(factor_config)
        self.metadata = _metadata(factor_config)

    def compute(self, context: FactorContext) -> FactorResult:
        """取最新可用观测；取不到时如实报告是哪种缺失。"""
        mine = [
            item
            for item in context.dataset.valuations
            if item.symbol == context.symbol and item.metric == self._spec.metric
        ]
        available = [item for item in mine if item.available_at <= context.as_of]

        status = _blocking_status(mine, available, self._stale_after_days, context)
        latest = _latest(available)
        inputs = (
            FactorInputRef(
                metric=self._spec.metric,
                report_period=latest.valuation_date if latest else None,
                announce_date=latest.valuation_date if latest else None,
                value=latest.value if latest else None,
            ),
        )
        if status is not None:
            return _result(
                context,
                self.metadata,
                status=status,
                inputs=inputs,
                unit=self._spec.unit,
            )
        return _result(
            context,
            self.metadata,
            status=DataStatus.VALUE,
            inputs=inputs,
            unit=self._spec.unit,
            value=latest.value if latest else None,
        )


def _latest(available: list[ValuationObservation]) -> ValuationObservation | None:
    """最新一个"带值"的观测，与基本面因子同一语义。"""
    valued = [item for item in available if item.value is not None]
    pool = valued or available
    if not pool:
        return None
    return max(pool, key=lambda item: (item.valuation_date, item.available_at))


def _blocking_status(
    mine: list[ValuationObservation],
    available: list[ValuationObservation],
    stale_after_days: int | None,
    context: FactorContext,
) -> DataStatus | None:
    """返回阻止取值的状态，或 `None` 表示可以计算。"""
    if not mine:
        return DataStatus.NOT_APPLICABLE
    if not available:
        return DataStatus.NULL

    latest = _latest(available)
    if latest is None or latest.value is None:
        return DataStatus.NULL

    if stale_after_days is not None:
        age = (context.as_of.date() - latest.valuation_date).days
        if age > stale_after_days:
            return DataStatus.STALE
    return None


def _configured_staleness(factor_config: FactorConfig) -> int | None:
    """新鲜度阈值：配置必须显式声明；写 `null` 表示尚未评审。"""
    if STALE_AFTER_DAYS not in factor_config.params:
        raise ValueError(
            f"因子配置 {factor_config.name!r} 必须声明 "
            f"params.{STALE_AFTER_DAYS}；写 null 表示尚无已评审的新鲜度要求"
        )
    configured = factor_config.params[STALE_AFTER_DAYS]
    if configured is None:
        return None
    if configured <= 0:
        raise ValueError(
            f"params.{STALE_AFTER_DAYS} 设置时必须为正，收到 {configured}"
        )
    return configured


def _metadata(factor_config: FactorConfig) -> FactorMetadata:
    """照抄配置里的元数据，因子不自己发明。"""
    return FactorMetadata(
        name=factor_config.name,
        domain=factor_config.domain,
        description=factor_config.description,
        inputs=factor_config.inputs,
        frequency=factor_config.frequency,
        direction=factor_config.direction,
        null_policy=factor_config.null_policy,
        version=factor_config.version,
    )


def _result(
    context: FactorContext,
    metadata: FactorMetadata,
    *,
    status: DataStatus,
    inputs: tuple[FactorInputRef, ...],
    unit: str,
    value: float | None = None,
) -> FactorResult:
    """非 `VALUE` 状态一律不携带数字。"""
    return FactorResult(
        symbol=context.symbol,
        factor=metadata.name,
        as_of=context.as_of,
        status=status,
        factor_version=metadata.version,
        lineage=SnapshotLineage(factor_version=metadata.version),
        raw_value=value if status is DataStatus.VALUE else None,
        inputs=inputs,
        unit=unit,
    )
