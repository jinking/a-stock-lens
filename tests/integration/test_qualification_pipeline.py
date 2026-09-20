"""资格管线集成测试：qualification_stage 必须读取股票完整 Factor 证据。

覆盖计划 Task 5 的四个场景：
1. Growth 资格能读到不在策略评分快照里的 ``roe_ttm``；
2. Growth 缺 ``roe_ttm`` 时失败关闭；
3. Dividend 单位回归：``dividend_paid_ratio``（单位 %）绝不参与绝对判定；
4. GARP 回归：``pe_ttm`` 参与绝对判定，``pe_percentile`` 不参与。

装配使用真实生产规则（``configs/qualifications``），以获得生产级强证据。
"""

from datetime import UTC, datetime

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines.stages import qualification_stage
from astock_lens.qualifications.registry import load_canonical_qualifiers
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)

QUALIFIERS = load_canonical_qualifiers()

SYMBOL = "600000.SH"


def _factor(
    name: str,
    value: float,
    *,
    symbol: str = SYMBOL,
    status: DataStatus = DataStatus.VALUE,
) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _strategy_result(
    *,
    strategy_id: str,
    rank_percentile: float = 0.95,
    factor_snapshot: tuple[FactorResult, ...] = (),
    symbol: str = SYMBOL,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=90.0,
        rank_percentile=rank_percentile,
        factor_snapshot=factor_snapshot,
    )


def test_growth_qualification_uses_full_factor_evidence_beyond_scoring_snapshot() -> (
    None
):
    """策略评分快照刻意不含 roe_ttm；资格必须从完整 Factor 证据读到它。"""
    growth_result = _strategy_result(
        strategy_id="growth",
        factor_snapshot=(
            _factor("revenue_yoy", 8.0),
            _factor("revenue_cagr_3y", 6.0),
            _factor("net_profit_parent_yoy", 20.0),
            _factor("net_profit_parent_cagr_3y", 12.0),
        ),
    )
    factor_results = (
        _factor("net_profit_parent_yoy", 20.0),
        _factor("revenue_yoy", 8.0),
        _factor("roe_ttm", 9.0),
    )

    qualifications = qualification_stage(
        strategy_results=(growth_result,),
        factor_results=factor_results,
        qualifiers=QUALIFIERS,
    )

    assert len(qualifications) == 1
    qualification = qualifications[0]
    assert qualification.absolute_pass is True
    assert qualification.qualified is True


def test_growth_qualification_fails_closed_when_roe_evidence_is_missing() -> None:
    growth_result = _strategy_result(
        strategy_id="growth",
        factor_snapshot=(
            _factor("revenue_yoy", 8.0),
            _factor("net_profit_parent_yoy", 20.0),
        ),
    )
    factor_results = (
        _factor("net_profit_parent_yoy", 20.0),
        _factor("revenue_yoy", 8.0),
        # 刻意缺少 roe_ttm
    )

    qualifications = qualification_stage(
        strategy_results=(growth_result,),
        factor_results=factor_results,
        qualifiers=QUALIFIERS,
    )

    qualification = qualifications[0]
    assert qualification.absolute_pass is False
    assert qualification.qualified is False
    assert any("roe_ttm" in risk for risk in qualification.risks)


def test_dividend_qualification_ignores_percent_unit_paid_ratio() -> None:
    """dividend_paid_ratio（单位 %，此处 79.0）绝不能与 0.80 比较。"""
    dividend_result = _strategy_result(
        strategy_id="dividend",
        factor_snapshot=(
            # 评分快照里故意放百分比口径的替代因子。
            _factor("dividend_paid_ratio", 79.0),
        ),
    )
    factor_results = (
        _factor("dividend_yield_ttm", 3.5),
        _factor("dividend_payout_ttm", 0.50),
    )

    qualifiers = QUALIFIERS
    assert set(qualifiers["dividend"].absolute_rule.thresholds) == {
        "dividend_yield_ttm",
        "dividend_payout_ttm",
    }
    assert "dividend_paid_ratio" not in qualifiers["dividend"].absolute_rule.thresholds

    qualifications = qualification_stage(
        strategy_results=(dividend_result,),
        factor_results=factor_results,
        qualifiers=qualifiers,
    )

    qualification = qualifications[0]
    assert qualification.qualified is True
    assert qualification.absolute_pass is True
    assert not any("dividend_paid_ratio" in risk for risk in qualification.risks)


def test_garp_qualification_uses_pe_ttm_and_not_pe_percentile() -> None:
    """pe_ttm 参与绝对判定；pe_percentile 不参与。"""
    assert set(QUALIFIERS["garp"].absolute_rule.thresholds) == {
        "pe_ttm",
        "net_profit_parent_yoy",
        "roe_ttm",
    }
    assert "pe_percentile" not in QUALIFIERS["garp"].absolute_rule.thresholds

    garp_result = _strategy_result(
        strategy_id="garp",
        factor_snapshot=(
            # 评分快照只含评分因子，刻意不含 pe_ttm / pe_percentile。
            _factor("net_profit_parent_yoy", 20.0),
            _factor("roe_ttm", 12.0),
        ),
    )
    factor_results = (
        _factor("pe_ttm", 30.0),
        _factor("net_profit_parent_yoy", 20.0),
        _factor("roe_ttm", 12.0),
    )

    qualifications = qualification_stage(
        strategy_results=(garp_result,),
        factor_results=factor_results,
        qualifiers=QUALIFIERS,
    )
    assert qualifications[0].qualified is True
    assert qualifications[0].absolute_pass is True

    # 反向：pe_ttm 触及 35 上限之上 → 绝对判定失败。
    expensive = (
        _factor("pe_ttm", 40.0),
        _factor("net_profit_parent_yoy", 20.0),
        _factor("roe_ttm", 12.0),
    )
    qualifications_fail = qualification_stage(
        strategy_results=(garp_result,),
        factor_results=expensive,
        qualifiers=QUALIFIERS,
    )
    assert qualifications_fail[0].absolute_pass is False
    assert any("pe_ttm" in risk for risk in qualifications_fail[0].risks)
