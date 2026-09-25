"""Distance-from-high factor.

`proximity_52w_high` is the latest close divided by the highest high of the
trailing window, so a symbol trading at its own peak scores 1.0 and a symbol
far below its peak scores lower. The expected values are recomputed from the
fixture's own columns, not from the factor.
"""

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest, NormalizedDataset
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.domain.enums import DataStatus, FactorDomain
from astock_lens.factors.builtin import ProximityToHighFactor
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.factors.contracts import FactorContext, FactorResult

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
FIXTURE = CSV_ROOT / "daily_bars_long.csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
DATASET = "daily_bars_long"

WINDOW = 252

# Symbols whose paths include a planted high well above the latest close.
SPIKED = ("300750.SZ", "600000.SH", "600519.SH", "830799.BJ")


def _config() -> FactorConfig:
    return load_factor_config(ROOT / "configs" / "factors" / "proximity_52w_high.yaml")


def _dataset() -> NormalizedDataset:
    raw = LocalCsvProvider(CSV_ROOT).fetch(FetchRequest(dataset=DATASET, as_of=AS_OF))
    return CsvDailyBarNormalizer().normalize(raw, as_of=AS_OF)


def _columns(symbol: str) -> tuple[list[float], list[float]]:
    """Return (closes, highs) for one symbol, straight from the CSV."""
    closes: list[float] = []
    highs: list[float] = []
    with FIXTURE.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["symbol"] == symbol:
                closes.append(float(row["close"]))
                highs.append(float(row["high"]))
    return closes, highs


def _compute(symbol: str, *, dataset: NormalizedDataset | None = None) -> FactorResult:
    return ProximityToHighFactor(_config()).compute(
        FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset or _dataset())
    )


def test_proximity_equals_the_latest_close_over_the_window_peak() -> None:
    wrong = []
    for symbol in (*SPIKED, "000001.SZ", "900948.SH"):
        closes, highs = _columns(symbol)
        expected = closes[-1] / max(highs[-WINDOW:])
        result = _compute(symbol)
        if result.status is not DataStatus.VALUE or result.raw_value != pytest.approx(
            expected, rel=1e-9
        ):
            wrong.append(
                f"{symbol}: status={result.status!r} value={result.raw_value!r} expected={expected!r}"
            )
    assert not wrong, "近高点不等于收盘/窗口峰值:\n" + "\n".join(wrong)


def test_a_planted_high_pulls_proximity_below_a_flat_ratio() -> None:
    """没有植入的高点，每个上涨标的都会得到同一个 1/1.01。"""
    wrong = [
        f"{symbol}: {_compute(symbol).raw_value!r}"
        for symbol in SPIKED
        if not (
            _compute(symbol).raw_value is not None
            and _compute(symbol).raw_value < 1 / 1.01
        )
    ]
    assert not wrong, "植入高点未把近高压到平坦比之下:\n" + "\n".join(wrong)


def test_proximity_never_exceeds_one() -> None:
    for symbol in (*SPIKED, "000001.SZ", "900948.SH"):
        result = _compute(symbol)
        assert result.raw_value is not None
        assert result.raw_value <= 1.0


def test_a_falling_symbol_sits_far_below_its_peak() -> None:
    falling = _compute("000001.SZ").raw_value
    rising = _compute("600000.SH").raw_value

    assert falling is not None
    assert rising is not None
    assert falling < rising


def test_a_missing_high_inside_the_window_is_null() -> None:
    dataset = _dataset()
    ordered = sorted(
        (bar for bar in dataset.daily_bars if bar.symbol == "600000.SH"),
        key=lambda bar: bar.trade_date,
    )
    target = ordered[-40]
    bars = tuple(
        bar.model_copy(update={"high": None}) if bar == target else bar
        for bar in dataset.daily_bars
    )

    result = _compute(
        "600000.SH", dataset=dataset.model_copy(update={"daily_bars": bars})
    )

    assert result.status is DataStatus.NULL
    assert result.raw_value is None


def test_too_few_bars_is_null() -> None:
    """000004.SZ has 34 bars, far short of a 252-bar window."""
    result = _compute("000004.SZ")

    assert result.status is DataStatus.NULL
    assert result.raw_value is None


def test_an_unknown_symbol_is_null() -> None:
    result = _compute("999999.SH")

    assert result.status is DataStatus.NULL
    assert result.raw_value is None


def test_a_zero_peak_is_null_rather_than_infinite() -> None:
    dataset = _dataset()
    bars = tuple(
        bar.model_copy(update={"high": 0.0, "close": 0.0})
        if bar.symbol == "600000.SH"
        else bar
        for bar in dataset.daily_bars
    )

    result = _compute(
        "600000.SH", dataset=dataset.model_copy(update={"daily_bars": bars})
    )

    assert result.status is DataStatus.NULL
    assert result.raw_value is None


def test_metadata_and_window_come_from_the_configuration() -> None:
    factor = ProximityToHighFactor(_config())

    assert factor.metadata.name == "proximity_52w_high"
    assert factor.metadata.domain is FactorDomain.MARKET_MOMENTUM
    assert factor.metadata.inputs == ("close", "high")
    assert factor.metadata.version == "v1"
    assert _config().params["window"] == WINDOW


def test_a_configuration_without_a_window_is_an_error() -> None:
    config = _config().model_copy(update={"params": {}})

    with pytest.raises(ValueError, match="params.window"):
        ProximityToHighFactor(config)


def test_a_configuration_for_another_factor_is_rejected() -> None:
    """The class is bound to one factor name, unlike the parameterised returns."""
    config = load_factor_config(ROOT / "configs" / "factors" / "ret_20d.yaml")

    with pytest.raises(ValueError, match="proximity_52w_high"):
        ProximityToHighFactor(config)
