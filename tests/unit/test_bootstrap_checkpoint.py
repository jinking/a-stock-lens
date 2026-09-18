"""冷启动的按标的检查点。

2026-09-18 的失败复盘指出：每完成一块就把整份 `daily_bars.csv` 重写一遍，会让一次运行
在"CPU 满载、文件不断被写、行数一根不涨"的状态里空转。检查点把"成功"先落到**分片 + 清单**，
于是完成一次就记一次，代价与已完成量成正比，而不是与整份文件大小成正比。

三条性质：成功必须跨进程重建后依然可见；续跑只暴露还缺的标的；同一只标的重复成功不得产生
第二份分片或第二条清单记录。
"""

from datetime import UTC, date, datetime
from pathlib import Path

from astock_lens.data.bootstrap_checkpoint import (
    BootstrapCheckpoint,
    BootstrapSymbolState,
)

AS_OF = date(2026, 9, 17)
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
