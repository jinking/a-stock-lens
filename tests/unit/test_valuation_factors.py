"""估值因子测试。

除了常规的时点选择，这里钉住一条本次新定的政策：
**倍数非正即不适用**。负现金流、负净资产、负增长给出的负倍数不是"更便宜"，
是这个量不存在；让它以"越低越便宜"的姿态排到榜首，会把最差的公司选成最便宜的。
百分位不受此约束——`0.000` 是合法分位。
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import NormalizedDataset
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import ValuationObservation
from astock_lens.factors.builtin import build_factor
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.factors.contracts import FactorContext

ROOT = Path(__file__).resolve().parents[2]
FACTOR_DIR = ROOT / "configs" / "factors"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
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
        as_of=AS_OF,
        source="neodata",
        value=value,
        unit="x",
    )


def _context(
    *observations: ValuationObservation, as_of: datetime = AS_OF
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
        _context(_observation("pe_ttm", 14.19))
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
            _context(_observation(factor, -71.31))
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
        _context(_observation("pe_percentile", 0.0))
    )

    assert result.status is DataStatus.VALUE
    assert result.raw_value == 0.0


def test_a_symbol_that_never_reports_the_metric_is_not_applicable() -> None:
    result = build_factor(_config("pb")).compute(_context())

    assert result.status is DataStatus.NOT_APPLICABLE


def test_a_metric_reported_only_after_the_point_in_time_is_null() -> None:
    """有观测但还没到可用时点：`NULL`（缺），不是 `NOT_APPLICABLE`（不适用）。"""
    early = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    context = _context(_observation("pb", 2.33), as_of=early)

    assert build_factor(_config("pb")).compute(context).status is DataStatus.NULL


def test_the_newest_available_day_wins() -> None:
    context = _context(
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
    context = _context(_observation("pb", 2.0, day=date(2026, 1, 5)))

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
