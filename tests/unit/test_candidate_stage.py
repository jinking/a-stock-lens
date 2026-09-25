"""候选阶段（构建、校准、发现、证据、政策、主策略、路由、v2 影响）长尾用例。

本文件由 Task 12「文件合并」把以下 8 个同域小文件整体搬入：
    - tests/unit/test_candidate_builder.py（8 例）
    - tests/unit/test_candidate_calibration.py（5 例）
    - tests/unit/test_candidate_discovery.py（5 例）
    - tests/unit/test_candidate_evidence.py（6 例）
    - tests/unit/test_candidate_policy.py（6 例）
    - tests/unit/test_candidate_primary_strategy.py（3 例）
    - tests/unit/test_candidate_routing.py（5 例）
    - tests/unit/test_candidate_v2_impact.py（3 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from astock_lens.calibration import (
    CALIBRATION_WARNING,
    generate_calibration_report,
    render_json,
    render_markdown,
)
from astock_lens.calibration.candidate_v2_impact import (
    CandidateV2ImpactReport,
    StrategyImpactSummary,
    compute_candidate_v2_impact,
    render_candidate_v2_impact_markdown,
)
from astock_lens.candidates import routing
from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.context import primary_qualified_strategy
from astock_lens.candidates.models import Candidate
from astock_lens.candidates.policy import (
    CandidateEvidence,
    CandidatePolicy,
    CandidatePolicyNotConfigured,
    CandidateQualification,
    CandidateSelection,
)
from astock_lens.candidates.routing import next_action_for
from astock_lens.cli.app import app
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.discovery.candidates import screen_candidates
from astock_lens.discovery.models import CandidateScreenItem, CandidateScreenResult
from astock_lens.domain.enums import (
    DataStatus,
    MarketValidation,
    NextAction,
    Signal,
    SnapshotKind,
)
from astock_lens.domain.models import DailyBar, SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines.stages import candidate_stage
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

# ===========================================================================
# 来源：tests/unit/test_candidate_builder.py（8 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Candidate builder tests.
#
# The rule these tests pin down: the builder assembles, it does not decide. The
# `next_action` is a parameter whose default is the inert `IGNORE`, and a
# candidate whose evidence disagrees with its declared lineage is refused rather
# than published with a contradictory provenance.
#


AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


BLD_LINEAGE = SnapshotLineage(factor_version="v1", strategy_version="v1")


def _strategy_result(
    *,
    strategy_version: str = "v1",
    reasons: tuple[str, ...] = (),
    risks: tuple[str, ...] = (),
) -> StrategyResult:
    return StrategyResult(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version=strategy_version,
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version=strategy_version),
        reasons=reasons,
        risks=risks,
        factor_snapshot=(
            FactorResult(
                symbol="600000.SH",
                factor="avg_amount_20d",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=1_000_000.0,
            ),
        ),
    )


def test_signal_and_market_validation_stay_unset() -> None:
    """Neither layer exists in this slice, so neither is fabricated."""
    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(), lineage=BLD_LINEAGE
    )

    assert candidate.market_validation is None
    assert candidate.signal is None


def test_lineage_mismatch_is_refused() -> None:
    result = _strategy_result(strategy_version="v2")

    with pytest.raises(ValueError, match="strategy_version"):
        CandidateBuilder().build(
            "600000.SH", as_of=AS_OF, strategy_results=(result,), lineage=BLD_LINEAGE
        )


def test_reasons_and_risks_are_aggregated_from_evidence() -> None:
    result = _strategy_result(reasons=("avg_amount_20d=1000000.0",), risks=("thin",))

    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(result,), lineage=BLD_LINEAGE
    )

    assert candidate.reasons == ("avg_amount_20d=1000000.0",)
    assert candidate.risks == ("thin",)
    assert candidate.strategy_results == (result,)


def test_candidate_is_a_research_object_not_a_recommendation() -> None:
    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(), lineage=BLD_LINEAGE
    )

    assert candidate.symbol == "600000.SH"
    assert candidate.as_of == AS_OF
    assert candidate.lineage == BLD_LINEAGE
    assert candidate.next_action in set(NextAction)


def test_candidate_lineage_carries_complete_stage_versions() -> None:
    """测试 Candidate 的 lineage 完整携带所有上游阶段版本（factor, strategy, qualification, policy, regime, market_validation, signal）。"""
    full_lineage = SnapshotLineage(
        universe_snapshot="2026-09-04:u1",
        factor_version="v1",
        strategy_version="v1",
        regime_version="v1",
        market_validation_version="v1",
        signal_version="v1",
    )
    strategy_res = _strategy_result(strategy_version="v1")
    strategy_qual = StrategyQualification(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    evidence = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(strategy_res,),
        strategy_qualifications=(strategy_qual,),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.BREAKOUT,
    )
    selection = CandidateSelection(
        symbol="600000.SH",
        policy_version="v1",
        reasons=("top candidate",),
    )
    candidate = CandidateBuilder().build(
        evidence=evidence,
        selection=selection,
        as_of=AS_OF,
        lineage=full_lineage,
    )
    assert candidate.lineage.factor_version == "v1"
    assert candidate.lineage.strategy_version == "v1"
    assert candidate.lineage.qualification_version == "v1"
    assert candidate.lineage.candidate_policy_version == "v1"
    assert candidate.lineage.regime_version == "v1"
    assert candidate.lineage.market_validation_version == "v1"
    assert candidate.lineage.signal_version == "v1"
    assert "v1" in candidate.lineage.market_validation_versions()
    assert "v1" in candidate.lineage.signal_versions()
    assert "v1" in candidate.lineage.regime_versions()


def test_candidate_builder_trend_weaken_under_approved_decision_e1() -> None:
    """根据决策 E1：TREND_WEAKEN 标的动作标记为 WATCH，并在 risks 中明确走弱风险警示。"""
    strategy_res = _strategy_result(strategy_version="v1")
    strategy_qual = StrategyQualification(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    evidence = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(strategy_res,),
        strategy_qualifications=(strategy_qual,),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.TREND_WEAKEN,
    )
    selection = CandidateSelection(
        symbol="600000.SH",
        policy_version="v1",
        reasons=("top candidate",),
    )
    candidate = CandidateBuilder().build(
        evidence=evidence,
        selection=selection,
        as_of=AS_OF,
        lineage=BLD_LINEAGE,
    )
    assert candidate.next_action == NextAction.WATCH
    assert any("TREND_WEAKEN" in r or "走弱" in r for r in candidate.risks)


def test_candidate_builder_no_signal_under_approved_decision_f1() -> None:
    """根据决策 F1：NO_SIGNAL 标的允许作为常规候选入选，默认动作标记为 WATCH。"""
    strategy_res = _strategy_result(strategy_version="v1")
    strategy_qual = StrategyQualification(
        symbol="600000.SH",
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.92,
    )
    evidence = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(strategy_res,),
        strategy_qualifications=(strategy_qual,),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    selection = CandidateSelection(
        symbol="600000.SH",
        policy_version="v1",
        reasons=("top candidate",),
    )
    candidate = CandidateBuilder().build(
        evidence=evidence,
        selection=selection,
        as_of=AS_OF,
        lineage=BLD_LINEAGE,
    )
    assert candidate.next_action == NextAction.WATCH


# ===========================================================================
# 来源：tests/unit/test_candidate_calibration.py（5 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


CALIBRATION_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


CALIBRATION_LINEAGE = SnapshotLineage(factor_version="v1", strategy_version="v1")


def _strat(
    symbol: str, strategy_id: str, percentile: float, score: float
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=CALIBRATION_AS_OF,
        eligible=True,
        lineage=CALIBRATION_LINEAGE,
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
        as_of=CALIBRATION_AS_OF,
        status=status,
        raw_value=value,
        lineage=CALIBRATION_LINEAGE,
    )


def test_empty_industry_map_raises_value_error() -> None:
    with pytest.raises(ValueError, match="industry_map"):
        generate_calibration_report(
            as_of=CALIBRATION_AS_OF,
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
        as_of=CALIBRATION_AS_OF,
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
    assert strat.boundary_rank_percentile == 0.91
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
        as_of=CALIBRATION_AS_OF,
        strategy_results=[s1, s2],
        factor_results=[f1, f2],
        industry_map=ind_map,
    )
    # Order B (reversed)
    rep_b = generate_calibration_report(
        as_of=CALIBRATION_AS_OF,
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


# --- 行业证据字段的兼容性（第一步任务 1.2）------------------------------------


def test_the_report_still_builds_without_the_new_evidence_fields() -> None:
    """既有调用方不传任何新字段也必须照常构造，默认是"未声明 + 诊断材料"。"""
    from astock_lens.calibration.candidate_report import (
        CandidateCalibrationReport,
        IndustryEvidence,
    )

    report = CandidateCalibrationReport(
        as_of=CALIBRATION_AS_OF,
        warning=CALIBRATION_WARNING,
        strategies=(),
        industry_coverage_ratio=0.0,
        unknown_industry_count=0,
    )
    assert report.unknown_industry_symbols == ()
    assert report.industry_evidence == IndustryEvidence()
    assert report.industry_evidence.origin == "unspecified"
    assert report.industry_coverage is None


def test_the_denominator_is_the_scored_population_not_the_industry_map() -> None:
    """缺口的分母是**参与计算的标的**，不是行业映射文件里的名单。

    映射里多出来的、这一轮根本没参与计算的代码，既不是缺口也不是覆盖；用映射
    名单冒充研究池会让覆盖率凭空变好看。
    """
    ind_map = {
        "600001.SH": "银行",
        "600002.SH": "电子",
        # 下面两只在映射里，但本轮没有任何因子/策略结果——不参与分母。
        "600009.SH": "医药",
        "600010.SH": "有色",
    }
    report = generate_calibration_report(
        as_of=CALIBRATION_AS_OF,
        strategy_results=[_strat("600001.SH", "value", 0.95, 95.0)],
        factor_results=[_factor("600002.SH", "peg", 1.5)],
        industry_map=ind_map,
    )
    assert report.industry_coverage is not None
    assert report.industry_coverage.total_count == 2
    assert report.industry_coverage.known_count == 2
    assert report.industry_coverage.ratio == 1.0
    assert report.unknown_industry_symbols == ()

    # 同一份映射，把一只没行业归属的标的加进参与集合，缺口立刻出现。
    widened = generate_calibration_report(
        as_of=CALIBRATION_AS_OF,
        strategy_results=[_strat("600001.SH", "value", 0.95, 95.0)],
        factor_results=[
            _factor("600002.SH", "peg", 1.5),
            _factor("600008.SH", "peg", 2.0),
        ],
        industry_map=ind_map,
    )
    assert widened.unknown_industry_symbols == ("600008.SH",)
    assert widened.industry_coverage is not None
    assert widened.industry_coverage.total_count == 3


# ===========================================================================
# 来源：tests/unit/test_candidate_discovery.py（5 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Unit tests for pure candidate discovery service.
#
# Plan: docs/superpowers/plans/2026-09-21-candidate-today-query-experience.md Task 1
# Spec: docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md
#


DISCOVERY_AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


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
            as_of=DISCOVERY_AS_OF,
        )
        for s_id, pct in qualified_strategies
    )
    s_results = tuple(
        StrategyResult(
            symbol=symbol,
            strategy_id=s_id,
            strategy_version="v1",
            as_of=DISCOVERY_AS_OF,
            eligible=True,
            score=88.0,
            rank_percentile=pct,
            lineage=SnapshotLineage(strategy_version="v1"),
        )
        for s_id, pct in qualified_strategies
    )
    return Candidate(
        symbol=symbol,
        as_of=DISCOVERY_AS_OF,
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
    result = screen_candidates([c2, c1, c3], as_of=DISCOVERY_AS_OF)
    assert isinstance(result, CandidateScreenResult)
    assert result.as_of == DISCOVERY_AS_OF
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
    result = screen_candidates([c], as_of=DISCOVERY_AS_OF)
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
    result = screen_candidates([c], as_of=DISCOVERY_AS_OF)
    item = result.items[0]
    assert item.signal == Signal.TREND_WEAKEN
    assert item.next_action == NextAction.WATCH
    assert item.risks == ("技术信号提示走弱风险 (TREND_WEAKEN)",)


def test_screen_candidates_respects_limit_and_tracks_total_count() -> None:
    candidates = [_make_candidate(f"60000{i}.SH") for i in range(10)]
    result = screen_candidates(candidates, as_of=DISCOVERY_AS_OF, limit=3)
    assert result.total_count == 10
    assert len(result.items) == 3
    assert [item.rank for item in result.items] == [1, 2, 3]


def test_screen_candidates_empty_records() -> None:
    result = screen_candidates([], as_of=DISCOVERY_AS_OF)
    assert result.total_count == 0
    assert result.items == ()


# ===========================================================================
# 来源：tests/unit/test_candidate_evidence.py（6 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


EVIDENCE_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _qualification(
    symbol: str,
    strategy_id: str = "value",
    *,
    qualified: bool = True,
    percentile: float = 0.95,
    version: str = "qual-v1",
) -> StrategyQualification:
    return StrategyQualification(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version=version,
        qualified=qualified,
        percentile_pass=percentile >= 0.90,
        absolute_pass=qualified,
        rank_percentile=percentile,
    )


def _result(
    symbol: str,
    strategy_id: str = "value",
    score: float = 80.0,
    percentile: float = 0.95,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=EVIDENCE_AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
        rank_percentile=percentile,
    )


def test_candidate_evidence_valid_construction() -> None:
    ev = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(_result("600000.SH"),),
        strategy_qualifications=(_qualification("600000.SH"),),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    assert ev.symbol == "600000.SH"
    assert len(ev.strategy_results) == 1
    assert len(ev.strategy_qualifications) == 1
    assert ev.market_validation == MarketValidation.CONFIRMED
    assert ev.signal == Signal.NO_SIGNAL


# 「非法构造必须被拒」三行：行序与原用例一致，label 即原测试名；
# 列 = label, payload, expected：
#   - `payload` 逐行保留原 `CandidateEvidence(...)` 的关键字参数；
#   - `expected` 逐字取自原 `pytest.raises(..., match=...)` 的消息片段，
#     比对方式与原断言同为 `re.search`。
CANDIDATE_EVIDENCE_REJECTION_CASES = (
    # test_candidate_evidence_rejects_mismatched_result_symbol
    (
        "test_candidate_evidence_rejects_mismatched_result_symbol",
        {
            "symbol": "600000.SH",
            "strategy_results": (_result("600001.SH"),),
            "strategy_qualifications": (_qualification("600000.SH"),),
            "market_validation": MarketValidation.CONFIRMED,
            "signal": Signal.NO_SIGNAL,
        },
        "symbol",
    ),
    # test_candidate_evidence_rejects_mismatched_qualification_symbol
    (
        "test_candidate_evidence_rejects_mismatched_qualification_symbol",
        {
            "symbol": "600000.SH",
            "strategy_results": (_result("600000.SH"),),
            "strategy_qualifications": (_qualification("600001.SH"),),
            "market_validation": MarketValidation.CONFIRMED,
            "signal": Signal.NO_SIGNAL,
        },
        "symbol",
    ),
    # test_candidate_evidence_requires_at_least_one_qualified_qualification
    (
        "test_candidate_evidence_requires_at_least_one_qualified_qualification",
        {
            "symbol": "600000.SH",
            "strategy_results": (_result("600000.SH"),),
            "strategy_qualifications": (_qualification("600000.SH", qualified=False),),
            "market_validation": MarketValidation.CONFIRMED,
            "signal": Signal.NO_SIGNAL,
        },
        "qualified",
    ),
)


def test_candidate_evidence_rejects_invalid_constructions() -> None:
    """三种非法构造各自以 ValueError 拒绝，消息须匹配原 `match=` 片段。

    原 3 条「rejects / requires」用例逐条成行；循环只收集，断言在表外一次完成，
    失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, payload, expected in CANDIDATE_EVIDENCE_REJECTION_CASES:
        try:
            CandidateEvidence(**payload)
        except ValueError as exc:
            if re.search(expected, str(exc)) is None:
                wrong.append(
                    f"{label}: 错误消息中找不到 {expected!r}，实际 {str(exc)!r}"
                )
        else:
            wrong.append(f"{label}: 未抛出 ValueError")
    assert not wrong, "CandidateEvidence 未拒绝非法构造:\n" + "\n".join(wrong)


def test_candidate_evidence_allows_none_for_market_and_signal_representation() -> None:
    ev = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(_result("600000.SH"),),
        strategy_qualifications=(_qualification("600000.SH"),),
        market_validation=None,
        signal=None,
    )
    assert ev.market_validation is None
    assert ev.signal is None


def test_candidate_selection_immutability_and_fields() -> None:
    sel = CandidateSelection(
        symbol="600000.SH",
        policy_version="v1",
        reasons=("value top 5%",),
    )
    assert sel.symbol == "600000.SH"
    assert sel.policy_version == "v1"
    assert sel.reasons == ("value top 5%",)
    with pytest.raises(ValidationError):
        sel.symbol = "600001.SH"  # type: ignore[misc]


def test_candidate_builder_assembles_from_selection_and_evidence() -> None:
    sym = "600000.SH"
    res_val = _result(sym, strategy_id="value", percentile=0.98)
    res_gro = _result(sym, strategy_id="growth", percentile=0.85)  # not qualified
    q_val = _qualification(
        sym, strategy_id="value", qualified=True, percentile=0.98, version="qual-val-1"
    )
    q_gro = _qualification(
        sym,
        strategy_id="growth",
        qualified=False,
        percentile=0.85,
        version="qual-gro-1",
    )

    ev = CandidateEvidence(
        symbol=sym,
        strategy_results=(res_val, res_gro),
        strategy_qualifications=(q_val, q_gro),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    sel = CandidateSelection(
        symbol=sym,
        policy_version="policy-v1",
        reasons=("selected by representative policy",),
    )
    lineage = SnapshotLineage(
        universe_snapshot="2026-09-04:abc",
        factor_version="f1",
        strategy_version="v1",
    )

    candidate = CandidateBuilder().build(
        evidence=ev,
        selection=sel,
        as_of=EVIDENCE_AS_OF,
        lineage=lineage,
    )

    assert candidate.symbol == sym
    assert candidate.next_action is NextAction.WATCH
    assert candidate.candidate_policy_version == "policy-v1"
    assert candidate.market_validation == MarketValidation.CONFIRMED
    assert candidate.signal == Signal.NO_SIGNAL
    # Only retains qualified strategy results and qualifications
    assert len(candidate.strategy_results) == 1
    assert candidate.strategy_results[0].strategy_id == "value"
    assert len(candidate.strategy_qualifications) == 1
    assert candidate.strategy_qualifications[0].strategy_id == "value"
    # Lineage carries qualification_version and candidate_policy_version
    assert candidate.lineage.qualification_version == "qual-val-1"
    assert candidate.lineage.candidate_policy_version == "policy-v1"


def test_candidate_builder_rejects_symbol_mismatch() -> None:
    ev = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(_result("600000.SH"),),
        strategy_qualifications=(_qualification("600000.SH"),),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    sel = CandidateSelection(symbol="600001.SH", policy_version="v1")
    with pytest.raises(ValueError, match="Symbol mismatch"):
        CandidateBuilder().build(
            evidence=ev,
            selection=sel,
            as_of=EVIDENCE_AS_OF,
            lineage=SnapshotLineage(),
        )


# ===========================================================================
# 来源：tests/unit/test_candidate_policy.py（6 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 候选资格判定必须是显式策略，不能从分数推出来。
#
# 边界规则：
# * 没有批准的 policy 时，Candidate 阶段明确报错，而不是安静地返回空集；
# * policy 说入选，才有 Candidate；policy 说不入选，分数再高也没有 Candidate；
# * Builder 不参与资格判定，它只组装证据。
#


POLICY_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


LINEAGE = SnapshotLineage(universe_snapshot="2026-09-04:abc", strategy_version="v1")


def _policy_result(
    *,
    eligible: bool = True,
    score: float | None = 88.0,
    symbol: str = "600000.SH",
    percentile: float = 0.95,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id="momentum",
        strategy_version="v1",
        as_of=POLICY_AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
        rank_percentile=percentile,
    )


def _policy_qualification(
    symbol: str = "600000.SH",
    strategy_id: str = "momentum",
    qualified: bool = True,
    percentile: float = 0.95,
) -> StrategyQualification:
    return StrategyQualification(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version="v1",
        qualified=qualified,
        percentile_pass=percentile >= 0.90,
        absolute_pass=qualified,
        rank_percentile=percentile,
    )


class _ApprovesNothing:
    """一个策略的示例：它什么都不批准。"""

    version = "test-nothing"

    def select(
        self, evidence: Sequence[CandidateEvidence]
    ) -> tuple[CandidateSelection, ...]:
        return ()

    def qualify(
        self,
        *,
        strategy_results: tuple[StrategyResult, ...],
        market_validation: object | None,
        signal: object | None,
    ) -> CandidateQualification:
        del strategy_results, market_validation, signal
        return CandidateQualification(qualified=False, reasons=("no approved rule",))


class _ApprovesEverything:
    """只用于证明"资格来自 policy 的判定"，它不是任何被批准的业务规则。"""

    version = "test-everything"

    def select(
        self, evidence: Sequence[CandidateEvidence]
    ) -> tuple[CandidateSelection, ...]:
        return tuple(
            CandidateSelection(
                symbol=e.symbol,
                policy_version=self.version,
                reasons=("policy said so",),
            )
            for e in evidence
        )

    def qualify(
        self,
        *,
        strategy_results: tuple[StrategyResult, ...],
        market_validation: object | None,
        signal: object | None,
    ) -> CandidateQualification:
        del market_validation, signal
        return CandidateQualification(
            qualified=bool(strategy_results), reasons=("policy said so",)
        )


def test_cross_sectional_policy_protocol_conformance() -> None:
    policy: CandidatePolicy = _ApprovesEverything()
    ev = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(_policy_result(),),
        strategy_qualifications=(_policy_qualification(),),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    selected = policy.select([ev])
    assert len(selected) == 1
    assert selected[0].symbol == "600000.SH"
    assert selected[0].policy_version == "test-everything"


def test_no_reviewed_policy_is_an_error_not_an_empty_scan() -> None:
    """没有批准的规则时，Candidate 阶段必须明确报错。

    安静地返回空集会让"还没决定"和"今天没有标的入选"长得一模一样。
    """
    with pytest.raises(CandidatePolicyNotConfigured):
        candidate_stage(
            strategy_results=(_policy_result(),),
            lineage=LINEAGE,
            as_of=POLICY_AS_OF,
            policy=None,
        )


def test_the_policy_is_what_makes_a_candidate() -> None:
    candidates = candidate_stage(
        strategy_results=(_policy_result(score=12.0),),
        qualifications=(_policy_qualification(qualified=True),),
        market_validation_by_symbol={"600000.SH": MarketValidation.CONFIRMED},
        signal_by_symbol={"600000.SH": Signal.NO_SIGNAL},
        lineage=LINEAGE,
        as_of=POLICY_AS_OF,
        policy=_ApprovesEverything(),
    )

    assert len(candidates) == 1
    assert candidates[0].symbol == "600000.SH"
    assert candidates[0].next_action is NextAction.WATCH


def test_score_does_not_override_a_rejecting_policy() -> None:
    """分数再高也不能覆盖 policy 的拒绝判定。"""
    candidates = candidate_stage(
        strategy_results=(_policy_result(score=100.0),),
        lineage=LINEAGE,
        as_of=POLICY_AS_OF,
        policy=_ApprovesNothing(),
    )

    assert candidates == ()


# 两行是「Builder 缺省即惰性 IGNORE、绝不自行推导 next_action」同一断言的参数枚举：
# 无策略结果（默认值）/ 有 100 分的结果（分数不是决定）。
NEXT_ACTION_INERT_DEFAULT_CASES: tuple[
    tuple[str, datetime, tuple[StrategyResult, ...], SnapshotLineage], ...
] = (
    (
        "test_next_action_defaults_to_the_inert_choice",
        AS_OF,
        (),
        BLD_LINEAGE,
    ),
    (
        "test_the_builder_does_not_derive_next_action_from_a_score",
        POLICY_AS_OF,
        (_policy_result(score=100.0),),
        LINEAGE,
    ),
)


def test_the_builder_leaves_next_action_at_the_inert_default() -> None:
    wrong = []
    for label, as_of, strategy_results, lineage in NEXT_ACTION_INERT_DEFAULT_CASES:
        candidate = CandidateBuilder().build(
            "600000.SH", as_of=as_of, strategy_results=strategy_results, lineage=lineage
        )
        if candidate.next_action is not NextAction.IGNORE:
            wrong.append(
                f"{label}: next_action 得到 {candidate.next_action!r}，期望 IGNORE"
            )
    assert not wrong, "builder 不得自行推导 next_action:\n" + "\n".join(wrong)


def test_a_policy_verdict_is_ineligible_without_eligible_evidence() -> None:
    """没有资格成立的结果时，policy 不会被问到"要不要入选"。"""
    candidates = candidate_stage(
        strategy_results=(_policy_result(eligible=False, score=99.0),),
        lineage=LINEAGE,
        as_of=POLICY_AS_OF,
        policy=_ApprovesEverything(),
    )

    assert candidates == ()


# ===========================================================================
# 来源：tests/unit/test_candidate_primary_strategy.py（3 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Unit tests for deterministic primary qualified strategy context.
#
# Spec: docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md
# Plan: docs/superpowers/plans/2026-09-21-candidate-correctness-safety-gate.md Task 2
#


PRIMARY_STRATEGY_AS_OF = datetime(2026, 9, 21, 15, 0, tzinfo=UTC)


def _qual(
    strategy_id: str, percentile: float, is_qualified: bool
) -> StrategyQualification:
    return StrategyQualification(
        symbol="600000.SH",
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version="v1",
        as_of=PRIMARY_STRATEGY_AS_OF,
        rank_percentile=percentile,
        rank=1,
        total_evaluable=100,
        percentile_pass=percentile >= 0.90,
        absolute_pass=is_qualified,
        qualified=is_qualified,
    )


# 「合格策略的决胜规则」三行：行序与原用例一致，label 即原测试名，
# 原 docstring 逐字保留为行注释。
# 列 = label, quals, expected：
#   - `quals` 逐行保留原 `_qual(...)` 列表；
#   - `expected` 即原 `primary_qualified_strategy(quals) == "<策略 id>"` 的字面量，
#     比对方式同为 `==`。
PRIMARY_STRATEGY_CASES = (
    # test_highest_qualified_percentile_wins:
    #   Step 1: 最高百分位的合格策略获胜。
    (
        "test_highest_qualified_percentile_wins",
        [
            _qual("value", 0.92, True),
            _qual("growth", 0.95, True),
        ],
        "growth",
    ),
    # test_equal_percentile_resolves_by_strategy_id_ascending:
    #   Step 2: 百分位相同按 strategy_id 字母升序决胜。
    (
        "test_equal_percentile_resolves_by_strategy_id_ascending",
        [
            _qual("value", 0.95, True),
            _qual("growth", 0.95, True),
            _qual("garp", 0.95, True),
        ],
        "garp",
    ),
    # test_unqualified_strategy_never_wins_even_with_higher_percentile:
    #   Step 3: 未合格策略即使百分位更高也绝不获胜。
    (
        "test_unqualified_strategy_never_wins_even_with_higher_percentile",
        [
            _qual("momentum", 0.99, False),
            _qual("value", 0.91, True),
        ],
        "value",
    ),
)


def test_primary_qualified_strategy_selection_rules() -> None:
    """三个决胜步骤各自选出预期策略 id。

    原 3 条「Step 1/2/3」用例逐条成行；循环只收集，断言在表外一次完成，
    失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, quals, expected in PRIMARY_STRATEGY_CASES:
        selected = primary_qualified_strategy(quals)
        if selected != expected:
            wrong.append(f"{label}: 选出 {selected!r}，期望 {expected!r}")
    assert not wrong, "primary 策略选择不符合决胜规则:\n" + "\n".join(wrong)


def test_no_qualified_strategy_raises_explicit_value_error() -> None:
    """Step 4: 无任何合格策略时抛出明确的 ValueError。"""
    unqualified = [
        _qual("momentum", 0.85, False),
        _qual("growth", 0.70, False),
    ]
    with pytest.raises(ValueError, match="no qualified strategy"):
        primary_qualified_strategy(unqualified)

    with pytest.raises(ValueError, match="no qualified strategy"):
        primary_qualified_strategy([])


def test_candidate_model_carries_primary_strategy_id() -> None:
    """Step 6: Candidate 模型持久化 primary_strategy_id 字段。"""
    candidate = Candidate(
        symbol="600000.SH",
        as_of=PRIMARY_STRATEGY_AS_OF,
        next_action=NextAction.WATCH,
        lineage=SnapshotLineage(candidate_policy_version="v1"),
        primary_strategy_id="growth",
    )
    assert candidate.primary_strategy_id == "growth"
    dumped = candidate.model_dump(mode="json")
    assert dumped["primary_strategy_id"] == "growth"


# ===========================================================================
# 来源：tests/unit/test_candidate_routing.py（5 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 入选判定到候选动作的翻译。
#
# 这里只做最后一步映射：被批准的 Candidate Policy 说"入选"，候选动作才是
# `WATCH`；说"不入选"，就是 `IGNORE`。动作**不再**由分数推出来——旧规则
# 「有分数就 WATCH」已经在 Task 7 被删除，本文件同时钉住它不许回来。
#
# `DEEP_RESEARCH` 与 `TRACK_SIGNAL` 需要 Signal 层，而该层至今没有实现，所以
# 它们依然不可达：猜一个触发条件等于替项目所有者做产品决定。
#


ROUTING_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _routing_result(*, eligible: bool, score: float | None) -> StrategyResult:
    return StrategyResult(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version="v1",
        as_of=ROUTING_AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
    )


def test_a_qualified_verdict_routes_to_watch() -> None:
    qualification = CandidateQualification(qualified=True, reasons=("policy",))

    assert next_action_for(qualification) is NextAction.WATCH


def test_an_unqualified_verdict_routes_to_ignore() -> None:
    qualification = CandidateQualification(qualified=False, reasons=("policy",))

    assert next_action_for(qualification) is NextAction.IGNORE


def test_only_two_of_the_four_actions_are_reachable() -> None:
    """另外两个动作需要 Signal 层，这一阶段没有建它。"""
    reached = {
        next_action_for(CandidateQualification(qualified=True)),
        next_action_for(CandidateQualification(qualified=False)),
    }

    assert reached == {NextAction.WATCH, NextAction.IGNORE}


def test_the_routed_action_reaches_a_candidate() -> None:
    result = _routing_result(eligible=True, score=87.5)

    candidate = CandidateBuilder().build(
        "600000.SH",
        as_of=ROUTING_AS_OF,
        strategy_results=(result,),
        lineage=SnapshotLineage(strategy_version="v1"),
        next_action=next_action_for(CandidateQualification(qualified=True)),
    )

    assert candidate.next_action is NextAction.WATCH
    assert candidate.strategy_results == (result,)


def test_score_routing_api_is_absent() -> None:
    """路由模块不提供基于分数决定候选动作的 API。"""
    assert not hasattr(routing, "route_next_action")
    assert not hasattr(routing, "route_candidate_actions")


# ===========================================================================
# 来源：tests/unit/test_candidate_v2_impact.py（3 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Candidate-v2 market evidence impact audit unit tests.
#
# Auditable impact report tests:
# - Explicit denominator and counts per primary strategy;
# - Accurate tracking of complete 5D evidence vs missing industry/benchmark/volume;
# - Deterministic counts of BREAKDOWN, TREND_WEAKEN, NO_SIGNAL;
# - Markdown output formatting and strict read-only guarantee.
#


V2_IMPACT_AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def _v2_impact_factor(
    symbol: str, factor: str, value: float | None, status: DataStatus = DataStatus.VALUE
) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=V2_IMPACT_AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _v2_impact_qual(
    symbol: str, strategy_id: str = "momentum", rank: float = 0.95
) -> StrategyQualification:
    return StrategyQualification(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version="v1",
        as_of=V2_IMPACT_AS_OF,
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=rank,
        reasons=(),
        lineage=SnapshotLineage(strategy_version="v1"),
    )


def _bar(symbol: str, count: int) -> tuple[DailyBar, ...]:
    return tuple(
        DailyBar(
            symbol=symbol,
            trade_date=V2_IMPACT_AS_OF.date(),
            open=10.0,
            high=10.5,
            low=9.5,
            close=10.0,
            volume=1000.0,
        )
        for _ in range(count)
    )


def test_compute_candidate_v2_impact_explicit_counts() -> None:
    # 构造标的：
    # s1: 完整5D, BREAKOUT (prox=0.96)
    # s2: 缺 volume_ratio (<20 bars), BREAKDOWN (ret_20d=-0.20)
    # s3: 缺 industry, TREND_WEAKEN (ret_60d=0.20, ret_20d=-0.08)
    quals = (
        _v2_impact_qual("s1", "momentum", 0.99),
        _v2_impact_qual("s2", "momentum", 0.98),
        _v2_impact_qual("s3", "momentum", 0.97),
    )
    factors = (
        _v2_impact_factor("s1", "ret_20d", 0.10),
        _v2_impact_factor("s1", "ret_60d", 0.15),
        _v2_impact_factor("s1", "proximity_52w_high", 0.96),
        _v2_impact_factor("s2", "ret_20d", -0.20),
        _v2_impact_factor("s2", "ret_60d", -0.10),
        _v2_impact_factor("s2", "proximity_52w_high", 0.70),
        _v2_impact_factor("s3", "ret_20d", -0.08),
        _v2_impact_factor("s3", "ret_60d", 0.20),
        _v2_impact_factor("s3", "proximity_52w_high", 0.88),
    )
    # s1 有 20 根 bar，s2 只有 5 根 bar，s3 有 20 根 bar
    bars = _bar("s1", 20) + _bar("s2", 5) + _bar("s3", 20)
    industry_mapped = {"s1", "s2"}  # s3 缺行业
    benchmark_available = True  # 基准具备

    report = compute_candidate_v2_impact(
        qualifications=quals,
        factors=factors,
        bars=bars,
        industry_mapped_symbols=industry_mapped,
        benchmark_available=benchmark_available,
        as_of=V2_IMPACT_AS_OF,
    )

    assert isinstance(report, CandidateV2ImpactReport)
    assert len(report.summaries) == 1
    summary = report.summaries[0]
    assert summary.strategy_id == "momentum"
    assert summary.qualified_count == 3
    assert summary.missing_volume_ratio_count == 1  # s2
    assert summary.missing_industry_count == 1  # s3
    assert summary.missing_benchmark_count == 0  # 基准可用
    assert summary.complete_5d_evidence_count == 1  # 仅 s1 完整
    assert summary.candidate_v1_count == 3
    assert summary.breakdown_count == 1  # s2
    assert summary.trend_weaken_count == 1  # s3
    assert summary.no_signal_count == 0  # s1 为 BREAKOUT


def test_candidate_v2_impact_markdown_render() -> None:
    report = CandidateV2ImpactReport(
        as_of=V2_IMPACT_AS_OF,
        summaries=(
            StrategyImpactSummary(
                strategy_id="momentum",
                qualified_count=100,
                complete_5d_evidence_count=85,
                missing_industry_count=5,
                missing_benchmark_count=0,
                missing_volume_ratio_count=10,
                candidate_v1_count=100,
                breakdown_count=4,
                trend_weaken_count=6,
                no_signal_count=12,
            ),
        ),
    )

    md = render_candidate_v2_impact_markdown(report)
    assert "Candidate v2 市场证据与技术信号影响审计报告" in md
    assert "momentum" in md
    assert "100" in md
    assert "85" in md
    assert "BREAKDOWN" in md


def test_candidate_v2_impact_cli_execution_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_root = tmp_path / "snapshots"
    store = JsonSnapshotStore(snapshot_root)

    # 注入基础 FACTOR 和 STRATEGY
    store.write(
        SnapshotKind.FACTOR,
        V2_IMPACT_AS_OF,
        [
            FactorResult(
                symbol="600519.SH",
                factor="ret_20d",
                as_of=V2_IMPACT_AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=0.10,
            )
        ],
    )
    store.write(
        SnapshotKind.STRATEGY,
        V2_IMPACT_AS_OF,
        [
            StrategyResult(
                symbol="600519.SH",
                strategy_id="momentum",
                as_of=V2_IMPACT_AS_OF,
                score=80.0,
                rank_percentile=0.95,
                eligible=True,
                strategy_version="v1",
                lineage=SnapshotLineage(strategy_version="v1"),
            )
        ],
    )

    # 记录 snapshot 目录运行前的 sha256 指纹
    def _fingerprint(path: Path) -> dict[str, str]:
        return {
            str(f.relative_to(path)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in path.rglob("*")
            if f.is_file()
        }

    before_fp = _fingerprint(snapshot_root)

    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snapshot_root))
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "candidate-v2-impact",
            "--as-of",
            "2026-09-20",
            "--output-dir",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    # 产物落盘
    assert (out_dir / "candidate-v2-impact-2026-09-20.json").is_file()
    assert (out_dir / "candidate-v2-impact-2026-09-20.md").is_file()

    # 核心只读红线：快照目录绝未发生任何改写
    after_fp = _fingerprint(snapshot_root)
    assert before_fp == after_fp
