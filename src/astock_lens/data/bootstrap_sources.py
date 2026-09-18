"""启动历史数据的批量优先与单标的补缺契约。"""

from datetime import date, datetime
from typing import Protocol, Self

from pydantic import model_validator

from astock_lens.data.contracts import RawDataset
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord


def validate_bootstrap_as_of(as_of: datetime) -> datetime:
    """验证启动取数的时间点，拒绝无时区时间且不做静默修复。"""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of


def _validate_dataset_payload(dataset: RawDataset) -> RawDataset:
    """验证有效数据集不能用空载荷冒充成功。"""
    if dataset.status is DataStatus.VALUE and (
        dataset.row_count == 0 or dataset.payload is None or not dataset.payload.rows
    ):
        raise ValueError("empty VALUE dataset is not allowed")
    return dataset


def validate_bootstrap_source_dataset(
    dataset: RawDataset, *, as_of: datetime
) -> RawDataset:
    """验证 fallback 返回值；调用方必须在消费 source 返回值时调用。

    `SymbolBarFallbackSource` 是 Protocol，Python 不会在实现者返回值时自动
    执行校验。因此 fallback 的编排边界必须显式调用本函数；它会同时拒绝
    naive `as_of` 与空的 `VALUE` 数据集。
    """
    validate_bootstrap_as_of(as_of)
    return _validate_dataset_payload(dataset)


class BootstrapBatchRequest(DomainRecord):
    """请求批量获取一段时间内的标的行情。"""

    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    as_of: datetime

    @model_validator(mode="after")
    def _require_timezone_aware_as_of(self) -> Self:
        """拒绝没有时区的时间，避免启动数据产生前视歧义。"""
        validate_bootstrap_as_of(self.as_of)
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
            _validate_dataset_payload(dataset)
        return self


def validate_bootstrap_batch_result(
    result: BatchFetchResult, *, as_of: datetime
) -> BatchFetchResult:
    """验证批量结果的消费边界，返回原结果，不改变任何缺失状态。"""
    validate_bootstrap_as_of(as_of)
    for dataset in result.datasets:
        _validate_dataset_payload(dataset)
    return result


class BatchMarketBarSource(Protocol):
    """能够优先按批次获取近期行情的来源。"""

    def fetch_recent_bars(self, request: BootstrapBatchRequest) -> BatchFetchResult: ...


class SymbolBarFallbackSource(Protocol):
    """能够逐标的补取行情的来源。

    Protocol 不能强制实现者在返回时执行运行时校验；消费方必须把返回值
    交给 `validate_bootstrap_source_dataset`，再交给后续编排使用。
    """

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset: ...


class ValidatedSymbolBarFallbackSource:
    """把裸的 fallback 结构接口包成强制校验的消费边界。

    `SymbolBarFallbackSource` 只描述实现者的结构，不能拦截实现者直接返回的
    `RawDataset`。bootstrap 编排必须消费本 adapter，才能在调用 source 前拒绝
    naive `as_of`，并在返回后拒绝空的 `VALUE` 数据集。
    """

    def __init__(self, source: SymbolBarFallbackSource) -> None:
        self._source = source

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        """按原 Protocol 签名取数，并强制执行启动数据校验。"""
        validate_bootstrap_as_of(as_of)
        dataset = self._source.fetch_symbol_bars(
            symbol,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
        )
        return validate_bootstrap_source_dataset(dataset, as_of=as_of)
