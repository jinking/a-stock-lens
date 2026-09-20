"""DividendYieldTTMFactor — 除权日口径 TTM 股息率计算器。

依据项目所有者 2026-09-20 批准口径：
- A1: TTM 窗口按除权日 (ex_date) 在 [as_of - 365天, as_of] 之间；
- B1: 严格排除预案，仅聚合已实施 (implementation_status 包含实施) 的现金分红；
- C1: 以 as_of 当日 (或截至 as_of 最新交易日) 收盘价为分母；
- 单位以百分比呈现 (%)。
"""

from datetime import timedelta

from astock_lens.domain.enums import DataStatus, FactorDomain
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import (
    FactorContext,
    FactorInputRef,
    FactorMetadata,
    FactorResult,
)

FACTOR_NAME = "dividend_yield_ttm"


class DividendYieldTTMFactor:
    """根据除权日历史分红事件与日线行情计算 TTM 滚动股息率。"""

    def __init__(self, factor_config: FactorConfig) -> None:
        if factor_config.name != FACTOR_NAME:
            raise ValueError(
                f"DividendYieldTTMFactor requires {FACTOR_NAME!r}, got {factor_config.name!r}"
            )
        self.metadata = FactorMetadata(
            name=factor_config.name,
            domain=FactorDomain[factor_config.domain],
            description=factor_config.description,
            inputs=factor_config.inputs,
            frequency=factor_config.frequency,
            direction=factor_config.direction,
            null_policy=factor_config.null_policy,
            version=factor_config.version,
        )

    def compute(self, context: FactorContext) -> FactorResult:
        """计算该股票在 context.as_of 的 TTM 股息率。"""
        # 1. 检查是否存在该标的的分红历史记录
        has_symbol_events = any(
            e.symbol == context.symbol for e in context.dataset.dividend_events
        )
        if not has_symbol_events:
            return FactorResult(
                symbol=context.symbol,
                factor=self.metadata.name,
                as_of=context.as_of,
                status=DataStatus.NOT_APPLICABLE,
                factor_version=self.metadata.version,
                lineage=SnapshotLineage(factor_version=self.metadata.version),
                unit="%",
            )

        # 2. 检查基准日现价
        usable_bars = [
            b
            for b in context.dataset.daily_bars
            if b.symbol == context.symbol and b.trade_date <= context.as_of.date()
        ]
        if not usable_bars:
            return FactorResult(
                symbol=context.symbol,
                factor=self.metadata.name,
                as_of=context.as_of,
                status=DataStatus.NULL,
                factor_version=self.metadata.version,
                lineage=SnapshotLineage(factor_version=self.metadata.version),
                unit="%",
            )

        latest_bar = max(usable_bars, key=lambda b: b.trade_date)
        if latest_bar.close is None or latest_bar.close <= 0:
            return FactorResult(
                symbol=context.symbol,
                factor=self.metadata.name,
                as_of=context.as_of,
                status=DataStatus.NULL,
                factor_version=self.metadata.version,
                lineage=SnapshotLineage(factor_version=self.metadata.version),
                unit="%",
            )

        close_price = latest_bar.close

        # 3. 过滤 A1 + B1 口径合格分红事件
        window_start = context.as_of.date() - timedelta(days=365)
        window_end = context.as_of.date()

        qualified_events = [
            e
            for e in context.dataset.dividend_events
            if e.symbol == context.symbol
            and e.available_at <= context.as_of
            and e.ex_date is not None
            and window_start <= e.ex_date <= window_end
            and "实施" in e.implementation_status
            and "预案" not in e.implementation_status
            and e.cash_dividend_per_10_shares is not None
            and e.cash_dividend_per_10_shares > 0
        ]

        # 4. 若无符合事件，说明过去一年未实施分红，股息率为 0.0%
        if not qualified_events:
            return FactorResult(
                symbol=context.symbol,
                factor=self.metadata.name,
                as_of=context.as_of,
                status=DataStatus.VALUE,
                raw_value=0.0,
                factor_version=self.metadata.version,
                lineage=SnapshotLineage(factor_version=self.metadata.version),
                unit="%",
            )

        # 5. 累加每股派息并计算股息率 (C1 口径)
        total_dps = sum(
            e.cash_dividend_per_10_shares / 10.0
            for e in qualified_events
            if e.cash_dividend_per_10_shares is not None
        )
        dividend_yield_ttm = (total_dps / close_price) * 100.0

        inputs = tuple(
            FactorInputRef(
                metric="dividend_event",
                report_period=None,
                announce_date=e.announcement_date,
                available_at=e.available_at,
                value=e.cash_dividend_per_10_shares,
            )
            for e in qualified_events
        )

        return FactorResult(
            symbol=context.symbol,
            factor=self.metadata.name,
            as_of=context.as_of,
            status=DataStatus.VALUE,
            raw_value=dividend_yield_ttm,
            factor_version=self.metadata.version,
            lineage=SnapshotLineage(factor_version=self.metadata.version),
            inputs=inputs,
            unit="%",
        )
