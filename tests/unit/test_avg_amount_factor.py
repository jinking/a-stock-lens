"""First factor tests.

The rule these tests pin down: an incomplete window produces `NULL`, never a
number computed from fewer days than the window declares. Averaging a shorter
stretch would silently answer a different question.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.domain.enums import DataStatus
from astock_lens.factors.builtin import AverageAmountFactor
from astock_lens.factors.config import load_factor_config
from astock_lens.factors.contracts import FactorContext

CSV_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "factors" / "avg_amount_20d.yaml"
)
FULL_WINDOW_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _factor() -> AverageAmountFactor:
    return AverageAmountFactor(load_factor_config(CONFIG_PATH))


def _context(symbol: str, as_of: datetime = FULL_WINDOW_AS_OF) -> FactorContext:
    raw = LocalCsvProvider(CSV_ROOT).fetch(
        FetchRequest(dataset="daily_bars", as_of=as_of)
    )
    return FactorContext(
        symbol=symbol,
        as_of=as_of,
        dataset=CsvDailyBarNormalizer().normalize(raw, as_of=as_of),
    )


def test_metadata_comes_from_the_config_file() -> None:
    metadata = _factor().metadata

    assert metadata.name == "avg_amount_20d"
    assert metadata.version == "v1"
    assert metadata.inputs == ("amount",)


def test_full_window_averages_exactly() -> None:
    result = _factor().compute(_context("600000.SH"))

    assert result.status is DataStatus.VALUE
    assert result.raw_value == pytest.approx(1_014_500.0)


def test_short_window_is_null_not_a_smaller_average() -> None:
    """000001.SZ only has 10 bars, so no 20-day average exists."""
    result = _factor().compute(_context("000001.SZ"))

    assert result.status is DataStatus.NULL
    assert result.raw_value is None


def test_missing_amount_inside_the_window_forces_null() -> None:
    """601398.SH has a blank amount on one of its trailing 20 bars."""
    result = _factor().compute(_context("601398.SH"))

    assert result.status is DataStatus.NULL
    assert result.raw_value is None


def test_missing_amount_outside_the_window_is_harmless() -> None:
    """600519.SH has a blank amount only on its oldest bar."""
    result = _factor().compute(_context("600519.SH"))

    assert result.status is DataStatus.VALUE
    assert result.raw_value == pytest.approx(3_014_500.0)


def test_bars_after_as_of_are_excluded() -> None:
    earlier = datetime(2026, 8, 28, 15, 0, tzinfo=UTC)

    result = _factor().compute(_context("600000.SH", earlier))

    assert result.status is DataStatus.VALUE
    assert result.raw_value == pytest.approx(1_009_500.0)
    assert result.as_of == earlier


def test_result_carries_its_version_and_lineage() -> None:
    result = _factor().compute(_context("600000.SH"))

    assert result.factor == "avg_amount_20d"
    assert result.factor_version == "v1"
    assert result.lineage.factor_version == "v1"


def test_config_without_a_window_is_rejected(local_tmp: Path) -> None:
    path = local_tmp / "no_window.yaml"
    path.write_text(
        "name: avg_amount_20d\n"
        "domain: MARKET_MOMENTUM\n"
        "description: missing its window\n"
        "inputs: [amount]\n"
        "frequency: DAILY\n"
        "direction: HIGHER_MEANS_MORE_LIQUID\n"
        "null_policy: NULL_UNLESS_THE_WHOLE_WINDOW_IS_PRESENT\n"
        "version: v1\n"
        "params: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="window"):
        AverageAmountFactor(load_factor_config(path))


def test_config_for_another_factor_is_rejected() -> None:
    config = load_factor_config(CONFIG_PATH).model_copy(
        update={"name": "something_else"}
    )

    with pytest.raises(ValueError, match="avg_amount_20d"):
        AverageAmountFactor(config)


def test_unknown_symbol_is_null() -> None:
    result = _factor().compute(_context("999999.SH"))

    assert result.status is DataStatus.NULL
    assert result.raw_value is None
    assert result.as_of == FULL_WINDOW_AS_OF
