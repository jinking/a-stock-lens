"""红利策略双门槛合格发现与审计集成测试 (Plan D Task 4)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from astock_lens.discovery.qualified import (
    QualifiedScreenQuery,
    screen_qualified,
)
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.registry import load_canonical_qualifiers
from astock_lens.strategies.contracts import StrategyResult

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SHANGHAI)


def _fr(symbol: str, factor: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=AS_OF,
        status=DataStatus.VALUE,
        raw_value=value,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
    )


def _sr(symbol: str, rank_percentile: float) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id="dividend",
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        score=0.88,
        rank_percentile=rank_percentile,
        lineage=SnapshotLineage(strategy_version="v1"),
    )


def test_dividend_qualified_discovery_passes_when_factors_meet_dual_gate() -> None:
    """测试 Dividend 策略在具备真实 dividend_yield_ttm 后能够通过双门槛。"""
    # 标的 1: 工商银行 (Top 5%, 股息率 5.5%, ROE 11.2% -> 双门槛全部通过)
    # 标的 2: 某低股息股 (Top 5%, 股息率 2.1% < 3.0% -> 绝对门槛不通过)
    # 标的 3: 某低分位股 (Top 30% < Top 10%, 股息率 6.0% -> 分位数门槛不通过)
    strategy_results = (
        _sr("601398.SH", 0.95),
        _sr("000001.SZ", 0.92),
        _sr("600000.SH", 0.70),
    )

    factors = (
        _fr("601398.SH", "dividend_yield_ttm", 5.50),
        _fr("601398.SH", "dividend_payout_ttm", 0.35),
        _fr("000001.SZ", "dividend_yield_ttm", 2.10),
        _fr("000001.SZ", "dividend_payout_ttm", 0.30),
        _fr("600000.SH", "dividend_yield_ttm", 6.00),
        _fr("600000.SH", "dividend_payout_ttm", 0.40),
    )

    qualifiers = load_canonical_qualifiers()
    assert "dividend" in qualifiers

    result = screen_qualified(
        query=QualifiedScreenQuery(strategy_id="dividend", limit=10),
        strategy_results=strategy_results,
        factor_results=factors,
        qualifiers=qualifiers,
    )

    # 应该只有 601398.SH 双门槛通过
    assert result.coverage.qualified_count == 1
    assert result.coverage.strategy_eligible_count == 3
    assert result.coverage.ranked_count == 3
    assert result.coverage.percentile_pass_count == 2
    assert result.coverage.absolute_pass_count == 2
    assert len(result.items) == 1
    item = result.items[0]
    assert item.symbol == "601398.SH"
    assert item.rank_percentile == 0.95
    assert any("dividend_yield_ttm" in r for r in item.reasons)
    assert any("dividend_payout_ttm" in r for r in item.reasons)


def test_dividend_qualified_discovery_blocks_when_yield_falls_below_threshold() -> None:
    """测试当股息率不达标时，即使 percentile 在 Top 10% 依然被绝对门槛拦截并给出预警。"""
    strategy_results = (_sr("601398.SH", 0.98),)
    factors = (
        _fr("601398.SH", "dividend_yield_ttm", 2.80),  # 低于 3.0% 门槛
        _fr("601398.SH", "dividend_payout_ttm", 0.35),
    )
    qualifiers = load_canonical_qualifiers()
    result = screen_qualified(
        query=QualifiedScreenQuery(strategy_id="dividend", limit=10),
        strategy_results=strategy_results,
        factor_results=factors,
        qualifiers=qualifiers,
    )
    assert result.coverage.qualified_count == 0
    assert result.coverage.percentile_pass_count == 1
    assert result.coverage.absolute_pass_count == 0
    assert len(result.items) == 0
    assert len(result.warnings) > 0
    assert "无任何双门槛通过标的" in result.warnings[0]
