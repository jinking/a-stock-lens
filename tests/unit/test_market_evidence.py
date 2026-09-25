"""Stock market evidence tests.

Auditable evidence layer: ensures volume ratio is computed deterministically
from validated bars without future leakage and without silent fallbacks.
"""

from datetime import UTC, datetime, timedelta

import pytest

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DailyBar, SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.market.evidence import (
    StockMarketEvidence,
    build_stock_market_evidence,
)

AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def _factor_result(
    factor: str, value: float | None, status: DataStatus = DataStatus.VALUE
) -> FactorResult:
    return FactorResult(
        symbol="600519.SH",
        factor=factor,
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _bar(day_offset: int, volume: float) -> DailyBar:
    trade_date = AS_OF.date() - timedelta(days=25 - day_offset)
    return DailyBar(
        symbol="600519.SH",
        trade_date=trade_date,
        open=100.0,
        high=105.0,
        low=99.0,
        close=102.0,
        volume=volume,
        amount=volume * 102.0,
    )


def test_build_stock_market_evidence_computes_exact_volume_ratio() -> None:
    # 20 根有效 bar：前 15 根 volume 为 1000.0，后 5 根 volume 为 2000.0
    # 5日均量 = 2000.0
    # 20日总成交量 = 15 * 1000 + 5 * 2000 = 25000.0，20日均量 = 1250.0
    # volume_ratio_5_20 = 2000.0 / 1250.0 = 1.60
    bars = tuple(_bar(i, 1000.0) for i in range(15)) + tuple(
        _bar(i + 15, 2000.0) for i in range(5)
    )
    factors = (
        _factor_result("ret_20d", 0.12),
        _factor_result("proximity_52w_high", 0.95),
        _factor_result("avg_amount_20d", 500_000_000.0),
    )

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=factors,
        bars=bars,
        as_of=AS_OF,
    )

    assert isinstance(evidence, StockMarketEvidence)
    assert evidence.symbol == "600519.SH"
    assert evidence.as_of == AS_OF
    assert evidence.ret_20d == 0.12
    assert evidence.proximity_52w_high == 0.95
    assert evidence.avg_amount_20d == 500_000_000.0
    assert evidence.volume_ratio_5_20 == pytest.approx(1.60)


def test_fewer_than_20_bars_returns_none_volume_ratio() -> None:
    # 只有 19 根 bar，数据不足以支持 20 日均线，必须返回 None 而绝非 0 或假值
    bars = tuple(_bar(i, 1000.0) for i in range(19))

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=(),
        bars=bars,
        as_of=AS_OF,
    )

    assert evidence.volume_ratio_5_20 is None


def test_future_bars_are_strictly_excluded() -> None:
    # 20 根历史 bar，外加 2 根 as_of 之后的未来 bar
    past_bars = tuple(_bar(i, 1000.0) for i in range(20))
    future_bars = (
        DailyBar(
            symbol="600519.SH",
            trade_date=AS_OF.date() + timedelta(days=1),
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.0,
            volume=50000.0,
        ),
        DailyBar(
            symbol="600519.SH",
            trade_date=AS_OF.date() + timedelta(days=2),
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.0,
            volume=50000.0,
        ),
    )

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=(),
        bars=past_bars + future_bars,
        as_of=AS_OF,
    )

    # 历史 20 根均量 1000.0，5日与20日均为 1000.0，比率为 1.0
    # 若泄漏未来数据，比率会畸高
    assert evidence.volume_ratio_5_20 == pytest.approx(1.0)


def test_missing_or_error_factors_become_none() -> None:
    factors = (
        _factor_result("ret_20d", None, status=DataStatus.NULL),
        _factor_result("proximity_52w_high", 0.80, status=DataStatus.SOURCE_ERROR),
    )

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=factors,
        bars=(),
        as_of=AS_OF,
    )

    assert evidence.ret_20d is None
    assert evidence.proximity_52w_high is None
    assert evidence.avg_amount_20d is None
    assert evidence.volume_ratio_5_20 is None
    assert evidence.relative_strength_60d is None


def test_relative_strength_60d_exact_calculation() -> None:
    # 个股 ret_60d = 0.25, 基准 ret_60d = 0.10
    # 相对强弱 = 0.25 - 0.10 = 0.15
    factors = (_factor_result("ret_60d", 0.25),)

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=factors,
        bars=(),
        as_of=AS_OF,
        benchmark_ret_60d=0.10,
    )

    assert evidence.relative_strength_60d == pytest.approx(0.15)


# 「相对强弱的输入缺失」两行：行序与原用例一致，label 即原测试名。
# 列 = label, payload, expected：
#   - `payload` 逐行保留原 `build_stock_market_evidence(...)` 的关键字参数
#     （第 1 行的 `factors = (...)` 绑定按同一表达式内联）；
#   - `expected` 是该行断言的 `relative_strength_60d` 期望值（原断言为 `is None`），
#     比对方式同为 `is`。
MARKET_EVIDENCE_MISSING_INPUT_CASES = (
    # test_missing_benchmark_ret_60d_results_in_none
    (
        "test_missing_benchmark_ret_60d_results_in_none",
        {
            "symbol": "600519.SH",
            "factors": (_factor_result("ret_60d", 0.25),),
            "bars": (),
            "as_of": AS_OF,
            "benchmark_ret_60d": None,
        },
        None,
    ),
    # test_missing_stock_ret_60d_results_in_none
    (
        "test_missing_stock_ret_60d_results_in_none",
        {
            "symbol": "600519.SH",
            "factors": (),
            "bars": (),
            "as_of": AS_OF,
            "benchmark_ret_60d": 0.10,
        },
        None,
    ),
)


def test_missing_relative_strength_inputs_result_in_none() -> None:
    """缺基准或个股 ret_60d 时相对强弱必须是 None，绝不静默兜底。

    原 2 条「results_in_none」用例逐条成行；循环只收集，断言在表外一次完成，
    失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, payload, expected in MARKET_EVIDENCE_MISSING_INPUT_CASES:
        evidence = build_stock_market_evidence(**payload)
        if evidence.relative_strength_60d is not expected:
            wrong.append(
                f"{label}: relative_strength_60d 为 {evidence.relative_strength_60d!r}，"
                f"期望 {expected!r}"
            )
    assert not wrong, "相对强弱未对缺失输入返回 None:\n" + "\n".join(wrong)
