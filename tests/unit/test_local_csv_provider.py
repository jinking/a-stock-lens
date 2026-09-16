"""Provider-layer tests.

The rule these tests pin down: a *data* problem is reported through
`RawDataset.status`, while a *caller* problem raises. Data problems must stay
visible in Data Health instead of crashing a scan.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.domain.enums import DataStatus

CSV_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _request(dataset: str = "daily_bars", **overrides: object) -> FetchRequest:
    return FetchRequest(dataset=dataset, as_of=AS_OF, **overrides)  # type: ignore[arg-type]


def test_fetch_returns_verbatim_rows() -> None:
    dataset = LocalCsvProvider(CSV_ROOT).fetch(_request())

    assert dataset.status is DataStatus.VALUE
    assert dataset.provider == "local-csv"
    assert dataset.dataset == "daily_bars"
    assert dataset.row_count == 85
    assert dataset.payload is not None
    assert dataset.payload.columns[0] == "symbol"
    assert "amount" in dataset.payload.columns
    assert len(dataset.payload.rows) == 85


def test_payload_keeps_every_cell_as_a_string() -> None:
    """Raw stays raw: no type inference happens in the provider."""
    dataset = LocalCsvProvider(CSV_ROOT).fetch(_request())

    assert dataset.payload is not None
    assert all(isinstance(cell, str) for row in dataset.payload.rows for cell in row)


def test_fetched_at_is_timezone_aware() -> None:
    dataset = LocalCsvProvider(CSV_ROOT).fetch(_request())

    assert dataset.fetched_at.tzinfo is not None


def test_missing_file_reports_source_error_instead_of_raising() -> None:
    dataset = LocalCsvProvider(CSV_ROOT).fetch(_request(dataset="does_not_exist"))

    assert dataset.status is DataStatus.SOURCE_ERROR
    assert dataset.row_count == 0
    assert dataset.payload is None


def test_empty_cells_survive_as_empty_strings_not_zeroes() -> None:
    dataset = LocalCsvProvider(CSV_ROOT).fetch(_request())

    assert dataset.payload is not None
    amount_index = dataset.payload.columns.index("amount")
    blanks = [row for row in dataset.payload.rows if row[amount_index] == ""]

    assert len(blanks) == 2
    assert "0" not in {row[amount_index] for row in dataset.payload.rows}


def test_symbol_filter_keeps_requested_symbols_only() -> None:
    dataset = LocalCsvProvider(CSV_ROOT).fetch(_request(symbols=("000001.SZ",)))

    assert dataset.payload is not None
    symbol_index = dataset.payload.columns.index("symbol")
    assert dataset.row_count == 10
    assert {row[symbol_index] for row in dataset.payload.rows} == {"000001.SZ"}


def test_date_range_filter_narrows_rows() -> None:
    dataset = LocalCsvProvider(CSV_ROOT).fetch(
        _request(
            symbols=("600000.SH",),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 4),
        )
    )

    assert dataset.row_count == 4


def test_filtering_on_a_missing_column_is_a_caller_error(local_tmp: Path) -> None:
    """A request the file cannot satisfy is a programming error, not data health."""
    (local_tmp / "no_keys.csv").write_text("code,value\n600000,1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="symbol"):
        LocalCsvProvider(local_tmp).fetch(
            FetchRequest(dataset="no_keys", as_of=AS_OF, symbols=("600000.SH",))
        )


def test_health_reports_absent_root(local_tmp: Path) -> None:
    health = LocalCsvProvider(local_tmp / "absent").health()

    assert health.healthy is False
    assert health.status is DataStatus.SOURCE_ERROR
    assert health.message


def test_health_reports_present_root() -> None:
    health = LocalCsvProvider(CSV_ROOT).health()

    assert health.healthy is True
    assert health.status is DataStatus.VALUE
    assert health.checked_at.tzinfo is not None
