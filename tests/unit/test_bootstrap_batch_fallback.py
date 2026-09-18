"""启动数据源批量优先与单标的补缺契约测试。"""

from datetime import UTC, date, datetime

import pytest

from astock_lens.data.bootstrap_sources import (
    BatchFetchResult,
    BatchMarketBarSource,
    BootstrapBatchRequest,
    SymbolBarFallbackSource,
    validate_bootstrap_batch_result,
    validate_bootstrap_source_dataset,
)
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.domain.enums import DataStatus

AS_OF = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)
START_DATE = date(2026, 8, 1)
END_DATE = date(2026, 9, 18)
BAR_COLUMNS = ("symbol", "trade_date", "close")


def _dataset(
    symbol: str,
    *,
    status: DataStatus = DataStatus.VALUE,
    empty: bool = False,
) -> RawDataset:
    rows = () if empty else ((symbol, END_DATE.isoformat(), "10"),)
    return RawDataset(
        provider="test",
        dataset="daily_bars",
        fetched_at=AS_OF,
        provider_version="test",
        status=status,
        row_count=len(rows),
        payload=RawPayload(columns=BAR_COLUMNS, rows=rows) if rows else None,
    )


def test_batch_result_keeps_partial_coverage_and_explicit_missing_symbols() -> None:
    result = BatchFetchResult(
        datasets=(_dataset("000001.SZ"),),
        missing_symbols=("000002.SZ",),
        source_name="batch-test",
    )

    assert result.datasets[0].status is DataStatus.VALUE
    assert result.missing_symbols == ("000002.SZ",)


def test_fallback_contract_is_invoked_one_symbol_at_a_time() -> None:
    class RecordingFallback:
        calls: list[tuple[str, datetime, date, date]]

        def __init__(self) -> None:
            self.calls = []

        def fetch_symbol_bars(
            self,
            symbol: str,
            *,
            as_of: datetime,
            start_date: date,
            end_date: date,
        ) -> RawDataset:
            self.calls.append((symbol, as_of, start_date, end_date))
            return _dataset(symbol)

    recorder = RecordingFallback()
    fallback: SymbolBarFallbackSource = recorder
    fallback.fetch_symbol_bars(
        "000001.SZ", as_of=AS_OF, start_date=START_DATE, end_date=END_DATE
    )
    fallback.fetch_symbol_bars(
        "000002.SZ", as_of=AS_OF, start_date=START_DATE, end_date=END_DATE
    )

    assert recorder.calls == [
        ("000001.SZ", AS_OF, START_DATE, END_DATE),
        ("000002.SZ", AS_OF, START_DATE, END_DATE),
    ]


def test_batch_source_contract_returns_a_batch_result() -> None:
    class RecordingBatchSource:
        def fetch_recent_bars(
            self, request: BootstrapBatchRequest
        ) -> BatchFetchResult:
            return BatchFetchResult(
                datasets=tuple(_dataset(symbol) for symbol in request.symbols[:1]),
                missing_symbols=request.symbols[1:],
                source_name="batch-test",
            )

    request = BootstrapBatchRequest(
        symbols=("000001.SZ", "000002.SZ"),
        start_date=START_DATE,
        end_date=END_DATE,
        as_of=AS_OF,
    )
    source: BatchMarketBarSource = RecordingBatchSource()

    result = source.fetch_recent_bars(request)

    assert len(result.datasets) == 1
    assert result.missing_symbols == ("000002.SZ",)


def test_bootstrap_batch_request_rejects_naive_as_of() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        BootstrapBatchRequest(
            symbols=("000001.SZ",),
            start_date=START_DATE,
            end_date=END_DATE,
            as_of=datetime.fromisoformat("2026-09-18T15:00:00"),
        )


def test_batch_result_rejects_empty_value_dataset() -> None:
    with pytest.raises(ValueError, match="empty VALUE"):
        BatchFetchResult(
            datasets=(_dataset("000001.SZ", status=DataStatus.VALUE, empty=True),),
            missing_symbols=(),
            source_name="batch-test",
        )


def test_fallback_validation_rejects_naive_as_of() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_bootstrap_source_dataset(
            _dataset("000001.SZ"),
            as_of=datetime.fromisoformat("2026-09-18T15:00:00"),
        )


def test_fallback_validation_rejects_empty_value_dataset() -> None:
    with pytest.raises(ValueError, match="empty VALUE"):
        validate_bootstrap_source_dataset(
            _dataset("000001.SZ", empty=True),
            as_of=AS_OF,
        )


def test_batch_validation_rejects_naive_as_of() -> None:
    result = BatchFetchResult(
        datasets=(_dataset("000001.SZ"),),
        missing_symbols=(),
        source_name="batch-test",
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        validate_bootstrap_batch_result(
            result,
            as_of=datetime.fromisoformat("2026-09-18T15:00:00"),
        )
