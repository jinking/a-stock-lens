"""冷启动的按标的检查点。

2026-09-18 的失败复盘指出：每完成一块就把整份 `daily_bars.csv` 重写一遍，会让一次运行
在"CPU 满载、文件不断被写、行数一根不涨"的状态里空转。检查点把"成功"先落到**分片 + 清单**，
于是完成一次就记一次，代价与已完成量成正比，而不是与整份文件大小成正比。

三条性质：成功必须跨进程重建后依然可见；续跑只暴露还缺的标的；同一只标的重复成功不得产生
第二份分片或第二条清单记录。

本文件同时钉住**编排接入**（Task 6 Step 5）：`land_bar_chunks` 每块不再重写整份
`daily_bars.csv`，而是逐标的落分片；整份文件在一次落地调用里只合并一次。
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import sleep

from astock_lens.data import bootstrap
from astock_lens.data.bootstrap import BootstrapRequirement, land_bar_chunks
from astock_lens.data.bootstrap_checkpoint import (
    BootstrapCheckpoint,
    BootstrapSymbolState,
)
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.sync import read_raw_rows
from astock_lens.domain.enums import DataStatus

AS_OF = date(2026, 9, 17)
AS_OF_MOMENT = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
START_DATE = date(2026, 9, 1)
END_DATE = date(2026, 9, 17)
BAR_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
)


def _rows(symbol: str, *, days: int = 20) -> tuple[tuple[str, ...], ...]:
    return tuple(
        (
            symbol,
            f"2026-09-{day:02d}",
            "1",
            "1",
            "1",
            "1",
            "1",
            "1000",
            "0.01",
        )
        for day in range(1, days + 1)
    )


def _checkpoint(root: Path) -> BootstrapCheckpoint:
    return BootstrapCheckpoint(root, as_of=AS_OF, required_valid_bars=20)


def test_a_success_survives_recreating_the_checkpoint(local_tmp: Path) -> None:
    checkpoint = _checkpoint(local_tmp)
    checkpoint.record_success("000001.SZ", columns=BAR_COLUMNS, rows=_rows("000001.SZ"))

    reopened = _checkpoint(local_tmp)
    entry = reopened.entry_for("000001.SZ")

    assert entry is not None
    assert entry.status is BootstrapSymbolState.SUCCESS
    assert entry.bars == 20


def test_resume_exposes_only_the_symbols_still_missing(local_tmp: Path) -> None:
    symbols = tuple(f"{index:06d}.SZ" for index in range(100))
    checkpoint = _checkpoint(local_tmp)
    for symbol in symbols[:40]:
        checkpoint.record_success(symbol, columns=BAR_COLUMNS, rows=_rows(symbol))

    reopened = _checkpoint(local_tmp)

    assert len(reopened.pending_symbols(symbols)) == 60
    assert not set(reopened.pending_symbols(symbols)) & set(symbols[:40])


def test_recording_the_same_success_twice_keeps_one_part_and_one_entry(
    local_tmp: Path,
) -> None:
    checkpoint = _checkpoint(local_tmp)
    checkpoint.record_success("000001.SZ", columns=BAR_COLUMNS, rows=_rows("000001.SZ"))
    checkpoint.record_success("000001.SZ", columns=BAR_COLUMNS, rows=_rows("000001.SZ"))

    reopened = _checkpoint(local_tmp)
    parts = sorted(
        (local_tmp / "bootstrap" / AS_OF.isoformat() / "parts").glob("*.csv")
    )

    assert len(parts) == 1, "一个标的只应有一份分片"
    assert len(reopened.manifest().entries) == 1, "一个标的只应有一条清单记录"


def test_a_failure_is_recorded_with_its_reason(local_tmp: Path) -> None:
    checkpoint = _checkpoint(local_tmp)
    checkpoint.record_failure(
        "600519.SH", state=BootstrapSymbolState.TIMEOUT, error="no answer in 60s"
    )

    entry = _checkpoint(local_tmp).entry_for("600519.SH")

    assert entry is not None
    assert entry.status is BootstrapSymbolState.TIMEOUT
    assert entry.last_error == "no answer in 60s"
    assert entry.attempts == 1


class _SymbolFetcher:
    """两只正常、一只失败——真实冷启动的形状（失败不得丢掉成功的邻居）。"""

    table = ("000001.SZ", "600519.SH", "300750.SZ")

    def __init__(self, *, failing: frozenset[str] = frozenset({"600519.SH"})) -> None:
        self.requests: list[str] = []
        self._failing = failing

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        self.requests.append(symbol)
        if symbol in self._failing:
            return RawDataset(
                provider="stub",
                dataset="daily_bars",
                fetched_at=datetime.now(UTC),
                provider_version="test",
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
                message=f"{symbol} could not be fetched",
            )
        rows = _rows(symbol)
        return RawDataset(
            provider="stub",
            dataset="daily_bars",
            fetched_at=datetime.now(UTC),
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=BAR_COLUMNS, rows=rows),
        )


class _HangingFetcher:
    """一只标的永不返回；其余正常。"""

    def __init__(self, *, hanging: str) -> None:
        self.hanging = hanging

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        if symbol == self.hanging:
            sleep(5)
        rows = _rows(symbol)
        return RawDataset(
            provider="hanging",
            dataset="daily_bars",
            fetched_at=datetime.now(UTC),
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=BAR_COLUMNS, rows=rows),
        )


class _BulkFetcher:
    """每只标的都能用第一轮窗口满足要求，于是不会出现扩展轮次。"""

    def __init__(self, *, days: int = 30) -> None:
        self._days = days

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        # 行必须落在 as_of 之前，否则计数会把它们排除、逼出第二轮扩展。
        rows = tuple(
            (
                symbol,
                (end_date - timedelta(days=offset)).isoformat(),
                "1",
                "1",
                "1",
                "1",
                "1",
                "1000",
                "0.01",
            )
            for offset in range(self._days)
        )
        return RawDataset(
            provider="bulk",
            dataset="daily_bars",
            fetched_at=datetime.now(UTC),
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=BAR_COLUMNS, rows=rows),
        )


def test_landing_a_chunk_stages_a_part_per_symbol(local_tmp: Path) -> None:
    """每块落地改成分片：成功的标的一份分片，失败的标的一条清单状态。"""
    checkpoint = _checkpoint(local_tmp)
    provider = _SymbolFetcher()

    result = land_bar_chunks(
        provider=provider,
        root=local_tmp,
        as_of=AS_OF_MOMENT,
        symbols=provider.table,
        start_date=START_DATE,
        end_date=END_DATE,
        chunk_size=2,
        checkpoint=checkpoint,
    )

    assert result.completed_symbols == ("000001.SZ", "300750.SZ")
    assert result.failed_symbols == ("600519.SH",)
    assert {path.stem for path in checkpoint.iter_part_files()} == {
        "000001.SZ",
        "300750.SZ",
    }
    failed = checkpoint.entry_for("600519.SH")
    assert failed is not None
    assert failed.status is BootstrapSymbolState.SOURCE_ERROR
    assert failed.last_error, "失败必须留下原因，不得只剩一个状态"


def test_the_canonical_file_is_merged_once_per_landing_call(
    local_tmp: Path, monkeypatch
) -> None:
    """三块落地只许合并一次整份 `daily_bars.csv`，不得每块重写一遍。"""
    merges: list[Path] = []
    real = bootstrap.write_merged

    def counted(path: Path, payload: RawPayload, **kwargs: object):
        merges.append(path)
        return real(path, payload, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(bootstrap, "write_merged", counted)

    bootstrap.bootstrap_liquidity_history(
        provider=_BulkFetcher(),
        root=local_tmp,
        as_of=AS_OF_MOMENT,
        symbols=tuple(f"{index:06d}.SZ" for index in range(60)),
        requirement=BootstrapRequirement(
            factor_name="avg_amount_20d", required_valid_bars=20
        ),
        end_date=END_DATE,
        chunk_size=20,
    )

    assert len(merges) == 1, (
        "一次落地调用只应把分片合并进整份文件一次；实际 "
        f"{len(merges)} 次（每块一次就是 2026-09-18 空转的根因）"
    )


def test_a_symbol_that_does_not_answer_is_recorded_as_timeout(
    local_tmp: Path,
) -> None:
    """超时必须记成 TIMEOUT，而不是被抹成 0 或混进成功。"""
    checkpoint = _checkpoint(local_tmp)
    provider = _HangingFetcher(hanging="000003.SZ")

    result = land_bar_chunks(
        provider=provider,
        root=local_tmp,
        as_of=AS_OF_MOMENT,
        symbols=("000001.SZ", "000003.SZ"),
        start_date=START_DATE,
        end_date=END_DATE,
        chunk_size=2,
        max_workers=2,
        symbol_timeout_seconds=0.3,
        checkpoint=checkpoint,
    )

    entry = checkpoint.entry_for("000003.SZ")
    assert entry is not None
    assert entry.status is BootstrapSymbolState.TIMEOUT
    assert entry.last_error
    assert result.failed_symbols == ("000003.SZ",)
    answered = checkpoint.entry_for("000001.SZ")
    assert answered is not None
    assert answered.status is BootstrapSymbolState.SUCCESS


def test_a_rerun_does_not_refetch_symbols_whose_part_is_already_staged(
    local_tmp: Path,
) -> None:
    """续跑看的是"清单 + 已落盘分片"，不是从头再来。

    模拟崩溃：分片已落盘、整份文件还没合并（进程在合并前被杀）。第二次运行不得再请求
    这只标的，并且要把已暂存的行补进整份文件。
    """
    first = _SymbolFetcher(failing=frozenset())
    land_bar_chunks(
        provider=first,
        root=local_tmp,
        as_of=AS_OF_MOMENT,
        symbols=("000001.SZ",),
        start_date=START_DATE,
        end_date=END_DATE,
        chunk_size=10,
        checkpoint=_checkpoint(local_tmp),
    )
    (local_tmp / "daily_bars.csv").unlink()

    second = _SymbolFetcher()
    result = land_bar_chunks(
        provider=second,
        root=local_tmp,
        as_of=AS_OF_MOMENT,
        symbols=("000001.SZ",),
        start_date=START_DATE,
        end_date=END_DATE,
        chunk_size=10,
        checkpoint=_checkpoint(local_tmp),
    )

    assert second.requests == [], "已落盘分片覆盖窗口的标的不得被再次请求"
    assert result.completed_symbols == ()
    columns, rows = read_raw_rows(local_tmp / "daily_bars.csv")
    index = columns.index("symbol")
    assert {row[index] for row in rows} == {"000001.SZ"}, (
        "已暂存的行必须被补进整份文件，不得留在分片里成为孤儿数据"
    )
