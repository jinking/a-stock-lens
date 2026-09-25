"""因子长尾（均额、距高点、估值因子、因子注册表）。

本文件由 Task 12「文件合并」把以下 4 个同域小文件整体搬入：
    - tests/unit/test_avg_amount_factor.py（7 例）
    - tests/unit/test_proximity_high_factor.py（8 例）
    - tests/unit/test_valuation_factors.py（8 例）
    - tests/unit/test_factor_registry.py（4 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

import csv
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest, NormalizedDataset
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.domain.enums import DataStatus, FactorDomain
from astock_lens.domain.models import ValuationObservation
from astock_lens.factors.builtin import (
    AverageAmountFactor,
    ProximityToHighFactor,
    build_factor,
)
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.factors.contracts import FactorContext, FactorResult
from astock_lens.factors.registry import FactorRegistry

# ===========================================================================
# 来源：tests/unit/test_avg_amount_factor.py（7 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# First factor tests.
#
# The rule these tests pin down: an incomplete window produces `NULL`, never a
# number computed from fewer days than the window declares. Averaging a shorter
# stretch would silently answer a different question.
# """
#


AVG_AMOUNT_CSV_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "csv"


CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "factors" / "avg_amount_20d.yaml"
)


FULL_WINDOW_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _factor() -> AverageAmountFactor:
    return AverageAmountFactor(load_factor_config(CONFIG_PATH))


def _context(symbol: str, as_of: datetime = FULL_WINDOW_AS_OF) -> FactorContext:
    raw = LocalCsvProvider(AVG_AMOUNT_CSV_ROOT).fetch(
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


# 窗口完整性四行：整窗 / 窗口不足 / 窗口内缺值 / 窗口外缺值。
# 行序与原用例一致，label 即原测试名，原 docstring 逐字保留为行注释。
# 期望值一列原样携带 pytest.approx；None 表示该行要求 raw_value 就是 None。
WINDOW_COMPLETENESS_CASES = (
    # test_full_window_averages_exactly
    (
        "test_full_window_averages_exactly",
        "600000.SH",
        DataStatus.VALUE,
        pytest.approx(1_014_500.0),
    ),
    # test_short_window_is_null_not_a_smaller_average:
    #   000001.SZ only has 10 bars, so no 20-day average exists.
    (
        "test_short_window_is_null_not_a_smaller_average",
        "000001.SZ",
        DataStatus.NULL,
        None,
    ),
    # test_missing_amount_inside_the_window_forces_null:
    #   601398.SH has a blank amount on one of its trailing 20 bars.
    (
        "test_missing_amount_inside_the_window_forces_null",
        "601398.SH",
        DataStatus.NULL,
        None,
    ),
    # test_missing_amount_outside_the_window_is_harmless:
    #   600519.SH has a blank amount only on its oldest bar.
    (
        "test_missing_amount_outside_the_window_is_harmless",
        "600519.SH",
        DataStatus.VALUE,
        pytest.approx(3_014_500.0),
    ),
)


def test_window_completeness_decides_value_or_null() -> None:
    """窗口不足或窗口内缺值返回 NULL，绝不用更短的窗口凑一个平均。"""
    wrong = []
    for label, symbol, expected_status, expected_value in WINDOW_COMPLETENESS_CASES:
        result = _factor().compute(_context(symbol))
        if result.status is not expected_status:
            wrong.append(f"{label}: status={result.status!r}，期望 {expected_status!r}")
        if expected_value is None:
            if result.raw_value is not None:
                wrong.append(f"{label}: raw_value={result.raw_value!r}，期望 None")
        elif result.raw_value != expected_value:
            wrong.append(
                f"{label}: raw_value={result.raw_value!r}，期望 {expected_value!r}"
            )
    assert not wrong, "窗口完整性判定未按预期:\n" + "\n".join(wrong)


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


# ===========================================================================
# 来源：tests/unit/test_proximity_high_factor.py（8 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Distance-from-high factor.
#
# `proximity_52w_high` is the latest close divided by the highest high of the
# trailing window, so a symbol trading at its own peak scores 1.0 and a symbol
# far below its peak scores lower. The expected values are recomputed from the
# fixture's own columns, not from the factor.
# """
#


ROOT = Path(__file__).resolve().parents[2]


CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"


FIXTURE = CSV_ROOT / "daily_bars_long.csv"


AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


DATASET = "daily_bars_long"


WINDOW = 252


# Symbols whose paths include a planted high well above the latest close.
SPIKED = ("300750.SZ", "600000.SH", "600519.SH", "830799.BJ")


def _proximity_config() -> FactorConfig:
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
    return ProximityToHighFactor(_proximity_config()).compute(
        FactorContext(symbol=symbol, as_of=AS_OF, dataset=dataset or _dataset())
    )


def _with_null_high(dataset: NormalizedDataset, symbol: str) -> NormalizedDataset:
    """抹掉窗口内第 40 根 bar 的 high。"""
    ordered = sorted(
        (bar for bar in dataset.daily_bars if bar.symbol == symbol),
        key=lambda bar: bar.trade_date,
    )
    target = ordered[-40]
    bars = tuple(
        bar.model_copy(update={"high": None}) if bar == target else bar
        for bar in dataset.daily_bars
    )
    return dataset.model_copy(update={"daily_bars": bars})


def _with_zero_peak(dataset: NormalizedDataset, symbol: str) -> NormalizedDataset:
    """把一只标的的全部 bar 的 high 与 close 归零。"""
    bars = tuple(
        bar.model_copy(update={"high": 0.0, "close": 0.0})
        if bar.symbol == symbol
        else bar
        for bar in dataset.daily_bars
    )
    return dataset.model_copy(update={"daily_bars": bars})


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


# 缺数据四行：窗口内缺 high / 窗口不足 / 标的未知 / 峰值与收盘价为 0。
# 行序与原用例一致，label 即原测试名，原 docstring 逐字保留为行注释；
# mutate 为 None 表示用未改动的数据集。
NULL_CASES = (
    # test_a_missing_high_inside_the_window_is_null
    ("test_a_missing_high_inside_the_window_is_null", "600000.SH", _with_null_high),
    # test_too_few_bars_is_null:
    #   000004.SZ has 34 bars, far short of a 252-bar window.
    ("test_too_few_bars_is_null", "000004.SZ", None),
    # test_an_unknown_symbol_is_null
    ("test_an_unknown_symbol_is_null", "999999.SH", None),
    # test_a_zero_peak_is_null_rather_than_infinite
    ("test_a_zero_peak_is_null_rather_than_infinite", "600000.SH", _with_zero_peak),
)


def test_missing_high_or_insufficient_window_is_null() -> None:
    """窗口内缺 high、窗口不足、标的未知或峰值为 0：一律 NULL，不扁平化也不取无限值。"""
    wrong = []
    for label, symbol, mutate in NULL_CASES:
        dataset = _dataset()
        if mutate is not None:
            dataset = mutate(dataset, symbol)
        result = _compute(symbol, dataset=dataset)
        if result.status is not DataStatus.NULL or result.raw_value is not None:
            wrong.append(
                f"{label}: status={result.status!r} value={result.raw_value!r}，期望 NULL/None"
            )
    assert not wrong, "缺数据未按预期返回 NULL:\n" + "\n".join(wrong)


def test_metadata_and_window_come_from_the_configuration() -> None:
    factor = ProximityToHighFactor(_proximity_config())

    assert factor.metadata.name == "proximity_52w_high"
    assert factor.metadata.domain is FactorDomain.MARKET_MOMENTUM
    assert factor.metadata.inputs == ("close", "high")
    assert factor.metadata.version == "v1"
    assert _proximity_config().params["window"] == WINDOW


def test_a_configuration_without_a_window_is_an_error() -> None:
    config = _proximity_config().model_copy(update={"params": {}})

    with pytest.raises(ValueError, match="params.window"):
        ProximityToHighFactor(config)


def test_a_configuration_for_another_factor_is_rejected() -> None:
    """The class is bound to one factor name, unlike the parameterised returns."""
    config = load_factor_config(ROOT / "configs" / "factors" / "ret_20d.yaml")

    with pytest.raises(ValueError, match="proximity_52w_high"):
        ProximityToHighFactor(config)


# ===========================================================================
# 来源：tests/unit/test_valuation_factors.py（8 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 估值因子测试。
#
# 除了常规的时点选择，这里钉住一条本次新定的政策：
# **倍数非正即不适用**。负现金流、负净资产、负增长给出的负倍数不是"更便宜"，
# 是这个量不存在；让它以"越低越便宜"的姿态排到榜首，会把最差的公司选成最便宜的。
# 百分位不受此约束——`0.000` 是合法分位。
# """
#


VALUATION_ROOT = Path(__file__).resolve().parents[2]


FACTOR_DIR = VALUATION_ROOT / "configs" / "factors"


VALUATION_AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


SYMBOL = "600519.SH"


def _config(name: str) -> FactorConfig:
    return load_factor_config(FACTOR_DIR / f"{name}.yaml")


def _observation(
    metric: str,
    value: float | None,
    *,
    day: date = date(2026, 9, 16),
    symbol: str = SYMBOL,
) -> ValuationObservation:
    return ValuationObservation(
        symbol=symbol,
        metric=metric,
        valuation_date=day,
        available_at=datetime(day.year, day.month, day.day, 15, tzinfo=UTC),
        as_of=VALUATION_AS_OF,
        source="neodata",
        value=value,
        unit="x",
    )


def _valuation_context(
    *observations: ValuationObservation, as_of: datetime = VALUATION_AS_OF
) -> FactorContext:
    return FactorContext(
        symbol=SYMBOL,
        as_of=as_of,
        dataset=NormalizedDataset(
            dataset="valuation", as_of=as_of, valuations=tuple(observations)
        ),
    )


def test_a_positive_multiple_is_a_value() -> None:
    result = build_factor(_config("pe_ttm")).compute(
        _valuation_context(_observation("pe_ttm", 14.19))
    )

    assert result.status is DataStatus.VALUE
    assert result.raw_value == pytest.approx(14.19)
    assert result.unit == "x"
    assert result.inputs[0].report_period == date(2026, 9, 16)


def test_a_non_positive_multiple_is_not_applicable() -> None:
    """负倍数不是便宜，是不存在。"""
    wrong = []
    for factor in ("pe_ttm", "pb", "ps_ttm", "pcf_operating_ttm", "peg"):
        result = build_factor(_config(factor)).compute(
            _valuation_context(_observation(factor, -71.31))
        )
        if (
            result.status is not DataStatus.NOT_APPLICABLE
            or result.raw_value is not None
        ):
            wrong.append(
                f"{factor}: status={result.status!r} value={result.raw_value!r}"
            )
    assert not wrong, "非正倍数应为 NOT_APPLICABLE:\n" + "\n".join(wrong)


def test_a_zero_percentile_is_still_a_value() -> None:
    """分位为 0 表示"处在自身历史最便宜处"，完全合法。"""
    result = build_factor(_config("pe_percentile")).compute(
        _valuation_context(_observation("pe_percentile", 0.0))
    )

    assert result.status is DataStatus.VALUE
    assert result.raw_value == 0.0


def test_a_symbol_that_never_reports_the_metric_is_not_applicable() -> None:
    result = build_factor(_config("pb")).compute(_valuation_context())

    assert result.status is DataStatus.NOT_APPLICABLE


def test_a_metric_reported_only_after_the_point_in_time_is_null() -> None:
    """有观测但还没到可用时点：`NULL`（缺），不是 `NOT_APPLICABLE`（不适用）。"""
    early = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    context = _valuation_context(_observation("pb", 2.33), as_of=early)

    assert build_factor(_config("pb")).compute(context).status is DataStatus.NULL


def test_the_newest_available_day_wins() -> None:
    context = _valuation_context(
        _observation("pb", 3.0, day=date(2026, 9, 10)),
        _observation("pb", 2.0, day=date(2026, 9, 16)),
    )

    result = build_factor(_config("pb")).compute(context)

    assert result.raw_value == pytest.approx(2.0)
    assert result.inputs[0].report_period == date(2026, 9, 16)


def test_a_reviewed_freshness_bound_switches_stale_on(local_tmp: Path) -> None:
    """机制就绪：配置写天数即启用（当前出货配置写的是 null）。"""
    payload = {
        "name": "pb",
        "domain": "VALUATION",
        "description": "pb",
        "inputs": ["pb"],
        "frequency": "DAILY",
        "direction": "LOWER_MEANS_CHEAPER",
        "null_policy": "NULL_UNLESS_THE_METRIC_HAS_A_PUBLISHED_VALUE",
        "version": "v1",
        "params": {"stale_after_days": 30},
    }
    config = FactorConfig.model_validate(payload)
    context = _valuation_context(_observation("pb", 2.0, day=date(2026, 1, 5)))

    assert build_factor(config).compute(context).status is DataStatus.STALE


def test_the_freshness_key_must_be_declared() -> None:
    payload = {
        "name": "pb",
        "domain": "VALUATION",
        "description": "pb",
        "inputs": ["pb"],
        "frequency": "DAILY",
        "direction": "LOWER_MEANS_CHEAPER",
        "null_policy": "NULL_UNLESS_THE_METRIC_HAS_A_PUBLISHED_VALUE",
        "version": "v1",
        "params": {},
    }

    with pytest.raises(ValueError, match="stale_after_days"):
        build_factor(FactorConfig.model_validate(payload))


# ===========================================================================
# 来源：tests/unit/test_factor_registry.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Factor registry tests."""
#


REGISTRY_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "factors" / "avg_amount_20d.yaml"
)


def _registry_factor() -> AverageAmountFactor:
    return AverageAmountFactor(load_factor_config(REGISTRY_CONFIG_PATH))


def test_registration_preserves_order() -> None:
    registry = FactorRegistry()
    registry.register(_registry_factor())

    assert registry.names() == ("avg_amount_20d",)


def test_duplicate_registration_is_rejected() -> None:
    registry = FactorRegistry()
    registry.register(_registry_factor())

    with pytest.raises(ValueError, match="avg_amount_20d"):
        registry.register(_registry_factor())


def test_unknown_lookup_is_rejected() -> None:
    registry = FactorRegistry()

    with pytest.raises(KeyError, match="nonexistent"):
        registry.get("nonexistent")


def test_registered_factor_is_returned_by_name() -> None:
    registry = FactorRegistry()
    factor = _registry_factor()
    registry.register(factor)

    assert registry.get("avg_amount_20d") is factor
