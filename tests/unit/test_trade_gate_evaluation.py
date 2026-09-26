"""Trade Gate 评估链（上下文、引擎、评分、否决、存储、指标、回放、服务）长尾用例。

本文件由 Task 12「文件合并」把以下 9 个同域小文件整体搬入：
    - tests/unit/test_trade_gate_context.py（3 例）
    - tests/unit/test_trade_gate_engine.py（2 例）
    - tests/unit/test_trade_gate_scoring.py（3 例）
    - tests/unit/test_trade_gate_veto.py（3 例）
    - tests/unit/test_trade_gate_store.py（2 例）
    - tests/unit/test_trade_gate_duckdb_store.py（2 例）
    - tests/unit/test_trade_gate_metrics.py（1 例）
    - tests/unit/test_trade_gate_replay.py（1 例）
    - tests/unit/test_trade_gate_service.py（1 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from datetime import UTC, datetime

import pytest

from astock_lens.domain.enums import (
    MarketValidation,
    Signal,
    SnapshotKind,
    TradeDecision,
    TradeProfile,
    VetoSeverity,
)
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.trade_gate.context import (
    TradeContextBuilder,
    TradeGateSnapshotNotPublishedError,
)
from astock_lens.trade_gate.duckdb_store import DuckDBTradeLedgerStore
from astock_lens.trade_gate.engine import TradeGateEngine
from astock_lens.trade_gate.metrics import summarize_trade_discipline
from astock_lens.trade_gate.models import (
    DimensionJudgement,
    DimensionScore,
    ExecutionRecord,
    IndependentAssessment,
    ThesisAuditResult,
    TradeContext,
    TradeGateEvaluation,
    TradeIntent,
    TradeMarketOverlay,
    TradeReview,
    TradeRiskProposal,
)
from astock_lens.trade_gate.profiles import (
    StrategyProfileConfig,
    load_trade_gate_profiles,
)
from astock_lens.trade_gate.replay import replay_evaluation
from astock_lens.trade_gate.scoring import score_event, score_position, score_swing
from astock_lens.trade_gate.service import TradeGateService
from astock_lens.trade_gate.store import JsonTradeLedgerStore, TradeLedgerConflictError
from astock_lens.trade_gate.veto import evaluate_vetoes

# ===========================================================================
# 来源：tests/unit/test_trade_gate_context.py（3 例）
# ===========================================================================


CTX_NOW = datetime(2026, 9, 22, tzinfo=UTC)


class Store:
    def __init__(self, candidate=()) -> None:
        self.candidate = candidate

    def read(self, kind, as_of):
        return self.candidate if kind is SnapshotKind.CANDIDATE else ()

    def dates(self, kind):
        return (CTX_NOW.date().isoformat(),) if kind is SnapshotKind.CANDIDATE else ()


def test_eod_snapshot_does_not_invent_intraday_facts() -> None:
    context = TradeContextBuilder(Store()).build(symbol="603991.SH", as_of=CTX_NOW)
    assert context.overlay is None
    assert context.stock_return_1d is None
    assert context.sector_return_1d is None
    assert context.confirmation_met is None
    assert context.candidate_status == "not_selected"


def test_overlay_facts_are_explicitly_carried() -> None:
    overlay = TradeMarketOverlay(
        captured_at=CTX_NOW,
        stock_return_1d=0.01,
        sector_return_1d=0.02,
        confirmation_met=True,
    )
    context = TradeContextBuilder(Store()).build(
        symbol="603991.SH", as_of=CTX_NOW, overlay=overlay
    )
    assert context.stock_return_1d == 0.01
    assert context.confirmation_met is True


def test_missing_all_snapshots_is_distinguished() -> None:
    class EmptyStore(Store):
        def dates(self, kind):
            return ()

    try:
        TradeContextBuilder(EmptyStore()).build(symbol="603991.SH", as_of=CTX_NOW)
    except TradeGateSnapshotNotPublishedError:
        pass
    else:
        raise AssertionError("missing snapshot should be explicit")


# ===========================================================================
# 来源：tests/unit/test_trade_gate_engine.py（2 例）
# ===========================================================================


NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _engine_intent(profile: TradeProfile) -> TradeIntent:
    return TradeIntent(
        id="intent-1",
        symbol="000001.SZ",
        action="ENTRY",
        profile=profile,
        thesis="a thesis",
        expected_holding_days=5,
        created_at=NOW,
        risk=TradeRiskProposal(
            account_nav=100000,
            planned_entry_price=10,
            stop_loss_price=9,
            target_price=12,
            quantity=100,
            invalidation_rule="跌破9",
        ),
    )


def test_event_without_intraday_evidence_waits() -> None:
    engine = TradeGateEngine(load_trade_gate_profiles())
    judgement = tuple(
        DimensionJudgement(
            name=name,
            score_ratio=0.95,
            confidence=0.95,
            evidence=("evidence",),
            summary="summary",
        )
        for name in ("catalyst_quality", "expectation_gap", "directness")
    )
    audit = ThesisAuditResult(dimensions=judgement)
    independent = IndependentAssessment(summary="assessment", dimensions=())
    context = TradeContext(symbol="000001.SZ", as_of=NOW, candidate_status="published")
    result = engine.evaluate(
        intent=_engine_intent(TradeProfile.EVENT),
        context=context,
        independent=independent,
        audit=audit,
        fomo_score=1,
    )
    assert result.decision is TradeDecision.WAIT
    assert "stock_return_1d" in result.missing_data
    assert result.reentry_triggers


def test_hard_veto_overrides_high_weighted_score() -> None:
    engine = TradeGateEngine(load_trade_gate_profiles())
    names = ("industry_trend", "competitiveness", "risk_resilience")
    judgement = tuple(
        DimensionJudgement(
            name=name,
            score_ratio=1,
            confidence=1,
            evidence=("evidence",),
            summary="summary",
        )
        for name in names
    )
    audit = ThesisAuditResult(dimensions=judgement)
    independent = IndependentAssessment(summary="assessment", dimensions=())
    context = TradeContext(
        symbol="000001.SZ",
        as_of=NOW,
        candidate_status="published",
        market_validation=MarketValidation.CONTRADICTED,
        ret_60d=0.2,
        strategy_results=tuple(
            StrategyResult(
                symbol="000001.SZ",
                strategy_id=name,
                strategy_version="v1",
                as_of=NOW,
                eligible=True,
                rank_percentile=1.0,
                lineage=SnapshotLineage(),
            )
            for name in ("quality", "growth", "value")
        ),
    )
    result = engine.evaluate(
        intent=_engine_intent(TradeProfile.POSITION),
        context=context,
        independent=independent,
        audit=audit,
        fomo_score=1,
    )
    assert result.weighted_score >= 80
    assert result.decision is TradeDecision.NO_TRADE
    assert "UPSTREAM_MARKET_CONTRADICTED" in {v.code for v in result.vetoes}


# ===========================================================================
# 来源：tests/unit/test_trade_gate_scoring.py（3 例）
# ===========================================================================


SCORING_NOW = datetime(2026, 9, 22, 9, tzinfo=UTC)


def _intent(profile: TradeProfile, target: float | None = 115) -> TradeIntent:
    return TradeIntent(
        id="i",
        symbol="000001.SZ",
        action="ENTRY",
        profile=profile,
        thesis="thesis",
        expected_holding_days=5,
        created_at=SCORING_NOW,
        risk=TradeRiskProposal(
            account_nav=100000,
            planned_entry_price=100,
            stop_loss_price=90,
            target_price=target,
            quantity=100,
            invalidation_rule="跌破90",
        ),
    )


def _judgement(name: str, ratio: float) -> DimensionJudgement:
    return DimensionJudgement(
        name=name,
        score_ratio=ratio,
        confidence=1,
        evidence=("source",),
        summary="audited",
    )


def test_event_sector_and_relative_strength_mapping() -> None:
    profiles = load_trade_gate_profiles()
    audit = ThesisAuditResult(
        dimensions=tuple(
            _judgement(n, 1)
            for n in ("catalyst_quality", "expectation_gap", "directness")
        )
    )
    context = TradeContext(
        symbol="000001.SZ",
        as_of=SCORING_NOW,
        candidate_status="published",
        stock_return_1d=0.015,
        sector_return_1d=0.03,
        benchmark_return_1d=0.005,
        confirmation_met=True,
    )
    scores = score_event(
        intent=_intent(TradeProfile.EVENT),
        context=context,
        audit=audit,
        independent=IndependentAssessment(summary="ok", dimensions=()),
        profile=profiles[TradeProfile.EVENT],
    )
    values = {s.dimension: s.score for s in scores}
    assert values["sector_strength"] == 15
    assert values["relative_strength"] == pytest.approx(7.5)
    assert values["price_confirmation"] == 10


def test_swing_rr_is_reward_risk_transform() -> None:
    profiles = load_trade_gate_profiles()
    context = TradeContext(
        symbol="000001.SZ",
        as_of=SCORING_NOW,
        candidate_status="published",
        ret_20d=0.1,
        ret_60d=0.2,
        confirmation_met=True,
        volume_ratio_5_20=0.8,
        relative_strength_60d=0.1,
    )
    values = {
        s.dimension: s.score
        for s in score_swing(
            intent=_intent(TradeProfile.SWING),
            context=context,
            profile=profiles[TradeProfile.SWING],
        )
    }
    assert values["risk_reward"] == pytest.approx(10 * (1.5 / 2.5))
    assert values["volume_confirmation"] == 8


def test_position_reuses_strategy_percentiles() -> None:
    profiles = load_trade_gate_profiles()
    strategies = tuple(
        StrategyResult(
            symbol="000001.SZ",
            strategy_id=name,
            strategy_version="v1",
            as_of=SCORING_NOW,
            eligible=True,
            rank_percentile=value,
            lineage=SnapshotLineage(),
        )
        for name, value in (
            ("quality", 0.88),
            ("growth", 0.90),
            ("garp", 0.85),
            ("value", 0.75),
        )
    )
    context = TradeContext(
        symbol="000001.SZ",
        as_of=SCORING_NOW,
        candidate_status="published",
        strategy_results=strategies,
        ret_60d=0.12,
    )
    audit = ThesisAuditResult(
        dimensions=tuple(
            _judgement(n, 0.8)
            for n in ("industry_trend", "competitiveness", "risk_resilience")
        )
    )
    values = {
        s.dimension: s.score
        for s in score_position(
            intent=_intent(TradeProfile.POSITION),
            context=context,
            audit=audit,
            profile=profiles[TradeProfile.POSITION],
        )
    }
    assert values["financial_quality"] == pytest.approx(13.2)
    assert values["earnings_growth"] == pytest.approx(13.5)
    assert values["valuation"] == pytest.approx(12.75)
    assert values["long_term_trend"] == 5


# ===========================================================================
# 来源：tests/unit/test_trade_gate_veto.py（3 例）
# ===========================================================================


def test_vetoes_include_upstream_hard_blocks_and_missing_confirmation() -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    intent = TradeIntent(
        id="i",
        symbol="000001.SZ",
        action="ENTRY",
        profile=TradeProfile.EVENT,
        thesis="thesis",
        expected_holding_days=2,
        created_at=now,
        risk=TradeRiskProposal(
            account_nav=10000,
            planned_entry_price=10,
            stop_loss_price=9,
            quantity=100,
            invalidation_rule="跌破9",
        ),
    )
    context = TradeContext(
        symbol=intent.symbol,
        as_of=now,
        candidate_status="published",
        market_validation=MarketValidation.CONTRADICTED,
        signal=Signal.BREAKDOWN,
        confirmation_met=False,
        stock_return_1d=-0.01,
        sector_return_1d=0.02,
    )
    vetoes = evaluate_vetoes(
        intent=intent,
        context=context,
        profile=load_trade_gate_profiles()[TradeProfile.EVENT],
        audit=ThesisAuditResult(dimensions=()),
        fomo_score=2,
    )
    by_code = {v.code: v for v in vetoes}
    assert by_code["UPSTREAM_MARKET_CONTRADICTED"].severity is VetoSeverity.HARD
    assert by_code["UPSTREAM_BREAKDOWN"].severity is VetoSeverity.HARD
    assert "NO_PRICE_CONFIRMATION" in by_code
    assert "RELATIVE_WEAKNESS" in by_code


def test_losing_add_without_independent_confirmation_is_hard_veto() -> None:
    from astock_lens.domain.enums import TradeAction
    from astock_lens.trade_gate.models import ExistingPositionSnapshot

    now = datetime(2026, 9, 22, tzinfo=UTC)
    intent = TradeIntent(
        id="add",
        symbol="000001.SZ",
        action=TradeAction.ADD,
        profile=TradeProfile.POSITION,
        thesis="thesis",
        expected_holding_days=10,
        created_at=now,
        existing_position=ExistingPositionSnapshot(
            quantity=100, avg_cost=12, current_price=10, captured_at=now
        ),
        risk=TradeRiskProposal(
            account_nav=10000,
            planned_entry_price=10,
            stop_loss_price=9,
            quantity=100,
            invalidation_rule="跌破9",
        ),
    )
    vetoes = evaluate_vetoes(
        intent=intent,
        context=TradeContext(
            symbol=intent.symbol, as_of=now, candidate_status="published"
        ),
        profile=load_trade_gate_profiles()[TradeProfile.POSITION],
        audit=ThesisAuditResult(dimensions=()),
        fomo_score=1,
    )
    hit = next(item for item in vetoes if item.code == "AVERAGING_DOWN_WITHOUT_SIGNAL")
    assert hit.severity is VetoSeverity.HARD


def test_absent_invalidation_is_recorded_as_hard_veto() -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    intent = TradeIntent(
        id="i",
        symbol="000001.SZ",
        action="ENTRY",
        profile=TradeProfile.POSITION,
        thesis="thesis",
        expected_holding_days=2,
        created_at=now,
        risk=TradeRiskProposal(
            account_nav=10000, planned_entry_price=10, stop_loss_price=9, quantity=100
        ),
    )
    vetoes = evaluate_vetoes(
        intent=intent,
        context=TradeContext(
            symbol=intent.symbol, as_of=now, candidate_status="published"
        ),
        profile=load_trade_gate_profiles()[TradeProfile.POSITION],
        audit=ThesisAuditResult(dimensions=()),
        fomo_score=1,
    )
    assert (
        next(v for v in vetoes if v.code == "NO_INVALIDATION").severity
        is VetoSeverity.HARD
    )


# ===========================================================================
# 来源：tests/unit/test_trade_gate_store.py（2 例）
# ===========================================================================


STORE_NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _store_intent() -> TradeIntent:
    return TradeIntent(
        id="intent-1",
        symbol="000001.SZ",
        action="ENTRY",
        profile=TradeProfile.POSITION,
        thesis="test",
        expected_holding_days=5,
        created_at=STORE_NOW,
        risk=TradeRiskProposal(
            account_nav=10000,
            planned_entry_price=10,
            stop_loss_price=9,
            quantity=10,
            invalidation_rule="跌破9",
        ),
    )


def _evaluation(identifier: str) -> TradeGateEvaluation:
    return TradeGateEvaluation(
        id=identifier,
        intent_id="intent-1",
        profile=TradeProfile.POSITION,
        profile_version="v1",
        dimension_scores=(),
        weighted_score=0,
        decision=TradeDecision.NO_TRADE,
        context=TradeContext(
            symbol="000001.SZ", as_of=STORE_NOW, candidate_status="not_selected"
        ),
        independent_assessment=IndependentAssessment(summary="none", dimensions=()),
        thesis_audit=ThesisAuditResult(dimensions=()),
        evaluated_at=STORE_NOW,
    )


def test_same_day_multiple_evaluations_are_append_only(tmp_path) -> None:
    store = JsonTradeLedgerStore(tmp_path)
    store.write_intent(_store_intent())
    first, second = _evaluation("eval-1"), _evaluation("eval-2")
    store.write_evaluation(first)
    store.write_evaluation(second)
    assert [item.id for item in store.evaluations_for_intent("intent-1")] == [
        "eval-1",
        "eval-2",
    ]
    assert store.read_intent("intent-1") == _store_intent()


def test_same_id_is_idempotent_only_for_identical_content(tmp_path) -> None:
    store = JsonTradeLedgerStore(tmp_path)
    record = _store_intent()
    store.write_intent(record)
    store.write_intent(record)
    changed = record.model_copy(update={"thesis": "different"})
    try:
        store.write_intent(changed)
    except TradeLedgerConflictError:
        pass
    else:
        raise AssertionError(
            "different content must not overwrite an append-only record"
        )


# ===========================================================================
# 来源：tests/unit/test_trade_gate_duckdb_store.py（2 例）
# ===========================================================================


def test_duckdb_store_round_trips_intent_and_read_does_not_create(tmp_path) -> None:
    pytest.importorskip("duckdb")
    database = tmp_path / "ledger.duckdb"
    store = DuckDBTradeLedgerStore(database)
    assert store.read_intent("missing") is None
    assert not database.exists()
    intent = TradeIntent(
        id="intent",
        symbol="000001.SZ",
        action="ENTRY",
        profile=TradeProfile.EVENT,
        thesis="thesis",
        expected_holding_days=2,
        created_at=datetime(2026, 9, 22, tzinfo=UTC),
        risk=TradeRiskProposal(
            account_nav=1000,
            planned_entry_price=10,
            stop_loss_price=9,
            quantity=1,
            invalidation_rule="跌破9",
        ),
    )
    store.write_intent(intent)
    assert store.read_intent("intent") == intent


def test_duckdb_reads_missing_trade_table_as_empty(tmp_path) -> None:
    duckdb = pytest.importorskip("duckdb")
    database = tmp_path / "shared.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("CREATE TABLE unrelated (id INTEGER)")
    connection.close()
    store = DuckDBTradeLedgerStore(database)
    assert store.read_intent("missing") is None
    assert store.evaluations_for_intent("missing") == ()


# ===========================================================================
# 来源：tests/unit/test_trade_gate_metrics.py（1 例）
# ===========================================================================


def test_metrics_report_override_rate_and_group_results() -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    executions = tuple(
        ExecutionRecord(
            id=f"e{i}",
            evaluation_id=f"v{i}",
            avg_fill_price=10,
            filled_quantity=1,
            filled_at=now,
            discipline_status=state,
        )
        for i, state in enumerate(("PASS", "OVERRIDDEN"))
    )
    reviews = tuple(
        TradeReview(
            id=f"r{i}",
            execution_id=f"e{i}",
            pnl_amount=pnl,
            pnl_pct=pnl,
            max_drawdown=0,
            max_adverse_excursion=0,
            max_favorable_excursion=0,
            thesis_correct=True,
            gate_correct=True,
            discipline_followed=True,
            lessons_learned="review",
            reviewed_at=now,
        )
        for i, pnl in enumerate((0.1, -0.1))
    )
    result = summarize_trade_discipline(executions, reviews)
    assert result.override_rate == 0.5
    assert result.pass_group.win_rate == 1
    assert result.overridden_group.win_rate == 0


# ===========================================================================
# 来源：tests/unit/test_trade_gate_replay.py（1 例）
# ===========================================================================


def test_replay_uses_stored_context_and_assigns_new_versions() -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    original = TradeGateEvaluation(
        id="old",
        intent_id="intent",
        profile=TradeProfile.POSITION,
        profile_version="v1",
        dimension_scores=(),
        weighted_score=0,
        decision=TradeDecision.NO_TRADE,
        context=TradeContext(symbol="000001.SZ", as_of=now, candidate_status="stored"),
        independent_assessment=IndependentAssessment(summary="stored", dimensions=()),
        thesis_audit=ThesisAuditResult(dimensions=()),
        evaluated_at=now,
    )
    profile = StrategyProfileConfig(
        id=TradeProfile.POSITION,
        version="v2",
        pass_threshold=80,
        wait_threshold=70,
        weights={"x": 100},
        fomo_wait_threshold=8,
    )
    replay = replay_evaluation(original, profile=profile)
    assert replay.id != original.id
    assert replay.replayed_from_evaluation_id == "old"
    assert replay.profile_version == "v2"


# ===========================================================================
# 来源：tests/unit/test_trade_gate_service.py（1 例）
# ===========================================================================


SERVICE_NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _seed_evaluation(store: JsonTradeLedgerStore) -> TradeGateEvaluation:
    evaluation = TradeGateEvaluation(
        id="eval-1",
        intent_id="intent-1",
        profile=TradeProfile.EVENT,
        profile_version="v1",
        dimension_scores=(
            DimensionScore(
                dimension="seed", weight=60, ratio=1, score=60, source="RULE"
            ),
        ),
        weighted_score=60,
        decision=TradeDecision.NO_TRADE,
        context=TradeContext(
            symbol="000001.SZ", as_of=SERVICE_NOW, candidate_status="published"
        ),
        independent_assessment=IndependentAssessment(summary="x", dimensions=()),
        thesis_audit=ThesisAuditResult(dimensions=()),
        evaluated_at=SERVICE_NOW,
        proposed_position_pct=0.1,
    )
    store.write_evaluation(evaluation)
    return evaluation


def _service(store: JsonTradeLedgerStore) -> TradeGateService:
    return TradeGateService(
        store=store, context_builder=None, audit_adapter=None, engine=None
    )  # type: ignore[arg-type]


def test_override_requires_smaller_size_evidence_ack_and_stop(tmp_path) -> None:
    store = JsonTradeLedgerStore(tmp_path)
    _seed_evaluation(store)
    service = _service(store)
    with pytest.raises(ValueError, match="smaller"):
        service.override(
            "eval-1",
            reason="new evidence",
            evidence=("e",),
            fomo_score=2,
            manual_position_limit_pct=0.1,
            manual_stop_rule="跌破9",
            ack_risk=True,
        )
    with pytest.raises(ValueError, match="acknowledgement"):
        service.override(
            "eval-1",
            reason="new evidence",
            evidence=("e",),
            fomo_score=2,
            manual_position_limit_pct=0.05,
            manual_stop_rule="跌破9",
            ack_risk=False,
        )
    with pytest.raises(ValueError, match="stop rule"):
        service.override(
            "eval-1",
            reason="new evidence",
            evidence=("e",),
            fomo_score=2,
            manual_position_limit_pct=0.05,
            manual_stop_rule="",
            ack_risk=True,
        )
    record = service.override(
        "eval-1",
        reason="new evidence",
        evidence=("e",),
        fomo_score=2,
        manual_position_limit_pct=0.05,
        manual_stop_rule="跌破9",
        ack_risk=True,
    )
    with pytest.raises(ValueError, match="override"):
        service.record_execution(
            evaluation_id="eval-1",
            fill_price=10,
            quantity=100,
            filled_at=SERVICE_NOW,
            override_id="unknown",
        )
    execution = service.record_execution(
        evaluation_id="eval-1",
        fill_price=10,
        quantity=100,
        filled_at=SERVICE_NOW,
        override_id=record.id,
    )
    assert execution.discipline_status == "OVERRIDDEN"
