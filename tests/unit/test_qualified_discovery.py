"""双门槛合格股票发现服务（screen_qualified）单元测试。

覆盖 brief 的四组行为：

1. 双门槛判定：仅 percentile 与 absolute 双通过的结果返回；
2. 确定性排序：rank_percentile DESC → score DESC → symbol ASC；
3. 覆盖度在 limit 之前对全量计算；
4. 零合格时 items 为空、qualified_count 为 0 且必须携带 warnings。

另按裁决补充：strategy_id 缺失 qualifier 时必须显式抛错（fail loudly），
不得返回「零合格」假装正常。
"""

from datetime import UTC, datetime

import pytest

from astock_lens.discovery import (
    QualifiedCoverage,
    QualifiedScreenItem,
    QualifiedScreenQuery,
    QualifiedScreenResult,
    screen_qualified,
)
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.models import (
    QualificationContext,
    StrategyQualification,
)
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)

STRATEGY_ID = "growth"
QUALIFICATION_VERSION = "qual-v1"


class _FakeQualifier:
    """测试专用 qualifier：按 symbol 配置 (percentile_pass, absolute_pass)。

    同时记录收到的每个 QualificationContext，供断言因子索引传递是否正确。
    """

    strategy_id = STRATEGY_ID
    qualification_version = QUALIFICATION_VERSION

    def __init__(self, verdicts: dict[str, tuple[bool, bool]]) -> None:
        self._verdicts = verdicts
        self.seen_contexts: list[QualificationContext] = []

    def qualify(self, context: QualificationContext) -> StrategyQualification:
        self.seen_contexts.append(context)
        result = context.strategy_result
        percentile_pass, absolute_pass = self._verdicts[result.symbol]
        assert result.rank_percentile is not None
        return StrategyQualification(
            symbol=result.symbol,
            strategy_id=result.strategy_id,
            strategy_version=result.strategy_version,
            qualification_version=self.qualification_version,
            qualified=percentile_pass and absolute_pass,
            percentile_pass=percentile_pass,
            absolute_pass=absolute_pass,
            rank_percentile=result.rank_percentile,
            reasons=(f"percentile={percentile_pass}", f"absolute={absolute_pass}"),
            risks=(),
        )


def _strategy_result(
    symbol: str,
    *,
    strategy_id: str = STRATEGY_ID,
    strategy_version: str = "v1",
    score: float | None = 80.0,
    percentile: float | None = 0.95,
    eligible: bool = True,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        as_of=AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version=strategy_version),
        score=score,
        rank_percentile=percentile,
    )


def _factor(symbol: str, name: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def test_screen_qualified_returns_only_dual_pass() -> None:
    """AAA 双通过、BBB 仅 percentile 通过、CCC 仅 absolute 通过：只返回 AAA。"""
    qualifier = _FakeQualifier(
        {
            "AAA": (True, True),
            "BBB": (True, False),
            "CCC": (False, True),
        }
    )
    factor_results = (
        _factor("AAA", "roe_ttm", 12.0),
        _factor("BBB", "roe_ttm", 3.0),
        _factor("CCC", "roe_ttm", 15.0),
    )
    strategy_results = (
        _strategy_result("AAA", percentile=0.99),
        _strategy_result("BBB", percentile=0.98),
        _strategy_result("CCC", percentile=0.50),
    )

    result = screen_qualified(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers={STRATEGY_ID: qualifier},
        query=QualifiedScreenQuery(strategy_id=STRATEGY_ID),
    )

    assert isinstance(result, QualifiedScreenResult)
    assert [item.symbol for item in result.items] == ["AAA"]
    item = result.items[0]
    assert isinstance(item, QualifiedScreenItem)
    assert item.rank == 1
    assert item.strategy_id == STRATEGY_ID
    assert item.strategy_version == "v1"
    assert item.qualification_version == QUALIFICATION_VERSION
    assert item.rank_percentile == 0.99
    assert item.score == 80.0

    # 覆盖度：3 条全部 eligible 且 ranked；双通过仅 1 条
    assert result.coverage == QualifiedCoverage(
        strategy_id=STRATEGY_ID,
        strategy_eligible_count=3,
        ranked_count=3,
        percentile_pass_count=2,
        absolute_pass_count=2,
        qualified_count=1,
    )
    assert result.warnings == ()

    # qualifier 收到的是 factor_results 索引出的完整因子集合（按 symbol 分组）
    factors_by_symbol = {
        ctx.strategy_result.symbol: tuple(f.factor for f in ctx.factors)
        for ctx in qualifier.seen_contexts
    }
    assert factors_by_symbol == {
        "AAA": ("roe_ttm",),
        "BBB": ("roe_ttm",),
        "CCC": ("roe_ttm",),
    }


def test_screen_qualified_deterministic_order() -> None:
    """排序：rank_percentile DESC → score DESC → symbol ASC。"""
    qualifier = _FakeQualifier(
        {
            "DDD": (True, True),  # percentile 0.95, score 70.0
            "BBB": (True, True),  # percentile 0.95, score 90.0
            # 与 BBB 同 percentile 同 score，symbol 靠前
            "AAA": (True, True),
            "CCC": (True, True),  # percentile 0.99, score 10.0（percentile 最高）
            "EEE": (True, True),  # percentile 0.95, score None（排在有 score 之后）
        }
    )
    strategy_results = (
        _strategy_result("DDD", percentile=0.95, score=70.0),
        _strategy_result("BBB", percentile=0.95, score=90.0),
        _strategy_result("AAA", percentile=0.95, score=90.0),
        _strategy_result("CCC", percentile=0.99, score=10.0),
        _strategy_result("EEE", percentile=0.95, score=None),
    )

    result = screen_qualified(
        factor_results=(),
        strategy_results=strategy_results,
        qualifiers={STRATEGY_ID: qualifier},
        query=QualifiedScreenQuery(strategy_id=STRATEGY_ID),
    )

    assert [item.symbol for item in result.items] == [
        "CCC",
        "AAA",
        "BBB",
        "DDD",
        "EEE",
    ]
    assert [item.rank for item in result.items] == [1, 2, 3, 4, 5]
    # score 为 None 时保持 None，绝不静默变成 0
    assert result.items[-1].score is None


def test_screen_qualified_coverage_before_limit() -> None:
    """limit=1 不得改变对全量计算的覆盖度计数。"""
    qualifier = _FakeQualifier(
        {
            "AAA": (True, True),
            "BBB": (True, True),
            "CCC": (True, False),
            "DDD": (False, True),
        }
    )
    strategy_results = (
        _strategy_result("AAA", percentile=0.99),
        _strategy_result("BBB", percentile=0.98),
        _strategy_result("CCC", percentile=0.97),
        _strategy_result("DDD", percentile=0.96),
        # ineligible：只计入 eligible 统计之外，不进入判定
        _strategy_result("EEE", percentile=0.95, eligible=False),
        # 未排名：只计入覆盖度，不进入判定
        _strategy_result("FFF", percentile=None),
        # 其他策略：完全不参与
        _strategy_result("GGG", strategy_id="momentum", percentile=0.99),
    )

    result = screen_qualified(
        factor_results=(),
        strategy_results=strategy_results,
        qualifiers={STRATEGY_ID: qualifier},
        query=QualifiedScreenQuery(strategy_id=STRATEGY_ID, limit=1),
    )

    # limit 生效：只保留 1 条
    assert [item.symbol for item in result.items] == ["AAA"]
    assert [item.rank for item in result.items] == [1]

    # 覆盖度基于该 strategy_id 的全量结果（6 条 growth），在 limit 之前计算
    assert result.coverage == QualifiedCoverage(
        strategy_id=STRATEGY_ID,
        strategy_eligible_count=5,
        ranked_count=5,
        percentile_pass_count=3,
        absolute_pass_count=3,
        qualified_count=2,
    )

    # ineligible 与未排名的结果不进入 qualifier
    judged_symbols = {ctx.strategy_result.symbol for ctx in qualifier.seen_contexts}
    assert judged_symbols == {"AAA", "BBB", "CCC", "DDD"}


def test_screen_qualified_zero_qualified_warns() -> None:
    """零合格：items 为空、qualified_count 为 0、warnings 非空且确定。"""
    qualifier = _FakeQualifier({"AAA": (True, False), "BBB": (False, True)})
    strategy_results = (
        _strategy_result("AAA", percentile=0.99),
        _strategy_result("BBB", percentile=0.50),
    )

    result = screen_qualified(
        factor_results=(),
        strategy_results=strategy_results,
        qualifiers={STRATEGY_ID: qualifier},
        query=QualifiedScreenQuery(strategy_id=STRATEGY_ID),
    )

    assert result.items == ()
    assert result.coverage.qualified_count == 0
    assert result.warnings
    # 确定性：同输入同输出
    again = screen_qualified(
        factor_results=(),
        strategy_results=strategy_results,
        qualifiers={STRATEGY_ID: qualifier},
        query=QualifiedScreenQuery(strategy_id=STRATEGY_ID),
    )
    assert again.warnings == result.warnings
    # 数据健康提示，不得含推荐语义
    for warning in result.warnings:
        assert "推荐" not in warning
        assert "买入" not in warning
        assert "Candidate" not in warning


def test_screen_qualified_missing_qualifier_fails_loudly() -> None:
    """qualifiers 缺少该 strategy_id 时必须抛错，不得假装零合格。"""
    strategy_results = (_strategy_result("AAA", percentile=0.99),)

    with pytest.raises(KeyError):
        screen_qualified(
            factor_results=(),
            strategy_results=strategy_results,
            qualifiers={},
            query=QualifiedScreenQuery(strategy_id=STRATEGY_ID),
        )


def test_qualified_screen_query_rejects_non_positive_limit() -> None:
    """limit 必须为正数。"""
    with pytest.raises(ValueError, match="limit"):
        QualifiedScreenQuery(strategy_id=STRATEGY_ID, limit=0)
    with pytest.raises(ValueError, match="limit"):
        QualifiedScreenQuery(strategy_id=STRATEGY_ID, limit=-1)
