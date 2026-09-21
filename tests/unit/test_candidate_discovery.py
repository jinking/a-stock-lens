"""Unit tests for pure candidate discovery service.

Plan: docs/superpowers/plans/2026-09-21-candidate-today-query-experience.md Task 1
Spec: docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md
"""

from datetime import UTC, datetime

from astock_lens.candidates.models import Candidate
from astock_lens.discovery.candidates import screen_candidates
from astock_lens.discovery.models import CandidateScreenItem, CandidateScreenResult
from astock_lens.domain.enums import MarketValidation, NextAction, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


def _make_candidate(
    symbol: str,
    *,
    primary_strategy_id: str = "momentum",
    qualified_strategies: tuple[tuple[str, float], ...] = (("momentum", 0.95),),
    market_validation: MarketValidation | None = MarketValidation.CONFIRMED,
    signal: Signal | None = Signal.BREAKOUT,
    next_action: NextAction = NextAction.WATCH,
    risks: tuple[str, ...] = (),
) -> Candidate:
    quals = tuple(
        StrategyQualification(
            symbol=symbol,
            strategy_id=s_id,
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=pct,
            as_of=AS_OF,
        )
        for s_id, pct in qualified_strategies
    )
    s_results = tuple(
        StrategyResult(
            symbol=symbol,
            strategy_id=s_id,
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            score=88.0,
            rank_percentile=pct,
            lineage=SnapshotLineage(strategy_version="v1"),
        )
        for s_id, pct in qualified_strategies
    )
    return Candidate(
        symbol=symbol,
        as_of=AS_OF,
        next_action=next_action,
        lineage=SnapshotLineage(
            strategy_version="v1",
            qualification_version="v1",
            candidate_policy_version="v1",
            regime_version="v1",
            market_validation_version="v1",
            signal_version="v1",
            universe_snapshot="2026-09-19:u1",
        ),
        primary_strategy_id=primary_strategy_id,
        strategy_qualifications=quals,
        strategy_results=s_results,
        market_validation=market_validation,
        signal=signal,
        reasons=(f"qualified for {primary_strategy_id}",),
        risks=risks,
    )


def test_screen_candidates_preserves_stored_authoritative_order() -> None:
    c1 = _make_candidate("000001.SZ", primary_strategy_id="momentum")
    c2 = _make_candidate("600519.SH", primary_strategy_id="quality")
    c3 = _make_candidate("300750.SZ", primary_strategy_id="growth")

    # 存储中的 Candidate 顺序即权威顺序，不重新打分排序
    result = screen_candidates([c2, c1, c3], as_of=AS_OF)
    assert isinstance(result, CandidateScreenResult)
    assert result.as_of == AS_OF
    assert result.total_count == 3
    assert isinstance(result.items[0], CandidateScreenItem)
    assert [item.symbol for item in result.items] == [
        "600519.SH",
        "000001.SZ",
        "300750.SZ",
    ]
    assert [item.rank for item in result.items] == [1, 2, 3]


def test_screen_candidates_extracts_primary_and_all_qualified_strategies() -> None:
    c = _make_candidate(
        "601336.SH",
        primary_strategy_id="value",
        qualified_strategies=(("value", 0.98), ("garp", 0.92)),
    )
    result = screen_candidates([c], as_of=AS_OF)
    item = result.items[0]
    assert item.symbol == "601336.SH"
    assert item.primary_strategy_id == "value"
    assert item.qualified_strategy_ids == ("value", "garp")
    assert item.best_rank_percentile == 0.98


def test_screen_candidates_keeps_signal_risks_visible() -> None:
    c = _make_candidate(
        "688617.SH",
        primary_strategy_id="growth",
        signal=Signal.TREND_WEAKEN,
        next_action=NextAction.WATCH,
        risks=("技术信号提示走弱风险 (TREND_WEAKEN)",),
    )
    result = screen_candidates([c], as_of=AS_OF)
    item = result.items[0]
    assert item.signal == Signal.TREND_WEAKEN
    assert item.next_action == NextAction.WATCH
    assert item.risks == ("技术信号提示走弱风险 (TREND_WEAKEN)",)


def test_screen_candidates_respects_limit_and_tracks_total_count() -> None:
    candidates = [_make_candidate(f"60000{i}.SH") for i in range(10)]
    result = screen_candidates(candidates, as_of=AS_OF, limit=3)
    assert result.total_count == 10
    assert len(result.items) == 3
    assert [item.rank for item in result.items] == [1, 2, 3]


def test_screen_candidates_empty_records() -> None:
    result = screen_candidates([], as_of=AS_OF)
    assert result.total_count == 0
    assert result.items == ()
