"""研究池阶段（配置、合格发现、发现服务）长尾用例。

本文件由 Task 12「文件合并」把以下 3 个同域小文件整体搬入：
    - tests/unit/test_universe_config.py（5 例）
    - tests/unit/test_qualified_discovery.py（6 例）
    - tests/unit/test_discovery_service.py（8 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from astock_lens.discovery import (
    QualifiedCoverage,
    QualifiedScreenItem,
    QualifiedScreenQuery,
    QualifiedScreenResult,
    StrategyCoverage,
    StrategyScreenItem,
    StrategyScreenQuery,
    StrategyScreenResult,
    screen_qualified,
    screen_strategy,
    summarize_strategies,
)
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.models import (
    QualificationContext,
    StrategyQualification,
)
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.universe.config import UniverseConfig, load_universe_config

# ===========================================================================
# 来源：tests/unit/test_universe_config.py（5 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Universe configuration loading.
#
# `configs/universe.yaml` is the only place the Universe thresholds live. These
# tests pin the two rulings this slice records: the liquidity floor came from the
# project owner (20,000,000 CNY), and the long-suspension day count is explicitly
# deferred rather than guessed.
# """
#


ROOT = Path(__file__).resolve().parents[2]


CONFIG_PATH = ROOT / "configs" / "universe.yaml"


def _load() -> UniverseConfig:
    return load_universe_config(CONFIG_PATH)


def test_repository_config_loads() -> None:
    config = _load()

    # 所有者 2026-09-18 决定：暂时只纳入沪深两市（北交所日线在现用接口上取不到）。
    assert config.exchanges == ("SSE", "SZSE")
    assert config.min_listing_days == 120


def test_liquidity_floor_carries_the_owner_supplied_value() -> None:
    """门槛是人的决定，记在配置里、不在代码里。

    2026-09-16 由所有者给定 20,000,000；2026-09-18 同一位所有者要求研究池约 2,000–3,000 只，
    实测 100M → 2,961、150M → 2,303、200M → 1,853，取中段 150,000,000。
    """
    assert _load().min_average_turnover_20d == 150_000_000.0


def test_long_suspension_is_deferred_not_defaulted() -> None:
    """The rule is switched on, but no day count has been reviewed."""
    config = _load()

    assert config.exclude_long_suspension is True
    assert config.long_suspension_days is None


def _payload_without_liquidity_floor() -> dict[str, object]:
    """第 1 行的载荷：删掉流动性门槛键（原用例语句逐字保留）。"""
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    del payload["min_average_turnover_20d"]
    return payload


def _payload_without_listing_age() -> dict[str, object]:
    """第 2 行的载荷：删掉上市天数键（原用例语句逐字保留）。"""
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    del payload["min_listing_days"]
    return payload


def _payload_with_unknown_key() -> dict[str, object]:
    """第 3 行的载荷：金额键拼错（原用例语句逐字保留）。"""
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["min_average_turnover_2d"] = 5_000_000
    return payload


# 「配置损坏必须响亮失败」三行：行序与原用例一致，label 即原测试名，
# 原 docstring 逐字保留为行注释；`expected=None` 表示该行原本不断言消息。
# 列 = label, payload, expected：
#   - `payload` 为零参可调用，返回经就地改动后的 yaml 载荷；
#   - `expected` 逐字取自原 `pytest.raises(..., match=...)` 的片段，
#     比对方式与原断言同为 `re.search`。
UNIVERSE_CONFIG_ERROR_CASES = (
    # test_a_missing_liquidity_floor_is_an_error_not_a_fallback:
    #   Deleting the key must fail loudly; there is no code default.
    (
        "test_a_missing_liquidity_floor_is_an_error_not_a_fallback",
        _payload_without_liquidity_floor,
        "min_average_turnover_20d",
    ),
    # test_a_missing_listing_age_is_an_error_not_a_fallback
    (
        "test_a_missing_listing_age_is_an_error_not_a_fallback",
        _payload_without_listing_age,
        "min_listing_days",
    ),
    # test_an_unknown_key_is_rejected:
    #   A typo in the config must not be silently ignored.
    (
        "test_an_unknown_key_is_rejected",
        _payload_with_unknown_key,
        None,
    ),
)


def test_broken_configurations_are_refused() -> None:
    """缺门槛键 / 缺上市天数键 / 多余键各自以 ValueError 拒绝。

    原 3 条「is an error / is rejected」用例逐条成行；循环只收集，
    断言在表外一次完成，失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, payload, expected in UNIVERSE_CONFIG_ERROR_CASES:
        try:
            UniverseConfig.model_validate(payload())
        except ValueError as exc:
            if expected is not None and re.search(expected, str(exc)) is None:
                wrong.append(
                    f"{label}: 错误消息中找不到 {expected!r}，实际 {str(exc)!r}"
                )
        else:
            wrong.append(f"{label}: 未抛出 ValueError")
    assert not wrong, "损坏的 universe 配置未被拒绝:\n" + "\n".join(wrong)


def test_digest_is_stable_and_content_sensitive() -> None:
    config = _load()

    assert config.digest() == _load().digest()
    assert (
        config.digest() != config.model_copy(update={"min_listing_days": 121}).digest()
    )


# ===========================================================================
# 来源：tests/unit/test_qualified_discovery.py（6 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 双门槛合格股票发现服务（screen_qualified）单元测试。
#
# 覆盖 brief 的四组行为：
#
# 1. 双门槛判定：仅 percentile 与 absolute 双通过的结果返回；
# 2. 确定性排序：rank_percentile DESC → score DESC → symbol ASC；
# 3. 覆盖度在 limit 之前对全量计算；
# 4. 零合格时 items 为空、qualified_count 为 0 且必须携带 warnings。
#
# 另按裁决补充：strategy_id 缺失 qualifier 时必须显式抛错（fail loudly），
# 不得返回「零合格」假装正常。
# """
#


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


def _qualified_strategy_result(
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
        _qualified_strategy_result("AAA", percentile=0.99),
        _qualified_strategy_result("BBB", percentile=0.98),
        _qualified_strategy_result("CCC", percentile=0.50),
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
        _qualified_strategy_result("DDD", percentile=0.95, score=70.0),
        _qualified_strategy_result("BBB", percentile=0.95, score=90.0),
        _qualified_strategy_result("AAA", percentile=0.95, score=90.0),
        _qualified_strategy_result("CCC", percentile=0.99, score=10.0),
        _qualified_strategy_result("EEE", percentile=0.95, score=None),
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
        _qualified_strategy_result("AAA", percentile=0.99),
        _qualified_strategy_result("BBB", percentile=0.98),
        _qualified_strategy_result("CCC", percentile=0.97),
        _qualified_strategy_result("DDD", percentile=0.96),
        # ineligible：只计入 eligible 统计之外，不进入判定
        _qualified_strategy_result("EEE", percentile=0.95, eligible=False),
        # 未排名：只计入覆盖度，不进入判定
        _qualified_strategy_result("FFF", percentile=None),
        # 其他策略：完全不参与
        _qualified_strategy_result("GGG", strategy_id="momentum", percentile=0.99),
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
        _qualified_strategy_result("AAA", percentile=0.99),
        _qualified_strategy_result("BBB", percentile=0.50),
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
    strategy_results = (_qualified_strategy_result("AAA", percentile=0.99),)

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


# ===========================================================================
# 来源：tests/unit/test_discovery_service.py（8 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Unit tests for the strategy discovery query layer."""
#


DISCOVERY_AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


def _strategy_result(
    symbol: str,
    *,
    strategy_id: str = "growth",
    strategy_version: str = "v1",
    score: float | None = None,
    percentile: float | None = None,
    confidence: float | None = None,
    eligible: bool = True,
    reasons: tuple[str, ...] = (),
    risks: tuple[str, ...] = (),
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        as_of=DISCOVERY_AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version=strategy_version),
        score=score,
        rank_percentile=percentile,
        confidence=confidence,
        reasons=reasons,
        risks=risks,
    )


def test_screen_strategy_orders_ranked_results_best_first() -> None:
    result = screen_strategy(
        (
            _strategy_result("BBB", percentile=0.91, score=70.0),
            _strategy_result("AAA", percentile=0.99, score=60.0),
            _strategy_result("CCC", percentile=0.95, score=80.0),
        ),
        StrategyScreenQuery(strategy_id="growth", limit=20),
    )
    assert isinstance(result, StrategyScreenResult)
    assert all(isinstance(item, StrategyScreenItem) for item in result.items)
    assert [item.symbol for item in result.items] == ["AAA", "CCC", "BBB"]
    assert [item.rank for item in result.items] == [1, 2, 3]
    assert result.strategy_id == "growth"


def test_screen_strategy_tie_breaking_order() -> None:
    # Same percentile -> higher score first; same score -> symbol ASC
    result = screen_strategy(
        (
            _strategy_result("ZZZ", percentile=0.95, score=70.0),
            _strategy_result("CCC", percentile=0.95, score=80.0),
            _strategy_result("AAA", percentile=0.95, score=80.0),
        ),
        StrategyScreenQuery(strategy_id="growth", limit=20),
    )
    assert [item.symbol for item in result.items] == ["AAA", "CCC", "ZZZ"]


def test_screen_strategy_missing_values_order_and_preservation() -> None:
    # Pin order: ranked/scored -> unranked scored -> unranked/unscored
    # Preserving None, never converting to 0.0
    r_ranked = _strategy_result("AAA", percentile=0.90, score=70.0)
    r_unranked_scored = _strategy_result("BBB", percentile=None, score=85.0)
    r_unranked_unscored = _strategy_result("CCC", percentile=None, score=None)

    result = screen_strategy(
        (r_unranked_unscored, r_ranked, r_unranked_scored),
        StrategyScreenQuery(strategy_id="growth", limit=20),
    )

    assert [item.symbol for item in result.items] == ["AAA", "BBB", "CCC"]
    # Check that None values are strictly preserved
    assert result.items[0].rank_percentile == 0.90
    assert result.items[0].score == 70.0

    assert result.items[1].rank_percentile is None
    assert result.items[1].score == 85.0

    assert result.items[2].rank_percentile is None
    assert result.items[2].score is None


def test_screen_strategy_filters() -> None:
    results = (
        _strategy_result("AAA", percentile=0.99, score=90.0, eligible=True),
        _strategy_result("BBB", percentile=0.96, score=80.0, eligible=False),
        _strategy_result("CCC", percentile=0.92, score=70.0, eligible=True),
        _strategy_result("DDD", percentile=None, score=60.0, eligible=True),
    )

    # eligible_only=True (default)
    res_eligible = screen_strategy(
        results,
        StrategyScreenQuery(strategy_id="growth"),
    )
    assert [item.symbol for item in res_eligible.items] == ["AAA", "CCC", "DDD"]

    # eligible_only=False
    res_all = screen_strategy(
        results,
        StrategyScreenQuery(strategy_id="growth", eligible_only=False),
    )
    assert [item.symbol for item in res_all.items] == ["AAA", "BBB", "CCC", "DDD"]

    # min_percentile=0.95 (filters out < 0.95 and unranked None)
    res_pct = screen_strategy(
        results,
        StrategyScreenQuery(
            strategy_id="growth", eligible_only=False, min_percentile=0.95
        ),
    )
    assert [item.symbol for item in res_pct.items] == ["AAA", "BBB"]

    # limit=2
    res_limit = screen_strategy(
        results,
        StrategyScreenQuery(strategy_id="growth", eligible_only=False, limit=2),
    )
    assert [item.symbol for item in res_limit.items] == ["AAA", "BBB"]
    assert [item.rank for item in res_limit.items] == [1, 2]


def test_screen_strategy_query_validation() -> None:
    with pytest.raises(ValueError, match="limit"):
        StrategyScreenQuery(strategy_id="growth", limit=0)

    with pytest.raises(ValueError, match="limit"):
        StrategyScreenQuery(strategy_id="growth", limit=-5)

    with pytest.raises(ValueError, match="percentile"):
        StrategyScreenQuery(strategy_id="growth", min_percentile=-0.1)

    with pytest.raises(ValueError, match="percentile"):
        StrategyScreenQuery(strategy_id="growth", min_percentile=1.01)


def test_screen_strategy_coverage_calculated_before_filters() -> None:
    results = (
        _strategy_result("AAA", percentile=0.99, score=90.0, eligible=True),
        _strategy_result("BBB", percentile=0.96, score=80.0, eligible=False),
        _strategy_result("CCC", percentile=None, score=70.0, eligible=True),
        _strategy_result("DDD", percentile=None, score=None, eligible=False),
        # Mixed strategy result that must not be counted for growth
        _strategy_result(
            "EEE", strategy_id="momentum", percentile=0.99, score=99.0, eligible=True
        ),
    )

    query = StrategyScreenQuery(
        strategy_id="growth",
        eligible_only=True,
        min_percentile=0.98,
        limit=1,
    )
    screen_res = screen_strategy(results, query)

    # Filtered and limited items
    assert [item.symbol for item in screen_res.items] == ["AAA"]

    # Coverage calculated on all 4 growth results BEFORE filters and limit
    coverage = screen_res.coverage
    assert coverage.strategy_id == "growth"
    assert coverage.total_count == 4
    assert coverage.eligible_count == 2
    assert coverage.scored_count == 3
    assert coverage.ranked_count == 2


def test_summarize_strategies() -> None:
    results = (
        _strategy_result(
            "AAA", strategy_id="value", percentile=0.9, score=80.0, eligible=True
        ),
        _strategy_result(
            "BBB", strategy_id="growth", percentile=0.95, score=90.0, eligible=True
        ),
        _strategy_result(
            "CCC", strategy_id="growth", percentile=None, score=None, eligible=False
        ),
        _strategy_result(
            "DDD", strategy_id="momentum", percentile=0.8, score=70.0, eligible=False
        ),
    )

    summaries = summarize_strategies(results)

    # Sorted alphabetically by strategy_id
    assert [s.strategy_id for s in summaries] == ["growth", "momentum", "value"]

    # Growth summary: 2 total, 1 eligible, 1 scored, 1 ranked
    assert summaries[0] == StrategyCoverage(
        strategy_id="growth",
        total_count=2,
        eligible_count=1,
        scored_count=1,
        ranked_count=1,
    )

    # Momentum summary: 1 total, 0 eligible, 1 scored, 1 ranked
    assert summaries[1] == StrategyCoverage(
        strategy_id="momentum",
        total_count=1,
        eligible_count=0,
        scored_count=1,
        ranked_count=1,
    )

    # Value summary: 1 total, 1 eligible, 1 scored, 1 ranked
    assert summaries[2] == StrategyCoverage(
        strategy_id="value",
        total_count=1,
        eligible_count=1,
        scored_count=1,
        ranked_count=1,
    )


def test_summarize_strategies_empty() -> None:
    assert summarize_strategies(()) == ()
