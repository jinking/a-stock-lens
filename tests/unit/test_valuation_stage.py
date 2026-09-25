"""估值阶段（覆盖率、归一化）长尾用例。

本文件由 Task 12「文件合并」把以下 2 个同域小文件整体搬入：
    - tests/unit/test_valuation_coverage.py（8 例）
    - tests/unit/test_valuation_normalizer.py（8 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from astock_lens.calibration.valuation_coverage import valuation_coverage
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.normalize.valuations import (
    ALL_METRICS,
    NeodataValuationNormalizer,
)
from astock_lens.data.providers.neodata import PAYLOAD_COLUMNS
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import ValuationObservation
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.strategies.config import StrategyConfig, load_strategy_config

# ===========================================================================
# 来源：tests/unit/test_valuation_coverage.py（8 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 估值覆盖报告的语义测试。
#
# 这份报告要能替打分器说话，所以测试盯的是四件事：
#
# 1. 未采集的标的进 `uncovered_symbols`，**不是** 0；
# 2. 策略缺任意一个估值侧必需因子就不可打分；
# 3. 未来时点的观测不计入当期覆盖；
# 4. 因子语义按 `ValuationFactor` 走——负 PEG 不是"更匹配"，是 `NOT_APPLICABLE`。
# """
#


COVERAGE_ROOT = Path(__file__).resolve().parents[2]


CONFIGS = COVERAGE_ROOT / "configs"


COVERAGE_AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


VALUATION_FACTOR_FILES = (
    "pe_ttm.yaml",
    "pb.yaml",
    "ps_ttm.yaml",
    "pe_percentile.yaml",
    "pcf_operating_ttm.yaml",
    "peg.yaml",
)


def _factor_configs(*names: str) -> tuple[FactorConfig, ...]:
    wanted = set(names)
    loaded = [
        load_factor_config(CONFIGS / "factors" / filename)
        for filename in VALUATION_FACTOR_FILES
    ]
    return tuple(config for config in loaded if config.name in wanted)


def _observation(
    symbol: str,
    metric: str,
    value: float | None,
    *,
    available_at: datetime = COVERAGE_AS_OF,
    as_of: datetime = COVERAGE_AS_OF,
) -> ValuationObservation:
    return ValuationObservation(
        symbol=symbol,
        metric=metric,
        valuation_date=date(2026, 9, 16),
        available_at=available_at,
        as_of=as_of,
        source="neodata",
        value=value,
        unit="x",
    )


def test_an_uncollected_symbol_is_uncovered_not_zero() -> None:
    report = valuation_coverage(
        (_observation("600519.SH", "pe_ttm", 19.31),),
        as_of=COVERAGE_AS_OF,
        universe=("600519.SH", "000001.SZ"),
    )

    assert report.universe_size == 2
    assert report.covered_symbols == ("600519.SH",)
    assert report.uncovered_symbols == ("000001.SZ",)
    (pe,) = [item for item in report.metrics if item.metric == "pe_ttm"]
    assert pe.symbols_with_value == ("600519.SH",)
    assert pe.ratio == 0.5


def test_a_strategy_needs_every_valuation_factor_it_declares() -> None:
    value_config = load_strategy_config(CONFIGS / "strategies" / "value.yaml")
    observations = (
        _observation("600519.SH", "pe_ttm", 19.31),
        _observation("600519.SH", "pb", 7.1),
        _observation("000001.SZ", "pe_ttm", 5.18),
    )

    report = valuation_coverage(
        observations,
        as_of=COVERAGE_AS_OF,
        universe=("600519.SH", "000001.SZ"),
        strategy_configs=(value_config,),
        factor_configs=_factor_configs(
            "pe_ttm", "pb", "ps_ttm", "pe_percentile", "pcf_operating_ttm"
        ),
    )

    (value,) = report.strategies
    assert value.strategy_id == "value"
    # 600519.SH 有 PE 与 PB，但缺 PS / 分位 / 市现率，因此同样不可打分。
    assert value.scoreable_symbols == ()
    assert dict(value.blocking_factors) == {
        "pe_ttm": 0,
        "pb": 1,
        "ps_ttm": 2,
        "pe_percentile": 2,
        "pcf_operating_ttm": 2,
    }
    # 财报因子不在这份报告的判定范围里，必须显式列出而不是默默算进交集。
    assert value.non_valuation_factors == ("roe_ttm",)


def test_a_future_observation_does_not_count_at_this_point_in_time() -> None:
    later = datetime(2026, 9, 25, 15, 0, tzinfo=COVERAGE_AS_OF.tzinfo)
    report = valuation_coverage(
        (_observation("600519.SH", "pe_ttm", 19.31, available_at=later, as_of=later),),
        as_of=COVERAGE_AS_OF,
        universe=("600519.SH",),
    )

    assert report.covered_symbols == ()
    assert report.uncovered_symbols == ("600519.SH",)
    assert report.metrics == ()


def test_a_non_positive_multiple_is_not_scoreable() -> None:
    """负 PEG 是"这个量不存在"，不是"更匹配"——报告必须和打分器同一口径。"""
    garp_config = load_strategy_config(CONFIGS / "strategies" / "garp.yaml")
    observations = (
        _observation("000001.SZ", "peg", -282.08),
        _observation("000001.SZ", "pe_percentile", 57.24),
        _observation("600519.SH", "peg", 19.62),
        _observation("600519.SH", "pe_percentile", 31.43),
    )

    report = valuation_coverage(
        observations,
        as_of=COVERAGE_AS_OF,
        universe=("000001.SZ", "600519.SH"),
        strategy_configs=(garp_config,),
        factor_configs=_factor_configs("peg", "pe_percentile"),
    )

    (garp,) = report.strategies
    assert garp.scoreable_symbols == ("600519.SH",)
    assert garp.ratio == 0.5
    assert dict(garp.blocking_factors)["peg"] == 1
    assert garp.non_valuation_factors == (
        "revenue_cagr_3y",
        "net_profit_parent_cagr_3y",
        "roe_ttm",
    )


def test_a_strategy_without_factor_configs_fails_instead_of_approximating() -> None:
    garp_config = load_strategy_config(CONFIGS / "strategies" / "garp.yaml")

    with pytest.raises(ValueError, match="peg"):
        valuation_coverage(
            (_observation("600519.SH", "peg", 19.62),),
            as_of=COVERAGE_AS_OF,
            universe=("600519.SH",),
            strategy_configs=(garp_config,),
        )


def test_an_empty_universe_is_refused() -> None:
    with pytest.raises(ValueError, match="研究池"):
        valuation_coverage((), as_of=COVERAGE_AS_OF, universe=())


def test_a_strategy_without_valuation_factors_is_not_reported_as_covered() -> None:
    """空交集不是全覆盖：Momentum 不需要估值，但它也不因此"估值侧可打分"。"""
    momentum = load_strategy_config(CONFIGS / "strategies" / "momentum.yaml")

    report = valuation_coverage(
        (),
        as_of=COVERAGE_AS_OF,
        universe=("600519.SH", "000001.SZ"),
        strategy_configs=(momentum,),
    )

    (coverage,) = report.strategies
    assert coverage.valuation_factors == ()
    assert coverage.scoreable_symbols == ()
    assert coverage.ratio == 0.0
    assert coverage.blocking_factors == ()


def test_the_report_serializes_to_json_shape() -> None:
    report = valuation_coverage(
        (_observation("600519.SH", "pe_ttm", 19.31),),
        as_of=COVERAGE_AS_OF,
        universe=("600519.SH",),
        strategy_configs=(
            StrategyConfig(
                id="probe",
                version="v1",
                required_factors=("pe_ttm",),
            ),
        ),
        factor_configs=_factor_configs("pe_ttm"),
    )

    payload = report.to_payload()

    assert payload["universe_size"] == 1
    assert payload["uncovered_symbols"] == []
    assert payload["strategies"][0]["scoreable_symbols"] == ["600519.SH"]


# ===========================================================================
# 来源：tests/unit/test_valuation_normalizer.py（8 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 估值归一化测试（回放 neodata 的真实响应）。
#
# 估值与财务的时点语义不同，所以这里钉住的是估值特有的事情：
#
# - 逐日时序表里的指标**带估值日期**，可以直接做 point-in-time 选值；
# - 键值头的"最新 PE/PB/分位"没有日期，日期取自时序表最新一天；
#   没有时序表时（板块查询）以查询日为日期，并计数为 `dated_from_query`；
# - `--` / `暂无数据` 是"没有值"，不是 0；
# - 分类标签（"低于"）进 `text_value`，只作证据、不进排名。
# """
#


ROOT = Path(__file__).resolve().parents[2]


FIXTURES = ROOT / "tests" / "fixtures" / "neodata"


AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


def _raw(dataset: str) -> RawDataset:
    """把录制响应里 apiRecall 的内容块还原成 Provider 落地时的形状。"""
    payload = json.loads((FIXTURES / f"{dataset}.json").read_text(encoding="utf-8"))
    blocks = payload["data"]["apiData"]["apiRecall"]
    rows = tuple(
        (
            str(b.get("type") or ""),
            str(b.get("desc") or ""),
            str(b.get("content") or ""),
        )
        for b in blocks
    )
    return RawDataset(
        provider="neodata",
        dataset=dataset,
        fetched_at=AS_OF,
        provider_version="v1",
        status=DataStatus.VALUE,
        row_count=len(rows),
        payload=RawPayload(columns=PAYLOAD_COLUMNS, rows=rows),
    )


def test_the_daily_series_becomes_dated_observations() -> None:
    outcome = NeodataValuationNormalizer().normalize(_raw("valuation"), as_of=AS_OF)
    series = [item for item in outcome.observations if item.metric == "peg"]

    assert series
    assert all(item.valuation_date == date(2026, 9, 16) for item in series[:1])
    sample = series[0]
    assert sample.symbol == "000568.SZ"
    assert sample.value == pytest.approx(-99.2619)
    assert sample.unit == "x"
    assert sample.available_at.tzinfo is not None


def test_the_header_metrics_borrow_the_newest_series_date() -> None:
    """键值头只有"最新"，日期取时序表最新一天——这样它也能参与时点选值。"""
    outcome = NeodataValuationNormalizer().normalize(_raw("valuation"), as_of=AS_OF)
    header = {
        item.metric: item
        for item in outcome.observations
        if item.metric in {"pe_ttm", "pb", "pe_percentile", "pb_percentile"}
    }

    assert header["pe_ttm"].value == pytest.approx(14.19)
    assert header["pb"].value == pytest.approx(2.33)
    assert header["pe_percentile"].unit == "%"
    assert {item.valuation_date for item in header.values()} == {date(2026, 9, 16)}
    assert outcome.dated_from_query == 0


def test_a_categorical_label_is_evidence_not_a_number() -> None:
    outcome = NeodataValuationNormalizer().normalize(_raw("valuation"), as_of=AS_OF)
    label = next(
        item
        for item in outcome.observations
        if item.metric == "industry_relative_label"
    )

    assert label.text_value == "低于"
    assert label.value is None


def test_missing_markers_never_become_zero() -> None:
    """时序表里大量 `--`，它们必须是"没有值"。"""
    outcome = NeodataValuationNormalizer().normalize(_raw("valuation"), as_of=AS_OF)
    static_pe = [item for item in outcome.observations if item.metric == "pe_static"]

    # `静态市盈率（倍）` 这一列在录制响应里全部是 `--`，因此不产生任何指标，
    # 而不是产生一堆 0（该列没有映射到指标，因此这里断言它确实没出现）。
    assert static_pe == []
    absent_values = [
        item
        for item in outcome.observations
        if item.value is None and item.metric != "industry_relative_label"
    ]
    assert all(item.text_value is None for item in absent_values)


def test_every_metric_declares_a_unit_or_is_a_label() -> None:
    """单位必须齐备，指标名必须唯一：没有单位的值不可解释。"""
    assert all(item.unit for item in ALL_METRICS)
    assert len({item.metric for item in ALL_METRICS}) == len(ALL_METRICS)


def test_a_sector_block_without_a_series_is_dated_at_the_query_day() -> None:
    """板块估值没有逐日表，服务端给的是"最新"，因此以查询日为日期并计数。"""
    outcome = NeodataValuationNormalizer().normalize(_raw("industry"), as_of=AS_OF)

    assert outcome.observations
    assert outcome.dated_from_query > 0
    assert all(item.valuation_date == AS_OF.date() for item in outcome.observations)
    sector = outcome.observations[0]
    assert sector.symbol == "01801125.PT"
    assert sector.metric in {"pe_ttm", "pb"}


def test_an_empty_source_reports_its_status_instead_of_inventing_rows() -> None:
    raw = RawDataset(
        provider="neodata",
        dataset="valuation",
        fetched_at=AS_OF,
        provider_version="v1",
        status=DataStatus.NULL,
        row_count=0,
    )

    outcome = NeodataValuationNormalizer().normalize(raw, as_of=AS_OF)

    assert outcome.source_status is DataStatus.NULL
    assert outcome.observations == ()
    assert outcome.failures == ()


def test_a_block_without_an_instrument_is_reported_not_guessed() -> None:
    raw = RawDataset(
        provider="neodata",
        dataset="valuation",
        fetched_at=AS_OF,
        provider_version="v1",
        status=DataStatus.VALUE,
        row_count=1,
        payload=RawPayload(
            columns=PAYLOAD_COLUMNS,
            rows=(("统一估值查询", "统一估值查询", "**市净率（倍）**: 3.74"),),
        ),
    )

    outcome = NeodataValuationNormalizer().normalize(raw, as_of=AS_OF)

    assert outcome.observations == ()
    assert outcome.failures[0].label == "标的代码（统一输出字段名）"
