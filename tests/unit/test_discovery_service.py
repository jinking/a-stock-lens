"""Unit tests for the strategy discovery query layer."""

from datetime import UTC, datetime

import pytest

from astock_lens.discovery import (
    StrategyCoverage,
    StrategyScreenItem,
    StrategyScreenQuery,
    StrategyScreenResult,
    screen_strategy,
    summarize_strategies,
)
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


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
        as_of=AS_OF,
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
