"""估值覆盖报告的语义测试。

这份报告要能替打分器说话，所以测试盯的是四件事：

1. 未采集的标的进 `uncovered_symbols`，**不是** 0；
2. 策略缺任意一个估值侧必需因子就不可打分；
3. 未来时点的观测不计入当期覆盖；
4. 因子语义按 `ValuationFactor` 走——负 PEG 不是"更匹配"，是 `NOT_APPLICABLE`。
"""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from astock_lens.calibration.valuation_coverage import valuation_coverage
from astock_lens.domain.models import ValuationObservation
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.strategies.config import StrategyConfig, load_strategy_config

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

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
    available_at: datetime = AS_OF,
    as_of: datetime = AS_OF,
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
        as_of=AS_OF,
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
        as_of=AS_OF,
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
    later = datetime(2026, 9, 25, 15, 0, tzinfo=AS_OF.tzinfo)
    report = valuation_coverage(
        (_observation("600519.SH", "pe_ttm", 19.31, available_at=later, as_of=later),),
        as_of=AS_OF,
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
        as_of=AS_OF,
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
            as_of=AS_OF,
            universe=("600519.SH",),
            strategy_configs=(garp_config,),
        )


def test_an_empty_universe_is_refused() -> None:
    with pytest.raises(ValueError, match="研究池"):
        valuation_coverage((), as_of=AS_OF, universe=())


def test_a_strategy_without_valuation_factors_is_not_reported_as_covered() -> None:
    """空交集不是全覆盖：Momentum 不需要估值，但它也不因此"估值侧可打分"。"""
    momentum = load_strategy_config(CONFIGS / "strategies" / "momentum.yaml")

    report = valuation_coverage(
        (),
        as_of=AS_OF,
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
        as_of=AS_OF,
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
