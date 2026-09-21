"""Tests for canonical benchmark-bar reader (Task 3)."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.benchmark import (
    BENCHMARK_BARS_ENV,
    DEFAULT_BENCHMARK_BARS_PATH,
    read_benchmark_bars,
)
from astock_lens.domain.models import DailyBar

BENCHMARK_ID = "000985.CSI"
AS_OF = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

HEADER = "symbol,trade_date,open,high,low,close,volume,amount\n"


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_constants_contract() -> None:
    """Validate environment variable name and default file path."""
    assert BENCHMARK_BARS_ENV == "ASTOCK_BENCHMARK_BARS_PATH"
    assert DEFAULT_BENCHMARK_BARS_PATH == Path("data/raw/benchmark_bars.csv")


def test_step1_future_row_exclusion(tmp_path: Path) -> None:
    """Step 1: rows with trade_date > as_of.date() must be excluded."""
    csv_file = _write_csv(
        tmp_path / "benchmark_bars.csv",
        HEADER
        + f"{BENCHMARK_ID},2026-09-01,10.0,11.0,9.0,10.5,1000.0,5000.0\n"
        + f"{BENCHMARK_ID},2026-09-02,10.5,11.5,9.5,11.0,1200.0,6000.0\n"
        + f"{BENCHMARK_ID},2026-09-03,11.0,12.0,10.0,11.5,1500.0,7000.0\n"
        + f"{BENCHMARK_ID},2026-09-04,11.5,12.5,10.5,12.0,1600.0,8000.0\n",
    )

    bars = read_benchmark_bars(
        path=csv_file,
        benchmark_id=BENCHMARK_ID,
        as_of=AS_OF,  # 2026-09-02
    )

    assert len(bars) == 2
    assert [b.trade_date for b in bars] == [date(2026, 9, 1), date(2026, 9, 2)]


def test_step2_wrong_symbol_exclusion(tmp_path: Path) -> None:
    """Step 2: rows with symbol != benchmark_id must be excluded."""
    csv_file = _write_csv(
        tmp_path / "benchmark_bars.csv",
        HEADER
        + f"{BENCHMARK_ID},2026-09-01,10.0,11.0,9.0,10.5,1000.0,5000.0\n"
        + "000300.SH,2026-09-01,20.0,21.0,19.0,20.5,2000.0,9000.0\n"
        + "399006.SZ,2026-09-01,30.0,31.0,29.0,30.5,3000.0,12000.0\n"
        + f"{BENCHMARK_ID},2026-09-02,10.5,11.5,9.5,11.0,1200.0,6000.0\n",
    )

    bars = read_benchmark_bars(
        path=csv_file,
        benchmark_id=BENCHMARK_ID,
        as_of=AS_OF,
    )

    assert len(bars) == 2
    assert all(b.symbol == BENCHMARK_ID for b in bars)
    assert [b.trade_date for b in bars] == [date(2026, 9, 1), date(2026, 9, 2)]


def test_step3_missing_required_column_in_header(tmp_path: Path) -> None:
    """Step 3: missing required column in CSV header fails closed with ValueError."""
    # Header missing 'amount'
    csv_file = _write_csv(
        tmp_path / "benchmark_bars.csv",
        "symbol,trade_date,open,high,low,close,volume\n"
        + f"{BENCHMARK_ID},2026-09-01,10.0,11.0,9.0,10.5,1000.0\n",
    )

    with pytest.raises(ValueError, match="missing required columns"):
        read_benchmark_bars(
            path=csv_file,
            benchmark_id=BENCHMARK_ID,
            as_of=AS_OF,
        )


def test_step3_malformed_numeric_column(tmp_path: Path) -> None:
    """Step 3: non-numeric float in column fails closed with ValueError."""
    csv_file = _write_csv(
        tmp_path / "benchmark_bars.csv",
        HEADER
        + f"{BENCHMARK_ID},2026-09-01,10.0,11.0,9.0,not-a-number,1000.0,5000.0\n",
    )

    with pytest.raises(ValueError, match="Malformed numeric column 'close'"):
        read_benchmark_bars(
            path=csv_file,
            benchmark_id=BENCHMARK_ID,
            as_of=AS_OF,
        )


def test_step3_malformed_trade_date(tmp_path: Path) -> None:
    """Step 3: invalid date string fails closed with ValueError."""
    csv_file = _write_csv(
        tmp_path / "benchmark_bars.csv",
        HEADER + f"{BENCHMARK_ID},not-a-date,10.0,11.0,9.0,10.5,1000.0,5000.0\n",
    )

    with pytest.raises(ValueError, match="Malformed trade_date"):
        read_benchmark_bars(
            path=csv_file,
            benchmark_id=BENCHMARK_ID,
            as_of=AS_OF,
        )


def test_step3_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    """Step 3: non-existent file path fails closed with FileNotFoundError."""
    non_existent = tmp_path / "non_existent.csv"
    with pytest.raises(FileNotFoundError):
        read_benchmark_bars(
            path=non_existent,
            benchmark_id=BENCHMARK_ID,
            as_of=AS_OF,
        )


def test_step3_naive_as_of_rejected(tmp_path: Path) -> None:
    """Step 3: naive datetime without timezone must be rejected."""
    csv_file = _write_csv(
        tmp_path / "benchmark_bars.csv",
        HEADER + f"{BENCHMARK_ID},2026-09-01,10.0,11.0,9.0,10.5,1000.0,5000.0\n",
    )

    naive_as_of = datetime(2026, 9, 2, 15, 0)  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware"):
        read_benchmark_bars(
            path=csv_file,
            benchmark_id=BENCHMARK_ID,
            as_of=naive_as_of,
        )


def test_bars_sorted_ascending(tmp_path: Path) -> None:
    """Bars must be returned in ascending order by trade_date regardless of CSV order."""
    csv_file = _write_csv(
        tmp_path / "benchmark_bars.csv",
        HEADER
        + f"{BENCHMARK_ID},2026-09-02,10.5,11.5,9.5,11.0,1200.0,6000.0\n"
        + f"{BENCHMARK_ID},2026-09-01,10.0,11.0,9.0,10.5,1000.0,5000.0\n",
    )

    bars = read_benchmark_bars(
        path=csv_file,
        benchmark_id=BENCHMARK_ID,
        as_of=AS_OF,
    )

    assert len(bars) == 2
    assert bars[0].trade_date == date(2026, 9, 1)
    assert bars[1].trade_date == date(2026, 9, 2)
    assert bars[0].close == 10.5
    assert bars[0].amount == 5000.0
    assert bars[0].volume == 1000.0
    assert isinstance(bars[0], DailyBar)


def test_resolve_benchmark_bars_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate path resolution with and without environment variable."""
    from astock_lens.data.benchmark import resolve_benchmark_bars_path

    monkeypatch.delenv(BENCHMARK_BARS_ENV, raising=False)
    assert resolve_benchmark_bars_path() == DEFAULT_BENCHMARK_BARS_PATH

    custom_path = "/tmp/custom_benchmark.csv"
    monkeypatch.setenv(BENCHMARK_BARS_ENV, custom_path)
    assert resolve_benchmark_bars_path() == Path(custom_path)


def test_empty_csv_raises_value_error(tmp_path: Path) -> None:
    """Empty CSV file fails closed with ValueError."""
    empty_file = _write_csv(tmp_path / "empty.csv", "")
    with pytest.raises(ValueError, match="empty"):
        read_benchmark_bars(
            path=empty_file,
            benchmark_id=BENCHMARK_ID,
            as_of=AS_OF,
        )


def test_mismatched_row_field_count_raises_value_error(tmp_path: Path) -> None:
    """Row with fewer or more fields than header fails closed with ValueError."""
    mismatched = _write_csv(
        tmp_path / "mismatched.csv",
        HEADER + f"{BENCHMARK_ID},2026-09-01,10.0,11.0\n",
    )
    with pytest.raises(ValueError, match="unexpected field count"):
        read_benchmark_bars(
            path=mismatched,
            benchmark_id=BENCHMARK_ID,
            as_of=AS_OF,
        )


def test_empty_symbol_raises_value_error(tmp_path: Path) -> None:
    """Row with empty symbol string fails closed with ValueError."""
    empty_sym = _write_csv(
        tmp_path / "empty_symbol.csv",
        HEADER + "  ,2026-09-01,10.0,11.0,9.0,10.5,1000.0,5000.0\n",
    )
    with pytest.raises(ValueError, match="Empty symbol"):
        read_benchmark_bars(
            path=empty_sym,
            benchmark_id=BENCHMARK_ID,
            as_of=AS_OF,
        )


def test_non_finite_numeric_column_raises_value_error(tmp_path: Path) -> None:
    """Row with non-finite float (inf/nan) fails closed with ValueError."""
    non_finite = _write_csv(
        tmp_path / "non_finite.csv",
        HEADER + f"{BENCHMARK_ID},2026-09-01,10.0,11.0,9.0,inf,1000.0,5000.0\n",
    )
    with pytest.raises(ValueError, match="Non-finite numeric column"):
        read_benchmark_bars(
            path=non_finite,
            benchmark_id=BENCHMARK_ID,
            as_of=AS_OF,
        )


def test_blank_numeric_cells_parsed_as_none(tmp_path: Path) -> None:
    """Blank numeric cells become None without errors."""
    blank_cell = _write_csv(
        tmp_path / "blank.csv",
        HEADER + f"{BENCHMARK_ID},2026-09-01,,11.0,9.0,10.5,1000.0,\n",
    )
    bars = read_benchmark_bars(
        path=blank_cell,
        benchmark_id=BENCHMARK_ID,
        as_of=AS_OF,
    )
    assert len(bars) == 1
    assert bars[0].open is None
    assert bars[0].amount is None
    assert bars[0].close == 10.5
