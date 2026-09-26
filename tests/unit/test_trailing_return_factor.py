"""Trailing-return factors.

The expected values are recomputed here from the fixture's own `close` column
rather than by calling the factor, so the assertion is an independent check on
the implementation instead of a restatement of it.
"""

import csv
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest, NormalizedDataset
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.domain.enums import DataStatus, FactorDomain
from astock_lens.factors.builtin import TrailingReturnFactor
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.factors.contracts import FactorContext, FactorResult

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
FIXTURE = CSV_ROOT / "daily_bars_long.csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
DATASET = "daily_bars_long"

RANKED = (
    "300750.SZ",
    "600000.SH",
    "830799.BJ",
    "600519.SH",
    "900948.SH",
    "000001.SZ",
)


def _config(name: str = "ret_20d") -> FactorConfig:
    return load_factor_config(ROOT / "configs" / "factors" / f"{name}.yaml")


def _dataset() -> NormalizedDataset:
    raw = LocalCsvProvider(CSV_ROOT).fetch(FetchRequest(dataset=DATASET, as_of=AS_OF))
    return CsvDailyBarNormalizer().normalize(raw, as_of=AS_OF)


def _closes(symbol: str) -> list[float]:
    """Read one symbol's closes straight from the CSV, bypassing every module."""
    values: list[float] = []
    with FIXTURE.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["symbol"] == symbol:
                values.append(float(row["close"]))
    return values


def _compute(
    symbol: str,
    *,
    config: FactorConfig | None = None,
    dataset: NormalizedDataset | None = None,
) -> FactorResult:
    factor = TrailingReturnFactor(config or _config())
    return factor.compute(
        FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset or _dataset())
    )


def _with_null_close(
    dataset: NormalizedDataset, symbol: str, *, days_before_end: int
) -> NormalizedDataset:
    """Blank one close inside the trailing window."""
    ordered = sorted(
        (bar for bar in dataset.daily_bars if bar.symbol == symbol),
        key=lambda bar: bar.trade_date,
    )
    target = ordered[-1 - days_before_end]
    bars = tuple(
        bar.model_copy(update={"close": None}) if bar == target else bar
        for bar in dataset.daily_bars
    )
    return dataset.model_copy(update={"daily_bars": bars})


def _with_zero_close(dataset: NormalizedDataset, symbol: str) -> NormalizedDataset:
    """置零窗口起点那根 bar 的收盘价。"""
    ordered = sorted(
        (bar for bar in dataset.daily_bars if bar.symbol == symbol),
        key=lambda bar: bar.trade_date,
    )
    target = ordered[-21]
    bars = tuple(
        bar.model_copy(update={"close": 0.0}) if bar == target else bar
        for bar in dataset.daily_bars
    )
    return dataset.model_copy(update={"daily_bars": bars})


def test_return_equals_the_ratio_of_the_window_ends() -> None:
    """20 日收益跨 21 个收盘价：今天对 20 天前。"""
    wrong = []
    for symbol in RANKED:
        closes = _closes(symbol)
        expected = closes[-1] / closes[-21] - 1
        result = _compute(symbol)
        if result.status is not DataStatus.VALUE or result.raw_value != pytest.approx(
            expected, rel=1e-9
        ):
            wrong.append(
                f"{symbol}: status={result.status!r} value={result.raw_value!r} expected={expected!r}"
            )
    assert not wrong, "收益不等于窗口两端比:\n" + "\n".join(wrong)


def test_the_designed_ordering_holds() -> None:
    """The fixture's price paths were built to give one unambiguous ranking."""
    values = {symbol: _compute(symbol).raw_value for symbol in RANKED}

    ordered = sorted(RANKED, key=lambda symbol: values[symbol])  # type: ignore[arg-type,return-value]
    assert tuple(reversed(ordered)) == RANKED


def test_a_sixty_day_return_spans_a_longer_window() -> None:
    closes = _closes("600000.SH")
    expected = closes[-1] / closes[-61] - 1

    result = _compute("600000.SH", config=_config("ret_60d"))

    assert result.raw_value == pytest.approx(expected, rel=1e-9)


# 缺数据 / 窗口不足的 NULL 族六行：行序与原用例一致，label 即原测试名，
# 原 docstring 逐字保留为行注释。config 为 None 表示默认 ret_20d，
# mutate 为 None 表示用未改动的数据集；其余每行的输入逐字来自原用例。
NULL_CASES = (
    # test_too_few_bars_for_the_window_is_null:
    #   000004.SZ has 34 bars, so a 61-bar window cannot be satisfied.
    ("test_too_few_bars_for_the_window_is_null", "000004.SZ", _config("ret_60d"), None),
    # test_the_window_is_never_shortened_to_fit:
    #   A 300-bar window needs 301 closes, and the fixture supplies exactly 300.
    (
        "test_the_window_is_never_shortened_to_fit",
        "600000.SH",
        _config().model_copy(update={"params": {"window": 300}}),
        None,
    ),
    # test_an_unknown_symbol_is_null
    ("test_an_unknown_symbol_is_null", "999999.SH", None, None),
    # test_a_missing_close_inside_the_window_is_null:
    #   A hole in the window is not interpolated and not skipped over.
    (
        "test_a_missing_close_inside_the_window_is_null",
        "600000.SH",
        None,
        lambda dataset, symbol: _with_null_close(dataset, symbol, days_before_end=10),
    ),
    # test_a_missing_close_at_the_window_edge_is_null
    (
        "test_a_missing_close_at_the_window_edge_is_null",
        "600000.SH",
        None,
        lambda dataset, symbol: _with_null_close(dataset, symbol, days_before_end=20),
    ),
    # test_a_zero_starting_close_is_null_rather_than_infinite
    (
        "test_a_zero_starting_close_is_null_rather_than_infinite",
        "600000.SH",
        None,
        _with_zero_close,
    ),
)


def test_missing_or_insufficient_data_is_null() -> None:
    """窗口不足、标的未知、窗口内缺收盘价或起点收盘价为 0：一律 NULL，
    不插值、不跳过、不缩短窗口，也不拿零收盘价去算无限收益。"""
    wrong = []
    for label, symbol, config, mutate in NULL_CASES:
        dataset = _dataset()
        if mutate is not None:
            dataset = mutate(dataset, symbol)
        result = _compute(symbol, config=config, dataset=dataset)
        if result.status is not DataStatus.NULL or result.raw_value is not None:
            wrong.append(
                f"{label}: status={result.status!r} value={result.raw_value!r}，期望 NULL/None"
            )
    assert not wrong, "缺数据未按预期返回 NULL:\n" + "\n".join(wrong)


def test_bars_after_the_as_of_date_are_ignored() -> None:
    """A different as-of must move the window, not reuse the newest bars."""
    earlier = datetime(2026, 8, 28, 15, 0, tzinfo=UTC)
    raw = LocalCsvProvider(CSV_ROOT).fetch(FetchRequest(dataset=DATASET, as_of=earlier))
    dataset = CsvDailyBarNormalizer().normalize(raw, as_of=earlier)

    today = _compute("600000.SH").raw_value
    then = (
        TrailingReturnFactor(_config())
        .compute(FactorContext(symbol="600000.SH", as_of=earlier, dataset=dataset))
        .raw_value
    )

    assert then is not None
    assert today != then


def test_a_result_carries_its_version_and_time() -> None:
    result = _compute("600000.SH")

    assert result.factor == "ret_20d"
    assert result.factor_version == "v1"
    assert result.as_of == AS_OF
    assert result.lineage.factor_version == "v1"


def test_metadata_comes_from_the_configuration() -> None:
    factor = TrailingReturnFactor(_config())

    assert factor.metadata.name == "ret_20d"
    assert factor.metadata.domain is FactorDomain.MARKET_MOMENTUM
    assert factor.metadata.version == "v1"


def test_a_configuration_without_a_window_is_an_error() -> None:
    config = _config().model_copy(update={"params": {}})

    with pytest.raises(ValueError, match="params.window"):
        TrailingReturnFactor(config)


def test_a_non_positive_window_is_rejected() -> None:
    config = _config().model_copy(update={"params": {"window": 0}})

    with pytest.raises(ValueError, match="positive"):
        TrailingReturnFactor(config)


def test_the_60_day_configuration_declares_its_own_window() -> None:
    """Windows are configuration, so the two factors share one implementation."""
    assert _config("ret_20d").params["window"] == 20
    assert _config("ret_60d").params["window"] == 60
    assert _config("ret_60d").name == "ret_60d"


def test_the_fixture_still_ends_on_the_as_of_date() -> None:
    """Guard against a regenerated fixture drifting away from these tests."""
    closes = _dataset()
    last = max(bar.trade_date for bar in closes.daily_bars)

    assert last == date(2026, 9, 4)
