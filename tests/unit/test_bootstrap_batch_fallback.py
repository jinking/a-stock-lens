"""启动数据源批量优先与单标的补缺契约测试。

契约之外，本文件还钉住编排接线（Task 8）：批量来源先覆盖能覆盖的部分，逐标的补缺
只对缺口发起请求；没有批量来源时走有界 fallback，安全性质一条不少；两条路径在同一批
合成行情下必须产出完全相同的整份文件。
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    bootstrap_liquidity_history,
)
from astock_lens.data.bootstrap_sources import (
    BatchFetchResult,
    BatchMarketBarSource,
    BootstrapBatchRequest,
    SymbolBarFallbackSource,
    ValidatedSymbolBarFallbackSource,
    validate_bootstrap_batch_result,
    validate_bootstrap_source_dataset,
)
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.sync import read_raw_rows
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
        def fetch_recent_bars(self, request: BootstrapBatchRequest) -> BatchFetchResult:
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


class StaticFallback:
    def __init__(self, dataset: RawDataset) -> None:
        self.dataset = dataset
        self.calls: list[datetime] = []

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        self.calls.append(as_of)
        return self.dataset


def test_validated_fallback_rejects_naive_as_of_before_source_call() -> None:
    source = StaticFallback(_dataset("000001.SZ"))
    fallback = ValidatedSymbolBarFallbackSource(source)

    with pytest.raises(ValueError, match="timezone-aware"):
        fallback.fetch_symbol_bars(
            "000001.SZ",
            as_of=datetime.fromisoformat("2026-09-18T15:00:00"),
            start_date=START_DATE,
            end_date=END_DATE,
        )

    assert source.calls == []


def test_validated_fallback_rejects_empty_value_after_source_call() -> None:
    source = StaticFallback(_dataset("000001.SZ", empty=True))
    fallback = ValidatedSymbolBarFallbackSource(source)

    with pytest.raises(ValueError, match="empty VALUE"):
        fallback.fetch_symbol_bars(
            "000001.SZ",
            as_of=AS_OF,
            start_date=START_DATE,
            end_date=END_DATE,
        )


def test_validated_fallback_allows_value_and_explicit_source_error() -> None:
    for status, empty in ((DataStatus.VALUE, False), (DataStatus.SOURCE_ERROR, True)):
        source = StaticFallback(_dataset("000001.SZ", status=status, empty=empty))
        fallback = ValidatedSymbolBarFallbackSource(source)

        result = fallback.fetch_symbol_bars(
            "000001.SZ",
            as_of=AS_OF,
            start_date=START_DATE,
            end_date=END_DATE,
        )

        assert result.status is status


# ---- 编排接线：批量优先 + 仅缺口补抓（Task 8） --------------------------------

REQUIRED_BARS = 20
# 流动性启动测的是 amount 这根 bar 的根数，所以合成行情必须带 amount 列，
# 否则计数恒为 0，流程会一直判缺。
FLOW_COLUMNS = ("symbol", "trade_date", "close", "amount")


def _flow_rows(symbol: str, *, days: int = 30) -> tuple[tuple[str, ...], ...]:
    return tuple(
        (symbol, (END_DATE - timedelta(days=offset)).isoformat(), "10", "30000000")
        for offset in range(days)
    )


def _value_dataset(symbol: str, rows: tuple[tuple[str, ...], ...]) -> RawDataset:
    return RawDataset(
        provider="fake",
        dataset="daily_bars",
        fetched_at=AS_OF,
        provider_version="test",
        status=DataStatus.VALUE,
        row_count=len(rows),
        payload=RawPayload(columns=FLOW_COLUMNS, rows=rows),
    )


class RecordingFallback:
    """逐标的取数，并记录每一次请求（补缺只该打给缺口）。"""

    def __init__(self, *, failing: frozenset[str] = frozenset()) -> None:
        self.calls: list[str] = []
        self._failing = failing

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        self.calls.append(symbol)
        if symbol in self._failing:
            return RawDataset(
                provider="fake",
                dataset="daily_bars",
                fetched_at=AS_OF,
                provider_version="test",
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
                message=f"{symbol} could not be fetched",
            )
        return _value_dataset(symbol, _flow_rows(symbol))


class RecordingBatchSource:
    """一个批量请求覆盖多个标的；没覆盖到的标的进 missing_symbols。"""

    def __init__(self, *, covering: tuple[str, ...]) -> None:
        self.covering = covering
        self.requests: list[BootstrapBatchRequest] = []

    def fetch_recent_bars(self, request: BootstrapBatchRequest) -> BatchFetchResult:
        self.requests.append(request)
        covered = tuple(
            symbol for symbol in request.symbols if symbol in set(self.covering)
        )
        missing = tuple(
            symbol for symbol in request.symbols if symbol not in set(self.covering)
        )
        # 一个批次里多个标的的行放在同一份 payload 里，和真实批量接口同形状。
        rows = tuple(row for symbol in covered for row in _flow_rows(symbol))
        datasets = (_value_dataset("*", rows),) if rows else ()
        return BatchFetchResult(
            datasets=datasets, missing_symbols=missing, source_name="fake-batch"
        )


def _run_flow(
    root: Path,
    symbols: tuple[str, ...],
    *,
    fallback_source: RecordingFallback,
    batch_source: RecordingBatchSource | None,
    max_inflight: int = 1,
    batch_size: int = 100,
):
    return bootstrap_liquidity_history(
        batch_source=batch_source,
        fallback_source=fallback_source,
        root=root,
        as_of=AS_OF,
        symbols=symbols,
        requirement=BootstrapRequirement(
            factor_name="avg_amount_20d", required_valid_bars=REQUIRED_BARS
        ),
        end_date=END_DATE,
        batch_size=batch_size,
        max_inflight=max_inflight,
    )


def _canonical_symbols(root: Path) -> set[str]:
    columns, rows = read_raw_rows(root / "daily_bars.csv")
    index = columns.index("symbol")
    return {row[index] for row in rows}


def test_full_batch_coverage_makes_the_fallback_answer_nothing(
    local_tmp: Path,
) -> None:
    symbols = tuple(f"{index:06d}.SZ" for index in range(100))
    batch = RecordingBatchSource(covering=symbols)
    fallback = RecordingFallback()

    result = _run_flow(local_tmp, symbols, fallback_source=fallback, batch_source=batch)

    assert batch.requests, "批量来源必须被优先使用"
    assert fallback.calls == [], "批量已经覆盖全部标的时不得再逐标的补抓"
    assert set(result.satisfied_symbols) == set(symbols)
    assert _canonical_symbols(local_tmp) == set(symbols)


def test_partial_batch_coverage_asks_the_fallback_for_exactly_the_gaps(
    local_tmp: Path,
) -> None:
    symbols = tuple(f"{index:06d}.SZ" for index in range(100))
    covered, gaps = symbols[:83], symbols[83:]
    batch = RecordingBatchSource(covering=covered)
    fallback = RecordingFallback()

    result = _run_flow(local_tmp, symbols, fallback_source=fallback, batch_source=batch)

    assert set(fallback.calls) == set(gaps), (
        "补缺只该对批量没覆盖的标的发起请求；实际 "
        f"{sorted(set(fallback.calls) - set(gaps))}"
    )
    assert len(fallback.calls) == len(gaps), "同一只标的不得被补抓两次"
    assert set(result.satisfied_symbols) == set(symbols)
    assert _canonical_symbols(local_tmp) == set(symbols)


def test_no_batch_source_uses_bounded_fallback_without_losing_neighbours(
    local_tmp: Path,
) -> None:
    symbols = ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ")
    fallback = RecordingFallback(failing=frozenset({"000003.SZ"}))

    result = _run_flow(
        local_tmp, symbols, fallback_source=fallback, batch_source=None, max_inflight=2
    )

    assert set(fallback.calls) == set(symbols), "没有批量来源时全部标的走补缺"
    assert result.failed_symbols == ("000003.SZ",)
    assert set(result.satisfied_symbols) == set(symbols) - {"000003.SZ"}
    assert _canonical_symbols(local_tmp) == set(symbols) - {"000003.SZ"}, (
        "一只标的失败不得丢掉它成功的邻居，也不得给它写空行"
    )


def test_a_batch_size_must_be_a_real_batch_size(local_tmp: Path) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        _run_flow(
            local_tmp,
            ("000001.SZ",),
            fallback_source=RecordingFallback(),
            batch_source=None,
            batch_size=0,
        )


def test_batch_plus_fallback_lands_the_same_bytes_as_fallback_only(
    local_tmp: Path,
) -> None:
    """同一批合成行情：一半走批量、一半补缺，与全部走补缺必须逐字节相同。"""
    symbols = tuple(f"{index:06d}.SZ" for index in range(20))
    with_batch_root = local_tmp / "with-batch"
    without_batch_root = local_tmp / "without-batch"
    with_batch_root.mkdir()
    without_batch_root.mkdir()

    _run_flow(
        with_batch_root,
        symbols,
        fallback_source=RecordingFallback(),
        batch_source=RecordingBatchSource(covering=symbols[:10]),
    )
    _run_flow(
        without_batch_root,
        symbols,
        fallback_source=RecordingFallback(),
        batch_source=None,
    )

    assert (with_batch_root / "daily_bars.csv").read_bytes() == (
        without_batch_root / "daily_bars.csv"
    ).read_bytes(), "批量优先不得改变最终落盘内容，只改变请求路径"
