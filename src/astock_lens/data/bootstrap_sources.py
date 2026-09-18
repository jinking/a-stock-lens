"""启动历史数据的批量优先与单标的补缺契约。"""

from datetime import date, datetime
from typing import Protocol, Self

from pydantic import model_validator

from astock_lens.data.contracts import RawDataset
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord


class BootstrapBatchRequest(DomainRecord):
    """请求批量获取一段时间内的标的行情。"""

    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    as_of: datetime

    @model_validator(mode="after")
    def _require_timezone_aware_as_of(self) -> Self:
        """拒绝没有时区的时间，避免启动数据产生前视歧义。"""
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return self


class BatchFetchResult(DomainRecord):
    """批量行情结果，明确记录已返回数据与未覆盖标的。"""

    datasets: tuple[RawDataset, ...]
    missing_symbols: tuple[str, ...]
    source_name: str

    @model_validator(mode="after")
    def _reject_empty_value_datasets(self) -> Self:
        """空结果必须带缺失状态，不能伪装成有效数据。"""
        for dataset in self.datasets:
            if dataset.status is not DataStatus.VALUE:
                continue
            if dataset.row_count == 0 or dataset.payload is None or not dataset.payload.rows:
                raise ValueError("empty VALUE dataset is not allowed")
        return self


class BatchMarketBarSource(Protocol):
    """能够优先按批次获取近期行情的来源。"""

    def fetch_recent_bars(
        self, request: BootstrapBatchRequest
    ) -> BatchFetchResult: ...


class SymbolBarFallbackSource(Protocol):
    """能够逐标的补取行情的来源。"""

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset: ...
