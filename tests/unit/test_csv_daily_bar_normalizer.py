"""Normalizer tests.

The rule these tests pin down: a value that cannot be read stays `None`, and
the reason it stayed `None` survives as a `ParseFailure`. Nothing is repaired
into a plausible number, and `float("nan")` never leaks out of a text cell.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest, NormalizedDataset
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.domain.models import DailyBar

CSV_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _normalize(dataset: str = "dirty_bars") -> NormalizedDataset:
    raw = LocalCsvProvider(CSV_ROOT).fetch(FetchRequest(dataset=dataset, as_of=AS_OF))
    return CsvDailyBarNormalizer().normalize(raw, as_of=AS_OF)


def _bar(normalized: NormalizedDataset, symbol: str, trade_date: date) -> DailyBar:
    return next(
        bar
        for bar in normalized.daily_bars
        if bar.symbol == symbol and bar.trade_date == trade_date
    )


def test_clean_row_becomes_a_canonical_bar() -> None:
    normalized = _normalize()

    bar = _bar(normalized, "600000.SH", date(2026, 9, 4))

    assert bar.close == 10.00
    assert bar.amount == 1014000.0
    assert bar.volume == 1000000.0


def test_blank_cell_stays_none_without_a_parse_failure() -> None:
    normalized = _normalize()

    bar = _bar(normalized, "600000.SH", date(2026, 9, 3))

    assert bar.amount is None
    assert not any(failure.column == "amount" for failure in normalized.parse_failures)


def test_corrupt_number_stays_none_and_is_reported() -> None:
    normalized = _normalize()

    bar = _bar(normalized, "600000.SH", date(2026, 9, 2))

    assert bar.close is None
    reported = [
        failure for failure in normalized.parse_failures if failure.column == "close"
    ]
    assert len(reported) == 1
    assert reported[0].raw_value == "abc"


def test_negative_close_is_normalized_verbatim() -> None:
    """The gate decides validity; the normalizer must not pre-empt it."""
    normalized = _normalize()

    bar = _bar(normalized, "600000.SH", date(2026, 9, 1))

    assert bar.close == -1.00


def test_row_with_unreadable_trade_date_is_rejected() -> None:
    normalized = _normalize()

    assert all(bar.symbol != "000001.SZ" for bar in normalized.daily_bars)
    reasons = [failure.reason for failure in normalized.parse_failures]
    assert any("trade_date" in reason for reason in reasons)


def test_row_with_empty_symbol_is_rejected() -> None:
    normalized = _normalize()

    assert all(bar.symbol for bar in normalized.daily_bars)
    reasons = [failure.reason for failure in normalized.parse_failures]
    assert any("symbol" in reason for reason in reasons)


def test_payload_less_dataset_normalizes_to_nothing() -> None:
    raw = LocalCsvProvider(CSV_ROOT).fetch(
        FetchRequest(dataset="does_not_exist", as_of=AS_OF)
    )

    normalized = CsvDailyBarNormalizer().normalize(raw, as_of=AS_OF)

    assert normalized.daily_bars == ()
    assert normalized.parse_failures == ()


def test_naive_as_of_is_rejected() -> None:
    raw = LocalCsvProvider(CSV_ROOT).fetch(
        FetchRequest(dataset="dirty_bars", as_of=AS_OF)
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        CsvDailyBarNormalizer().normalize(
            raw,
            as_of=datetime(2026, 9, 4, 15, 0),  # noqa: DTZ001
        )


def test_nan_spelling_never_becomes_a_float() -> None:
    """ "nan" parses as a float; it must be treated as absent instead."""
    normalized = _normalize()

    assert all(
        bar.amount is None or bar.amount == bar.amount for bar in normalized.daily_bars
    )
    assert not any(
        bar.close is not None and bar.close != bar.close
        for bar in normalized.daily_bars
    )


def test_column_map_renames_source_columns(local_tmp: Path) -> None:
    (local_tmp / "renamed.csv").write_text(
        "code,dt,px,vol,amt\n600000.SH,2026-09-04,10.0,1000,50000\n",
        encoding="utf-8",
    )
    raw = LocalCsvProvider(local_tmp).fetch(
        FetchRequest(dataset="renamed", as_of=AS_OF)
    )

    normalized = CsvDailyBarNormalizer(
        column_map={
            "code": "symbol",
            "dt": "trade_date",
            "px": "close",
            "vol": "volume",
            "amt": "amount",
        }
    ).normalize(raw, as_of=AS_OF)

    assert len(normalized.daily_bars) == 1
    bar = normalized.daily_bars[0]
    assert bar.symbol == "600000.SH"
    assert bar.trade_date == date(2026, 9, 4)
    assert bar.close == 10.0
    assert bar.high is None
