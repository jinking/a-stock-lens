"""Unit tests for calibration report engine and deterministic rendering."""

from datetime import UTC, datetime

import pytest

from astock_lens.calibration import (
    CALIBRATION_WARNING,
    generate_calibration_report,
    render_json,
    render_markdown,
)
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LINEAGE = SnapshotLineage(factor_version="v1", strategy_version="v1")


def _strat(
    symbol: str, strategy_id: str, percentile: float, score: float
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=LINEAGE,
        score=score,
        rank_percentile=percentile,
    )


def _factor(
    symbol: str, factor: str, value: float | None, status: DataStatus = DataStatus.VALUE
) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        factor_version="v1",
        as_of=AS_OF,
        status=status,
        raw_value=value,
        lineage=LINEAGE,
    )


def test_empty_industry_map_raises_value_error() -> None:
    with pytest.raises(ValueError, match="industry_map"):
        generate_calibration_report(
            as_of=AS_OF,
            strategy_results=(),
            factor_results=(),
            industry_map={},
        )


def test_calibration_report_statistics_and_warning() -> None:
    ind_map = {
        "600001.SH": "银行",
        "600002.SH": "电子",
        "600003.SH": "医药",
    }
    s_results = [
        _strat("600001.SH", "value", 0.95, 95.0),
        _strat("600002.SH", "value", 0.91, 91.0),
        _strat("600003.SH", "value", 0.85, 85.0),
        _strat("600004.SH", "value", 0.70, 70.0),  # unknown industry
    ]
    f_results = [
        _factor("600001.SH", "peg", 1.2),
        _factor("600002.SH", "peg", 0.8),
        _factor("600003.SH", "net_profit_parent_yoy", 25.0),
        _factor("600004.SH", "dividend_payout_ttm", None, status=DataStatus.NULL),
    ]

    report = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=s_results,
        factor_results=f_results,
        industry_map=ind_map,
    )

    assert report.warning == CALIBRATION_WARNING
    assert report.industry_coverage_ratio == 0.75  # 3 out of 4
    assert report.unknown_industry_count == 1
    assert len(report.strategies) == 1

    strat = report.strategies[0]
    assert strat.strategy_id == "value"
    assert strat.evaluable_count == 4
    assert strat.ranked_count == 4
    assert strat.percentile_boundary_90 == 0.91
    assert "600001.SH" in strat.top_symbols
    assert "600002.SH" in strat.boundary_above_symbols
    assert "600003.SH" in strat.boundary_below_symbols

    # Sensitivity counts:
    # 0.80: 3 (0.95, 0.91, 0.85)
    # 0.85: 3
    # 0.90: 2 (0.95, 0.91)
    # 0.95: 1 (0.95)
    sens = dict(strat.sensitivity_counts)
    assert sens[0.80] == 3
    assert sens[0.85] == 3
    assert sens[0.90] == 2
    assert sens[0.95] == 1

    # Anomaly summaries
    anom_map = dict(report.factor_anomalies)
    assert "peg" in anom_map
    assert "min=0.80" in anom_map["peg"]
    assert "net_profit_parent_yoy" in anom_map

    # DataStatus counts
    status_map = dict(report.data_status_counts)
    assert status_map[DataStatus.VALUE.value] == 3
    assert status_map[DataStatus.NULL.value] == 1


def test_deterministic_rendering_byte_for_byte() -> None:
    ind_map = {"600001.SH": "银行", "600002.SH": "电子"}
    s1 = _strat("600001.SH", "value", 0.95, 95.0)
    s2 = _strat("600002.SH", "value", 0.85, 85.0)
    f1 = _factor("600001.SH", "peg", 1.5)
    f2 = _factor("600002.SH", "peg", 2.0)

    # Order A
    rep_a = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=[s1, s2],
        factor_results=[f1, f2],
        industry_map=ind_map,
    )
    # Order B (reversed)
    rep_b = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=[s2, s1],
        factor_results=[f2, f1],
        industry_map=ind_map,
    )

    md_a = render_markdown(rep_a)
    md_b = render_markdown(rep_b)
    assert md_a == md_b

    json_a = render_json(rep_a)
    json_b = render_json(rep_b)
    assert json_a == json_b
    assert CALIBRATION_WARNING in md_a
    assert CALIBRATION_WARNING in json_a
