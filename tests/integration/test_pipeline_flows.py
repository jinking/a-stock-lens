"""集成层 pipeline / workflow 流程长尾用例。

本文件由 Task 12「文件合并」把以下 15 个同域小文件整体搬入：
    - tests/integration/test_analysis_pipeline.py（9 例）
    - tests/integration/test_candidate_correctness_gate.py（6 例）
    - tests/integration/test_candidate_qualification_pipeline.py（5 例）
    - tests/integration/test_daily_candidate_pipeline.py（1 例）
    - tests/integration/test_daily_production_evidence.py（4 例）
    - tests/integration/test_dividend_factor_pipeline.py（1 例）
    - tests/integration/test_dividend_qualified_discovery.py（2 例）
    - tests/integration/test_financial_pipeline.py（7 例）
    - tests/integration/test_market_regime_snapshot.py（5 例）
    - tests/integration/test_market_signal_pipeline.py（1 例）
    - tests/integration/test_post_valuation_analysis_flow.py（2 例）
    - tests/integration/test_qualification_pipeline.py（4 例）
    - tests/integration/test_research_universe_flow.py（8 例）
    - tests/integration/test_stock_discovery_workflow.py（3 例）
    - tests/integration/test_valuation_pipeline.py（6 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

import csv
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from artifacts.validator import validate_snapshot
from fastapi.testclient import TestClient
from typer.testing import CliRunner, Result

from astock_lens.api.app import create_app
from astock_lens.candidates.models import Candidate
from astock_lens.candidates.policy import RepresentativeCandidatePolicy
from astock_lens.cli.app import _production_industry_map, _run_daily, app
from astock_lens.data.benchmark import BENCHMARK_BARS_ENV, read_benchmark_bars
from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    ChunkSyncResult,
    bootstrap_liquidity_history,
    land_bar_chunks,
)
from astock_lens.data.bootstrap_checkpoint import BootstrapCheckpoint
from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.data.providers.neodata import PAYLOAD_COLUMNS
from astock_lens.data.snapshots.store import JsonSnapshotStore, SnapshotConflictError
from astock_lens.data.sync import land_neodata_blocks, read_raw_rows
from astock_lens.discovery import StrategyScreenQuery, screen_strategy
from astock_lens.discovery.qualified import QualifiedScreenQuery, screen_qualified
from astock_lens.domain.enums import (
    DataStatus,
    JobStage,
    MarketRegime,
    MarketValidation,
    NextAction,
    Signal,
    SnapshotKind,
)
from astock_lens.domain.models import DailyBar, SnapshotLineage
from astock_lens.factors.builtin import build_factor
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.factors.contracts import FactorContext, FactorResult
from astock_lens.jobs.models import JobStatus
from astock_lens.jobs.store import JsonJobStore
from astock_lens.market.regime import MarketRegimeResult
from astock_lens.pipelines import analysis, stages
from astock_lens.pipelines.analysis import (
    AnalysisState,
    FactorState,
    compute_factor_state,
    compute_research_universe,
    run_analysis,
    run_research_analysis,
)
from astock_lens.pipelines.daily import (
    DailyRunResult,
    _blocked_reasons,
    _Context,
    run_daily,
)
from astock_lens.pipelines.stages import (
    candidate_stage,
    factor_stage,
    market_regime_stage,
    market_validation_stage,
    normalize_stage,
    qualification_stage,
    signal_stage,
)
from astock_lens.qualifications.models import (
    AbsoluteQualificationVerdict,
    QualificationContext,
    StrategyQualification,
)
from astock_lens.qualifications.registry import (
    build_qualifiers,
    load_canonical_qualifiers,
)
from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.registry import (
    RegisteredStrategy,
    build_scanner,
    load_scanners,
)
from astock_lens.universe.config import UniverseConfig, load_universe_config
from astock_lens.universe.models import (
    UniverseExclusion,
    UniverseRule,
    UniverseSnapshot,
)

# ===========================================================================
# 来源：tests/integration/test_analysis_pipeline.py（9 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 唯一分析执行链的端到端测试。
#
# 一个调用贯穿设计命名的业务链路：
#
#     NORMALIZE → COMPUTE_FACTORS → BUILD_UNIVERSE → RUN_STRATEGIES
#
# 关于夹具：`daily_bars_long.csv` 的每只证券都为了观察一条 Universe 规则而存在
# （见 `scripts/generate_fixtures.py`），价格按 close = base × (1 + rate)^i 生成，
# 所以 ret_20d 与 ret_60d 严格按 `rate` 排序，proximity_52w_high 等于
# (1 + rate)^5 / 1.2（有尖顶的标的）或 1 / 1.01（000006.SZ，尖顶比例是 1.0）。
# 等权混合保持该顺序，只有 000006.SZ 因 proximity 升到第三。下面这些期望值是按
# 夹具公式手算的，不是把实现跑一遍抄回来的。
#
# 本文件同时替代已经退休的 first slice / daily scan 两个入口的测试：那两条链路
# 各有一套组装逻辑，正是本阶段要消灭的"同一个项目里有两个真相"。
#


ANALYSIS_ROOT = Path(__file__).resolve().parents[2]


CSV_ROOT = ANALYSIS_ROOT / "tests" / "fixtures" / "csv"


ANALYSIS_CONFIGS = ANALYSIS_ROOT / "configs"


ANALYSIS_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


ANALYSIS_LONG_DATASET = "daily_bars_long"


EXPECTED_RANKING = (
    "300750.SZ",
    "600000.SH",
    "000006.SZ",
    "600519.SH",
    "900948.SH",
    "000001.SZ",
)


EXPECTED_EXCLUSIONS: dict[str, tuple[UniverseRule, ...]] = {
    "000002.SZ": (UniverseRule.ST,),
    "000003.SZ": (UniverseRule.DELISTING_BOARD,),
    "000004.SZ": (UniverseRule.SHORT_LISTING,),
    "000005.SZ": (UniverseRule.LOW_LIQUIDITY,),
    "000007.SZ": (UniverseRule.NO_MARKET_DATA, UniverseRule.NO_LIQUIDITY_MEASURE),
}


LIQUIDITY_FACTOR_CONFIG = ANALYSIS_CONFIGS / "factors" / "avg_amount_20d.yaml"


def _analysis_factor_configs() -> tuple[object, ...]:
    return tuple(
        load_factor_config(path)
        for path in sorted((ANALYSIS_CONFIGS / "factors").glob("*.yaml"))
    )


def _momentum() -> StrategyConfig:
    return load_strategy_config(ANALYSIS_CONFIGS / "strategies" / "momentum.yaml")


def _momentum_scanner() -> RegisteredStrategy:
    config = _momentum()
    return RegisteredStrategy(config=config, plugin=build_scanner(config))


def _run(local_tmp: Path) -> AnalysisState:
    del local_tmp
    return run_analysis(
        csv_root=CSV_ROOT,
        as_of=ANALYSIS_AS_OF,
        universe_config=load_universe_config(ANALYSIS_CONFIGS / "universe.yaml"),
        factor_configs=_analysis_factor_configs(),
        scanners=(_momentum_scanner(),),
        dataset=ANALYSIS_LONG_DATASET,
    )


def test_the_analysis_returns_factors_a_universe_and_strategy_results() -> None:
    state = _run(Path())

    assert state.factor_results
    assert state.universe.as_of == ANALYSIS_AS_OF
    assert {result.strategy_id for result in state.strategy_results} == {"momentum"}
    # 长夹具一共 3034 根日线：质量门禁看的是整份数据集，而不是被 Universe
    # 放行的那 7 只。
    assert state.outcome.quality_report.checked == 3034
    assert state.outcome.quality_report.accepted == 3034
    assert state.outcome.quality_report.blocking() == ()


def test_the_analysis_writes_nothing(local_tmp: Path) -> None:
    """只计算的链路：没有正式快照，也没有 Job Manifest。"""
    snapshot_root = local_tmp / "snapshots"
    job_root = local_tmp / "jobs"

    run_analysis(
        csv_root=CSV_ROOT,
        as_of=ANALYSIS_AS_OF,
        universe_config=load_universe_config(ANALYSIS_CONFIGS / "universe.yaml"),
        factor_configs=_analysis_factor_configs(),
        scanners=(_momentum_scanner(),),
        dataset=ANALYSIS_LONG_DATASET,
    )

    assert not snapshot_root.exists()
    assert not job_root.exists()


def test_the_daily_pipeline_uses_the_same_business_steps(local_tmp: Path) -> None:
    """`daily` 与 `run_analysis` 必须给出同一份因子、Universe 与策略结果。

    两边共用 `stages` 里的同一组函数，所以这不是"看起来一样"，而是同一份
    实现被调用两次；一旦谁偷偷复制了一套计算，这条测试立刻会红。
    """
    scanners = (_momentum_scanner(),)
    expected = run_analysis(
        csv_root=CSV_ROOT,
        as_of=ANALYSIS_AS_OF,
        universe_config=load_universe_config(ANALYSIS_CONFIGS / "universe.yaml"),
        factor_configs=_analysis_factor_configs(),
        scanners=scanners,
        dataset=ANALYSIS_LONG_DATASET,
    )
    daily = run_daily(
        csv_root=CSV_ROOT,
        as_of=ANALYSIS_AS_OF,
        universe_config=load_universe_config(ANALYSIS_CONFIGS / "universe.yaml"),
        factor_configs=_analysis_factor_configs(),
        scanners=scanners,
        strategy_directory=ANALYSIS_CONFIGS / "strategies",
        store=JsonSnapshotStore(local_tmp / "snapshots"),
        job_store=JsonJobStore(local_tmp / "jobs"),
        dataset=ANALYSIS_LONG_DATASET,
    )

    assert daily.factor_results == expected.factor_results
    assert daily.universe == expected.universe
    assert daily.strategy_results == expected.strategy_results


def test_every_designed_universe_exclusion_fires_on_its_symbol() -> None:
    state = _run(Path())
    by_symbol = {
        exclusion.symbol: tuple(
            item.rule
            for item in state.universe.exclusions
            if item.symbol == exclusion.symbol
        )
        for exclusion in state.universe.exclusions
    }

    for symbol, rules in EXPECTED_EXCLUSIONS.items():
        assert by_symbol[symbol] == rules, symbol


def test_the_deferred_suspension_rule_is_reported_not_applied() -> None:
    state = _run(Path())

    deferred = {rule.rule for rule in state.universe.deferred_rules}
    assert deferred == {UniverseRule.LONG_SUSPENSION}
    # 000006.SZ 停牌很久了，但这条规则没有阈值：用一个没人评审过的天数把它剔
    # 除，正是 deferred 契约存在的意义所在。
    assert "000006.SZ" in state.universe.included


def test_the_ranking_matches_the_hand_computed_order() -> None:
    state = _run(Path())

    scored = sorted(
        (
            (item.symbol, item.score)
            for item in state.strategy_results
            if item.score is not None
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )

    assert [symbol for symbol, _ in scored] == list(EXPECTED_RANKING)
    # 分数严格递减：没有并列可以藏在排序后面。
    assert all(later[1] < earlier[1] for earlier, later in pairwise(scored))


def test_only_universe_symbols_enter_the_strategies() -> None:
    """被 Universe 排除的标的不能在背后被打分。"""
    state = _run(Path())

    assert {item.symbol for item in state.strategy_results} == set(
        state.universe.included
    )


def test_short_history_is_null_rather_than_a_number() -> None:
    measured: FactorState = compute_factor_state(
        csv_root=CSV_ROOT,
        as_of=ANALYSIS_AS_OF,
        factor_configs=(load_factor_config(LIQUIDITY_FACTOR_CONFIG),),
    )
    by_symbol = {item.symbol: item for item in measured.factor_results}

    assert by_symbol["000001.SZ"].status is DataStatus.NULL
    assert by_symbol["000001.SZ"].raw_value is None
    assert by_symbol["601398.SH"].status is DataStatus.NULL
    assert by_symbol["601398.SH"].raw_value is None


def test_a_missing_input_never_became_zero() -> None:
    """600519.SH 与 601398.SH 的成交额在夹具里是空值。"""
    measured = compute_factor_state(
        csv_root=CSV_ROOT,
        as_of=ANALYSIS_AS_OF,
        factor_configs=(load_factor_config(LIQUIDITY_FACTOR_CONFIG),),
    )
    by_symbol = {item.symbol: item for item in measured.factor_results}

    for symbol in ("600519.SH", "601398.SH"):
        assert by_symbol[symbol].raw_value != 0
    assert by_symbol["601398.SH"].raw_value is None


# ===========================================================================
# 来源：tests/integration/test_candidate_correctness_gate.py（6 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Integration tests locking candidate correctness gaps and safety gates.
#
# Spec: docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md
# Plan: docs/superpowers/plans/2026-09-21-candidate-correctness-safety-gate.md
#


CORRECTNESS_GATE_ROOT = Path(__file__).resolve().parents[2]


CORRECTNESS_GATE_CSV_ROOT = CORRECTNESS_GATE_ROOT / "tests" / "fixtures" / "csv"


CG_CONFIGS = CORRECTNESS_GATE_ROOT / "configs"


CG_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _factor(name: str, value: float | None, symbol: str = "600000.SH") -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=CG_AS_OF,
        status=DataStatus.VALUE if value is not None else DataStatus.NULL,
        raw_value=value,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
    )


def test_value_qualified_symbol_must_keep_value_validation_semantics() -> None:
    """Gap 1: Value 策略合格标的必须保持 Value 语义，不得被按 Momentum 规则判定为动量破坏。"""
    symbol = "600000.SH"
    factors = (
        _factor("ret_20d", -0.04, symbol=symbol),
        _factor("proximity_52w_high", 0.70, symbol=symbol),
        _factor("avg_amount_20d", 200_000_000.0, symbol=symbol),
    )

    # 显式传入策略映射与5维证据，断言验证结果携带并执行 value 语义
    results = market_validation_stage(
        symbols=[symbol],
        factor_results=factors,
        as_of=CG_AS_OF,
        strategy_by_symbol={symbol: "value"},
        vol_ratio_by_symbol={symbol: 1.1},
        industry_excess_by_symbol={symbol: 0.02},
        relative_strength_by_symbol={symbol: 0.05},
    )
    assert len(results) == 1
    result = results[0]

    # 1. 结果必须标记为 value 策略，而非写死的 momentum
    assert result.strategy_id == "value"
    # 2. 在 Value 策略下，ret_20d=-0.04 属于低估值区间正常调整，不得触发动量结构破坏风险
    assert not any("动量结构破坏" in r for r in result.risks)
    assert result.status != MarketValidation.CONTRADICTED


def test_growth_qualified_symbol_never_falls_through_to_value_contrarian_signal() -> (
    None
):
    """Gap 2: Growth 标的由于缺少 strategy_id，绝不能误跨界命中 Value/Dividend 规则。"""
    symbol = "300750.SZ"
    factors = (
        _factor("ret_20d", -0.01, symbol=symbol),
        _factor("ret_60d", 0.05, symbol=symbol),
        _factor("proximity_52w_high", 0.70, symbol=symbol),
    )

    results = signal_stage(
        symbols=[symbol],
        factor_results=factors,
        as_of=CG_AS_OF,
        strategy_by_symbol={symbol: "growth"},
    )
    assert len(results) == 1
    result = results[0]

    # 1. 结果必须显式记录所属策略为 growth
    assert getattr(result, "strategy_id", None) == "growth"
    # 2. Growth 标的绝对不能被贴上 VALUE_CONTRARIAN (价值逆向) 信号
    assert result.signal != Signal.VALUE_CONTRARIAN
    assert result.signal == Signal.NO_SIGNAL


def test_detect_regime_fails_closed_when_market_breadth_is_unavailable(
    local_tmp: Path,
) -> None:
    """Gap 3: 市场宽度不可用时，不得使用合成的 0.50 静默兜底判定为成功。"""
    # 构造日线数据无法计算有效宽度（没有足额 20 日历史）的场景
    empty_csv_root = local_tmp / "empty_csv"
    empty_csv_root.mkdir(parents=True)
    (empty_csv_root / "daily_bars.csv").write_text(
        "symbol,trade_date,open,high,low,close,volume,amount\n",
        encoding="utf-8",
    )
    (empty_csv_root / "securities.csv").write_text(
        "symbol,name,list_date\n",
        encoding="utf-8",
    )

    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    result = run_daily(
        csv_root=empty_csv_root,
        as_of=CG_AS_OF,
        universe_config=load_universe_config(CG_CONFIGS / "universe.yaml"),
        factor_configs=(),
        scanners=(),
        strategy_directory=CG_CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars",
        qualifiers={},
        candidate_policy=RepresentativeCandidatePolicy(version="v1"),
    )

    runs = {r.job_type: r for r in result.runs}
    regime_run = runs.get(JobStage.DETECT_REGIME)
    assert regime_run is not None
    # 必须 fail-closed：状态不得为 SUCCEEDED，note 中不得含有伪造 0.50 成功的记录
    assert regime_run.status != JobStatus.SUCCEEDED


def test_unconfigured_candidate_policy_fails_candidate_publication(
    local_tmp: Path,
) -> None:
    """未配置批准的 CandidatePolicy 时，Candidate 发布必须 fail-closed，严禁发布 CANDIDATE 快照。"""
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((CG_CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    result = run_daily(
        csv_root=CORRECTNESS_GATE_CSV_ROOT,
        as_of=CG_AS_OF,
        universe_config=load_universe_config(CG_CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(CG_CONFIGS / "strategies"),
        strategy_directory=CG_CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars_long",
        qualifiers=qualifiers,
        candidate_policy=None,
    )

    runs = {r.job_type: r for r in result.runs}
    candidate_run = runs.get(JobStage.BUILD_CANDIDATES)
    assert candidate_run is not None
    # 未配置候选策略时，BUILD_CANDIDATES 必须保持 BLOCKED，不得写入 CANDIDATE 快照
    assert candidate_run.status == JobStatus.BLOCKED
    assert not (
        local_tmp / "snapshots" / "CANDIDATE" / f"{CG_AS_OF.date().isoformat()}.json"
    ).exists()


def test_only_qualified_symbols_enter_downstream_validation_and_signal(
    local_tmp: Path,
) -> None:
    """Step 1: 只有至少有一个合格策略的标的才进入下游市场验证与信号检测。"""
    from astock_lens.pipelines.daily import (
        _primary_strategy_by_symbol,
    )
    from astock_lens.qualifications.models import StrategyQualification

    quals = [
        StrategyQualification(
            symbol="600000.SH",
            strategy_id="value",
            strategy_version="v1",
            qualification_version="v1",
            as_of=CG_AS_OF,
            rank_percentile=0.95,
            rank=1,
            total_evaluable=100,
            percentile_pass=True,
            absolute_pass=True,
            qualified=True,
        ),
        StrategyQualification(
            symbol="000001.SZ",
            strategy_id="growth",
            strategy_version="v1",
            qualification_version="v1",
            as_of=CG_AS_OF,
            rank_percentile=0.70,
            rank=30,
            total_evaluable=100,
            percentile_pass=False,
            absolute_pass=False,
            qualified=False,
        ),
    ]

    strat_map = _primary_strategy_by_symbol(quals)
    # 只有合格标的 600000.SH 进入映射，未合格标的 000001.SZ 绝不进入
    assert "600000.SH" in strat_map
    assert "000001.SZ" not in strat_map
    assert strat_map["600000.SH"] == "value"


def test_multi_qualified_symbol_derives_deterministic_primary_strategy_mapping() -> (
    None
):
    """Step 2: 多策略合格标的确定性推导主策略映射。"""
    from astock_lens.pipelines.daily import _primary_strategy_by_symbol
    from astock_lens.qualifications.models import StrategyQualification

    quals = [
        StrategyQualification(
            symbol="600000.SH",
            strategy_id="value",
            strategy_version="v1",
            qualification_version="v1",
            as_of=CG_AS_OF,
            rank_percentile=0.91,
            rank=9,
            total_evaluable=100,
            percentile_pass=True,
            absolute_pass=True,
            qualified=True,
        ),
        StrategyQualification(
            symbol="600000.SH",
            strategy_id="growth",
            strategy_version="v1",
            qualification_version="v1",
            as_of=CG_AS_OF,
            rank_percentile=0.95,
            rank=5,
            total_evaluable=100,
            percentile_pass=True,
            absolute_pass=True,
            qualified=True,
        ),
    ]
    strat_map = _primary_strategy_by_symbol(quals)
    assert strat_map["600000.SH"] == "growth"


# ===========================================================================
# 来源：tests/integration/test_candidate_qualification_pipeline.py（5 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


QUALIFICATION_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


LINEAGE = SnapshotLineage(
    universe_snapshot="2026-09-04:fixture",
    factor_version="v1",
    strategy_version="v1",
)


class _DummyPassRule:
    version = "v1"

    def evaluate(self, context: QualificationContext) -> AbsoluteQualificationVerdict:
        return AbsoluteQualificationVerdict(passed=True, reasons=("passed absolute",))


class _DummyFailRule:
    version = "v1"

    def evaluate(self, context: QualificationContext) -> AbsoluteQualificationVerdict:
        return AbsoluteQualificationVerdict(passed=False, risks=("failed absolute",))


def _make_strategy_result(
    symbol: str,
    strategy_id: str = "value",
    percentile: float = 0.95,
    score: float = 85.0,
    eligible: bool = True,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=QUALIFICATION_AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
        rank_percentile=percentile,
    )


def test_canonical_qualifiers_removes_unconfigured_reason() -> None:
    from astock_lens.qualifications.registry import load_canonical_qualifiers

    context = _Context(
        csv_root=Path("/fake"),
        as_of=QUALIFICATION_AS_OF,
        dataset="bars",
        securities_dataset="securities",
        universe_config=UniverseConfig(
            exchanges=("SSE", "SZSE"),
            min_listing_days=180,
            min_average_turnover_20d=10_000_000.0,
        ),
        factor_configs=(),
        scanners=(),
        strategy_directory=Path("/fake"),
        store=None,  # type: ignore[arg-type]
        sync=None,
        candidate_policy=RepresentativeCandidatePolicy(),
        qualifiers=load_canonical_qualifiers(),
    )
    reasons = _blocked_reasons(JobStage.BUILD_CANDIDATES, context)
    assert not any(
        "strategy qualification rules are not configured" in r for r in reasons
    )


def test_missing_upstream_layers_blocks_build_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "astock_lens.pipelines.daily.BLOCKED_REASONS",
        {
            JobStage.DETECT_REGIME: "test reason",
            JobStage.MARKET_VALIDATE: "test reason",
            JobStage.RUN_SIGNALS: "test reason",
        },
    )
    context = _Context(
        csv_root=Path("/fake"),
        as_of=QUALIFICATION_AS_OF,
        dataset="bars",
        securities_dataset="securities",
        universe_config=UniverseConfig(
            exchanges=("SSE", "SZSE"),
            min_listing_days=180,
            min_average_turnover_20d=10_000_000.0,
        ),
        factor_configs=(),
        scanners=(),
        strategy_directory=Path("/fake"),
        store=None,  # type: ignore[arg-type]
        sync=None,
        candidate_policy=RepresentativeCandidatePolicy(),
        qualifiers=build_qualifiers(
            {
                s: _DummyPassRule()
                for s in ("value", "growth", "garp", "quality", "dividend", "momentum")
            }
        ),
    )
    reasons = _blocked_reasons(JobStage.BUILD_CANDIDATES, context)
    assert any("its inputs do not exist yet" in r for r in reasons)
    assert any(JobStage.MARKET_VALIDATE.value in r for r in reasons)
    assert any(JobStage.RUN_SIGNALS.value in r for r in reasons)


def test_candidate_stage_direct_call_with_complete_evidence_produces_candidates() -> (
    None
):
    policy = RepresentativeCandidatePolicy()
    sym = "600000.SH"
    strat_res = _make_strategy_result(sym, strategy_id="value", percentile=0.95)
    qual = StrategyQualification(
        symbol=sym,
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    candidates = stages.candidate_stage(
        strategy_results=(strat_res,),
        qualifications=(qual,),
        market_validation_by_symbol={sym: MarketValidation.CONFIRMED},
        signal_by_symbol={sym: Signal.BREAKOUT},
        lineage=LINEAGE,
        as_of=QUALIFICATION_AS_OF,
        policy=policy,
    )
    assert len(candidates) == 1
    c = candidates[0]
    assert c.symbol == sym
    assert c.next_action is NextAction.WATCH
    assert c.market_validation is MarketValidation.CONFIRMED
    assert c.signal is Signal.BREAKOUT


def test_signal_no_signal_does_not_disqualify_candidate() -> None:
    policy = RepresentativeCandidatePolicy()
    sym = "600000.SH"
    strat_res = _make_strategy_result(sym, strategy_id="value", percentile=0.95)
    qual = StrategyQualification(
        symbol=sym,
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    candidates = stages.candidate_stage(
        strategy_results=(strat_res,),
        qualifications=(qual,),
        market_validation_by_symbol={sym: MarketValidation.CONFIRMED},
        signal_by_symbol={sym: Signal.NO_SIGNAL},
        lineage=LINEAGE,
        as_of=QUALIFICATION_AS_OF,
        policy=policy,
    )
    assert len(candidates) == 1
    assert candidates[0].symbol == sym
    assert candidates[0].signal is Signal.NO_SIGNAL


def test_market_validation_contradicted_disqualifies_candidate() -> None:
    policy = RepresentativeCandidatePolicy()
    sym = "600000.SH"
    strat_res = _make_strategy_result(sym, strategy_id="value", percentile=0.95)
    qual = StrategyQualification(
        symbol=sym,
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
    )
    candidates = stages.candidate_stage(
        strategy_results=(strat_res,),
        qualifications=(qual,),
        market_validation_by_symbol={sym: MarketValidation.CONTRADICTED},
        signal_by_symbol={sym: Signal.BREAKOUT},
        lineage=LINEAGE,
        as_of=QUALIFICATION_AS_OF,
        policy=policy,
    )
    assert candidates == ()


# ===========================================================================
# 来源：tests/integration/test_daily_candidate_pipeline.py（1 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


DAILY_CANDIDATE_ROOT = Path(__file__).resolve().parents[2]


DAILY_CANDIDATE_CSV_ROOT = DAILY_CANDIDATE_ROOT / "tests" / "fixtures" / "csv"


DAILY_CANDIDATE_CONFIGS = DAILY_CANDIDATE_ROOT / "configs"


DAILY_CANDIDATE_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


DAILY_CANDIDATE_LONG_DATASET = "daily_bars_long"


def test_daily_pipeline_executes_regime_validation_signal_and_candidates(
    local_tmp: Path,
) -> None:
    """测试日常管线在配置资格与候选政策后，顺畅执行市场环境、市场验证、信号与候选发布。"""
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((DAILY_CANDIDATE_CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    policy = RepresentativeCandidatePolicy(
        version="v1", soft_reserve_per_strategy=3, max_candidates=50
    )

    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    result = run_daily(
        csv_root=DAILY_CANDIDATE_CSV_ROOT,
        as_of=DAILY_CANDIDATE_AS_OF,
        universe_config=load_universe_config(DAILY_CANDIDATE_CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(DAILY_CANDIDATE_CONFIGS / "strategies"),
        strategy_directory=DAILY_CANDIDATE_CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset=DAILY_CANDIDATE_LONG_DATASET,
        qualifiers=qualifiers,
        candidate_policy=policy,
    )

    # 验证各阶段执行状态（Plan B 审批通过并完成五维接线后，BUILD_CANDIDATES 顺利执行为 SUCCEEDED）
    runs_by_type = {run.job_type: run for run in result.runs}
    assert runs_by_type[JobStage.DETECT_REGIME].status == JobStatus.SUCCEEDED
    assert runs_by_type[JobStage.MARKET_VALIDATE].status == JobStatus.SUCCEEDED
    assert runs_by_type[JobStage.RUN_SIGNALS].status == JobStatus.SUCCEEDED
    assert runs_by_type[JobStage.BUILD_CANDIDATES].status == JobStatus.SUCCEEDED

    # 验证 CANDIDATE 快照正式落盘
    assert (local_tmp / "snapshots" / "CANDIDATE" / "2026-09-04.json").exists()
    assert len(result.candidates) > 0


# ===========================================================================
# 来源：tests/integration/test_daily_production_evidence.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


PRODUCTION_EVIDENCE_ROOT = Path(__file__).resolve().parents[2]


FIXTURE_CSV = PRODUCTION_EVIDENCE_ROOT / "tests" / "fixtures" / "csv"


PE_CONFIGS = PRODUCTION_EVIDENCE_ROOT / "configs"


PE_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


BENCHMARK_ID = "000985.CSI"


BENCHMARK_HEADER = "symbol,trade_date,open,high,low,close,volume,amount\n"


def _write_benchmark_csv(path: Path, count: int = 70) -> Path:
    """写入指定天数的基准指数日线 CSV 文件。"""
    p = FIXTURE_CSV / "daily_bars_long.csv"
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        dates = sorted({date.fromisoformat(row["trade_date"]) for row in reader})
    selected_dates = dates[-count:]

    lines = [BENCHMARK_HEADER]
    for i, d in enumerate(selected_dates):
        lines.append(
            f"{BENCHMARK_ID},{d.isoformat()},3000.0,3050.0,2950.0,{3000.0 + i},100000.0,1000000.0\n"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _write_industry_csv(dir_path: Path, filename: str = "2026-09-04.csv") -> Path:
    """写入包含全部测试标的的申万行业 CSV 文件。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / filename
    rows = [
        ("000001.SZ", "sw2_bank", "银行"),
        ("000002.SZ", "sw2_realestate", "房地产"),
        ("000003.SZ", "sw2_software", "软件开发"),
        ("000004.SZ", "sw2_software", "软件开发"),
        ("000005.SZ", "sw2_env", "环保"),
        ("000006.SZ", "sw2_realestate", "房地产"),
        ("300750.SZ", "sw2_battery", "电池"),
        ("600000.SH", "sw2_bank", "银行"),
        ("600519.SH", "sw2_liquor", "白酒"),
        ("830799.BJ", "sw2_machinery", "通用设备"),
        ("900948.SH", "sw2_power", "电力"),
    ]
    lines = ["symbol,industry_id,industry_name,as_of,provider,source_ref\n"]
    for sym, ind_id, ind_name in rows:
        lines.append(
            f"{sym},{ind_id},{ind_name},2026-09-04T15:00:00+00:00,westock-cli,\n"
        )
    file_path.write_text("".join(lines), encoding="utf-8")
    return file_path


def _benchmark_bars_tuple(count: int = 70) -> tuple[DailyBar, ...]:
    """生成指定数量的 DailyBar 元组。"""
    p = FIXTURE_CSV / "daily_bars_long.csv"
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        dates = sorted({date.fromisoformat(row["trade_date"]) for row in reader})
    selected_dates = dates[-count:]
    return tuple(
        DailyBar(
            symbol=BENCHMARK_ID,
            trade_date=d,
            open=3000.0,
            high=3050.0,
            low=2950.0,
            close=3000.0 + i,
            volume=100000.0,
            amount=1000000.0,
        )
        for i, d in enumerate(selected_dates)
    )


ALL_INDUSTRY_MAP = {
    "000001.SZ": "银行",
    "000002.SZ": "房地产",
    "000003.SZ": "软件开发",
    "000004.SZ": "软件开发",
    "000005.SZ": "环保",
    "000006.SZ": "房地产",
    "300750.SZ": "电池",
    "600000.SH": "银行",
    "600519.SH": "白酒",
    "830799.BJ": "通用设备",
    "900948.SH": "电力",
}


def test_step1_composition_proves_benchmark_and_industry_reach_run_daily(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 1: 装配测试证明 benchmark_bars 与 industry_by_symbol 被真实传递给 run_daily。"""
    import astock_lens.cli.app as app_module

    bm_path = _write_benchmark_csv(tmp_path / "raw" / "benchmark_bars.csv", count=70)
    _write_industry_csv(tmp_path / "raw" / "westock" / "industry")

    monkeypatch.setenv(BENCHMARK_BARS_ENV, str(bm_path))
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(tmp_path / "raw"))
    monkeypatch.setenv("ASTOCK_STORAGE_ROOT", str(tmp_path / "storage"))

    captured_kwargs: dict[str, Any] = {}

    def spy_run_daily(*args: Any, **kwargs: Any) -> DailyRunResult:
        captured_kwargs.update(kwargs)
        return DailyRunResult(as_of=PE_AS_OF)

    monkeypatch.setattr(app_module, "run_daily", spy_run_daily)

    _run_daily(PE_AS_OF, land=False)

    assert "benchmark_id" in captured_kwargs
    assert captured_kwargs["benchmark_id"] == BENCHMARK_ID
    assert "benchmark_bars" in captured_kwargs
    assert captured_kwargs["benchmark_bars"] is not None
    assert len(captured_kwargs["benchmark_bars"]) == 70

    expected_bars = read_benchmark_bars(
        path=bm_path, benchmark_id=BENCHMARK_ID, as_of=PE_AS_OF
    )
    assert captured_kwargs["benchmark_bars"] == expected_bars

    assert "industry_by_symbol" in captured_kwargs
    assert captured_kwargs["industry_by_symbol"] is not None
    expected_industry = _production_industry_map(PE_AS_OF, root=tmp_path / "raw")
    assert captured_kwargs["industry_by_symbol"] == expected_industry
    assert "300750.SZ" in captured_kwargs["industry_by_symbol"]


def test_step2_missing_benchmark_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 2: 缺失基准指数日线文件时，抛出 FileNotFoundError，CLI 退出码非零且不产出新候选快照。"""
    missing_path = tmp_path / "missing_benchmark.csv"
    _write_industry_csv(tmp_path / "raw" / "westock" / "industry")

    monkeypatch.setenv(BENCHMARK_BARS_ENV, str(missing_path))
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(tmp_path / "raw"))
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("ASTOCK_STORAGE_ROOT", str(storage_root))

    # 1. _run_daily 直接调用严格抛出 FileNotFoundError
    with pytest.raises(FileNotFoundError, match=r"Benchmark bars file not found"):
        _run_daily(PE_AS_OF, land=False)

    # 2. CLI daily 运行退出码非零
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["daily", "--as-of", "2026-09-04", "--allow-incomplete"],
        env={
            BENCHMARK_BARS_ENV: str(missing_path),
            "ASTOCK_CSV_ROOT": str(tmp_path / "raw"),
            "ASTOCK_STORAGE_ROOT": str(storage_root),
        },
    )
    assert result.exit_code != 0

    # 3. 绝不写出新的 Candidate 快照
    candidate_snapshot = storage_root / "snapshots" / "CANDIDATE" / "2026-09-04.json"
    assert not candidate_snapshot.exists()


def test_step3_insufficient_59_benchmark_bars_regime_fails_closed(
    tmp_path: Path,
) -> None:
    """Step 3: 仅 59 根基准日线时，DETECT_REGIME 必须严格阻断 fail-closed，候选快照不得产出。"""
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((PE_CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    policy = RepresentativeCandidatePolicy(
        version="v1", soft_reserve_per_strategy=3, max_candidates=50
    )

    store = JsonSnapshotStore(tmp_path / "snapshots")
    job_store = JsonJobStore(tmp_path / "jobs")

    bars_59 = _benchmark_bars_tuple(count=59)

    result = run_daily(
        csv_root=FIXTURE_CSV,
        as_of=PE_AS_OF,
        universe_config=load_universe_config(PE_CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(PE_CONFIGS / "strategies"),
        strategy_directory=PE_CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars_long",
        qualifiers=qualifiers,
        candidate_policy=policy,
        benchmark_id=BENCHMARK_ID,
        benchmark_bars=bars_59,
        industry_by_symbol=ALL_INDUSTRY_MAP,
    )

    runs_by_type = {run.job_type: run for run in result.runs}
    assert runs_by_type[JobStage.DETECT_REGIME].status == JobStatus.FAILED
    assert "000985.CSI benchmark trend" in str(
        runs_by_type[JobStage.DETECT_REGIME].error
    )

    # 下游阶段终止，未产生候选集与候选快照
    assert JobStage.BUILD_CANDIDATES not in runs_by_type
    assert len(result.candidates) == 0
    assert not (tmp_path / "snapshots" / "CANDIDATE" / "2026-09-04.json").exists()


def _missing_industry_evidence_case(root: Path) -> tuple[Path, dict[str, str]]:
    """缺失 300750.SZ（达标标的）的行业映射表；CSV 仍用共享夹具目录，与原来一致。"""
    incomplete_industry_map = {
        k: v for k, v in ALL_INDUSTRY_MAP.items() if k != "300750.SZ"
    }
    return FIXTURE_CSV, incomplete_industry_map


def _insufficient_volume_bars_case(root: Path) -> tuple[Path, dict[str, str]]:
    """把 300750.SZ 的历史成交量置零，只留最后 19 根（有效量 bar < 20）。"""
    csv_root = root / "csv"
    csv_root.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_CSV / "securities.csv", csv_root / "securities.csv")

    p = FIXTURE_CSV / "daily_bars_long.csv"
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    # 对 300750.SZ，仅保留最后 19 根成交量，其余历史成交量置零（有效量 bar < 20）
    sym_rows = [r for r in rows if r["symbol"] == "300750.SZ"]
    for r in sym_rows[:-19]:
        r["volume"] = "0.0"

    with (csv_root / "daily_bars_long.csv").open("w", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return csv_root, ALL_INDUSTRY_MAP


# 「MARKET_VALIDATE 对已资格标的 fail-closed」两行：行序与原用例一致，
# label 兼作该行的运行根目录名，行与行不共享现场（原用例各自拿一份新的 `tmp_path`）。
# 列 = label, prepare, expected_evidence：
#   - `missing-industry-evidence` 是原
#     test_step4_qualified_symbol_missing_industry_evidence_fails_closed
#     （Step 4，docstring：达标标的缺失申万行业证据时，MARKET_VALIDATE 必须严格阻断 fail-closed。）；
#   - `insufficient-volume-bars` 是原
#     test_step5_qualified_symbol_insufficient_volume_bars_fails_closed
#     （Step 5，docstring：达标标的有效果量不足 20 根 bar 时，MARKET_VALIDATE 必须严格阻断 fail-closed。）。
# 两行的 run_daily 公共参数一致；step5 原本显式写的
# `securities_dataset="securities"` 就是 step4 走的默认值，故在公共调用里显式写出。
MARKET_VALIDATE_FAIL_CLOSED_CASES = (
    (
        "missing-industry-evidence",
        _missing_industry_evidence_case,
        "300750.SZ missing required 5D evidence: industry_excess_return_20d",
    ),
    (
        "insufficient-volume-bars",
        _insufficient_volume_bars_case,
        "300750.SZ missing required 5D evidence: volume_ratio_5_20",
    ),
)


def test_step4_qualified_symbol_missing_industry_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    """Step 4 / Step 5: 达标标的缺证据时，MARKET_VALIDATE 必须严格阻断 fail-closed。

    原 step4 / step5 两条 fail-closed 用例逐条成行（同一规则的两个缺失维度：
    行业证据 / 有效量）；循环只收集，断言在表外一次完成，失败消息点名行 label。
    """
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((PE_CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    policy = RepresentativeCandidatePolicy(
        version="v1", soft_reserve_per_strategy=3, max_candidates=50
    )
    bars_70 = _benchmark_bars_tuple(count=70)

    wrong = []
    for label, prepare, expected_evidence in MARKET_VALIDATE_FAIL_CLOSED_CASES:
        case_root = tmp_path / label
        csv_root, industry_by_symbol = prepare(case_root)

        result = run_daily(
            csv_root=csv_root,
            as_of=PE_AS_OF,
            universe_config=load_universe_config(PE_CONFIGS / "universe.yaml"),
            factor_configs=factor_configs,
            scanners=load_scanners(PE_CONFIGS / "strategies"),
            strategy_directory=PE_CONFIGS / "strategies",
            store=JsonSnapshotStore(case_root / "snapshots"),
            job_store=JsonJobStore(case_root / "jobs"),
            dataset="daily_bars_long",
            securities_dataset="securities",
            qualifiers=qualifiers,
            candidate_policy=policy,
            benchmark_id=BENCHMARK_ID,
            benchmark_bars=bars_70,
            industry_by_symbol=industry_by_symbol,
        )

        runs_by_type = {run.job_type: run for run in result.runs}
        regime = runs_by_type[JobStage.DETECT_REGIME]
        if regime.status != JobStatus.SUCCEEDED:
            wrong.append(
                f"{label}: DETECT_REGIME status 为 {regime.status}，期望 SUCCEEDED"
            )
        validate = runs_by_type[JobStage.MARKET_VALIDATE]
        if validate.status != JobStatus.FAILED:
            wrong.append(
                f"{label}: MARKET_VALIDATE status 为 {validate.status}，期望 FAILED"
            )
        if expected_evidence not in str(validate.error):
            wrong.append(
                f"{label}: error={str(validate.error)!r} 不含 {expected_evidence!r}"
            )
        # 下游阶段终止，未产生候选集与快照
        if JobStage.BUILD_CANDIDATES in runs_by_type:
            wrong.append(f"{label}: 下游 BUILD_CANDIDATES 不得运行")
        if len(result.candidates) != 0:
            wrong.append(f"{label}: candidates 有 {len(result.candidates)} 条，期望 0")
        candidate_snapshot = case_root / "snapshots" / "CANDIDATE" / "2026-09-04.json"
        if candidate_snapshot.exists():
            wrong.append(f"{label}: 候选快照不得产出 {candidate_snapshot}")
    assert not wrong, "MARKET_VALIDATE 未 fail-closed:\n" + "\n".join(wrong)


# ===========================================================================
# 来源：tests/integration/test_dividend_factor_pipeline.py（1 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


DIVIDEND_FACTOR_SHANGHAI = ZoneInfo("Asia/Shanghai")


DIVIDEND_FACTOR_AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=DIVIDEND_FACTOR_SHANGHAI)


def _factor_config() -> FactorConfig:
    return FactorConfig(
        name="dividend_yield_ttm",
        domain="VALUATION",
        description="Trailing dividend yield, in percent.",
        inputs=("dividend_yield_ttm",),
        frequency="DAILY",
        direction="HIGHER_MEANS_MORE_INCOME_RETURNED",
        null_policy="NULL_UNLESS_THE_METRIC_HAS_A_PUBLISHED_VALUE",
        version="v1",
    )


def test_pipeline_computes_dividend_yield_ttm_from_landed_events(
    tmp_path: Path,
) -> None:
    """测试分析管线从落地分红历史数据到产出有效 dividend_yield_ttm 因子。"""
    csv_root = tmp_path / "csv"
    bars_dir = csv_root / "daily_bars"
    div_dir = csv_root / "neodata" / "dividend_history"
    sec_dir = csv_root / "securities"
    bars_dir.mkdir(parents=True)
    div_dir.mkdir(parents=True)
    sec_dir.mkdir(parents=True)

    # 1. 写入证券名单
    sec_file = sec_dir / "securities.csv"
    sec_file.write_text(
        "symbol,name,list_date\n601398.SH,工商银行,2006-10-27\n",
        encoding="utf-8",
    )

    # 2. 写入日线行情 (股价 5.00 元)
    bar_file = csv_root / "daily_bars.csv"
    bar_file.write_text(
        "symbol,trade_date,open,high,low,close,volume,amount\n"
        "601398.SH,2026-09-18,5.00,5.00,5.00,5.00,1000000,5000000\n",
        encoding="utf-8",
    )

    # 3. 写入分红历史落地文件
    div_file = div_dir / "2026-09-20.csv"
    div_text = (
        "### 601398.SH 工商银行 分红信息\n"
        "| 公告日期 | 分红方案描述 | 股权登记日 | 除权除息日 | 方案进度 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 2026-06-25 | 10派3.06元 | 2026-07-15 | 2026-07-16 | 实施 |\n"
    )
    div_file.write_text(
        f'type,desc,content\n分红派息详细,分红派息详细,"{div_text}"\n',
        encoding="utf-8",
    )

    # 4. 执行 normalize_stage
    outcome = normalize_stage(csv_root=csv_root, as_of=DIVIDEND_FACTOR_AS_OF)
    assert len(outcome.bars.dividend_events) >= 1
    assert outcome.bars.dividend_events[0].symbol == "601398.SH"

    # 5. 执行 factor_stage
    results = factor_stage(
        outcome=outcome,
        factor_configs=(_factor_config(),),
        as_of=DIVIDEND_FACTOR_AS_OF,
    )
    assert len(results) == 1
    fr = results[0]
    assert fr.factor == "dividend_yield_ttm"
    assert fr.status == DataStatus.VALUE
    assert fr.raw_value is not None
    # 10 派 3.06 -> 每股 0.306 / 5.00 * 100 = 6.12%
    assert round(fr.raw_value, 4) == 6.1200


# ===========================================================================
# 来源：tests/integration/test_dividend_qualified_discovery.py（2 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


DIVIDEND_DISCOVERY_SHANGHAI = ZoneInfo("Asia/Shanghai")


DQ_AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=DIVIDEND_DISCOVERY_SHANGHAI)


def _fr(symbol: str, factor: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=DQ_AS_OF,
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
        as_of=DQ_AS_OF,
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


# ===========================================================================
# 来源：tests/integration/test_financial_pipeline.py（7 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# End-to-end test for the fundamentals side of the pipeline.
#
# The rule this pins down: a landed statement reaches the factor context as
# canonical observations, gated, with the point-in-time fields intact — and a
# statement that was never landed is *named* rather than silently treated as an
# empty one.
#


FINANCIAL_ROOT = Path(__file__).resolve().parents[2]


CSV_FIXTURES = FINANCIAL_ROOT / "tests" / "fixtures" / "csv"


AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


LONG_DATASET = "daily_bars_long"


INCOME_CSV = (
    "code,EndDate,InfoPublDate,OperatingRevenue,ROE,GrossIncomeRatio\n"
    "sh600519,2026-06-30,2026-08-15,90703260964.48,17.7179,89.5552\n"
    "sh600519,2026-03-31,2026-04-25,53909252220.51,10.0565,89.7592\n"
    "sh600519,2026-09-30,2026-11-01,1.0,2.0,3.0\n"
)


def _root_with_financials(local_tmp: Path) -> Path:
    """A raw root holding the bar fixtures plus one landed income statement."""
    for name in ("daily_bars_long.csv", "securities.csv"):
        shutil.copyfile(CSV_FIXTURES / name, local_tmp / name)
    (local_tmp / "financial_income.csv").write_text(INCOME_CSV, encoding="utf-8")
    return local_tmp


def test_a_landed_statement_reaches_the_factor_context(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root_with_financials(local_tmp),
        as_of=AS_OF,
        dataset=LONG_DATASET,
    )

    observations = outcome.bars.observations
    assert observations
    assert {item.metric for item in observations} == {
        "revenue",
        "roe",
        "gross_margin",
    }
    assert all(item.available_at <= AS_OF for item in observations)
    assert all(item.report_period is not None for item in observations)


def test_a_period_published_after_the_scan_is_not_in_the_context(
    local_tmp: Path,
) -> None:
    """The 2026-09-30 period was announced on 2026-11-01, after this scan."""
    outcome = stages.normalize_stage(
        csv_root=_root_with_financials(local_tmp),
        as_of=AS_OF,
        dataset=LONG_DATASET,
    )

    periods = {item.report_period for item in outcome.bars.observations}
    assert periods == {_date(2026, 6, 30), _date(2026, 3, 31)}
    assert outcome.financials.outcomes[0].not_yet_available == 1


def test_statements_that_were_never_landed_are_named(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root_with_financials(local_tmp),
        as_of=AS_OF,
        dataset=LONG_DATASET,
    )

    assert outcome.financials.absent_datasets == (
        "financial_balance",
        "financial_cashflow",
    )
    assert {report.dataset for report in outcome.financials.reports} == {
        "financial_income"
    }


def test_a_scan_without_landed_statements_still_runs_and_says_so(
    local_tmp: Path,
) -> None:
    """Bars must keep working before the first fundamentals sync."""
    shutil.copyfile(
        CSV_FIXTURES / "daily_bars_long.csv", local_tmp / "daily_bars_long.csv"
    )
    shutil.copyfile(CSV_FIXTURES / "securities.csv", local_tmp / "securities.csv")

    outcome = stages.normalize_stage(
        csv_root=local_tmp, as_of=AS_OF, dataset=LONG_DATASET
    )

    assert outcome.bars.observations == ()
    assert outcome.financials.observations == ()
    assert outcome.financials.absent_datasets == (
        "financial_balance",
        "financial_cashflow",
        "financial_income",
    )
    assert outcome.bars.daily_bars


def test_a_missing_value_stays_missing_through_the_pipeline(local_tmp: Path) -> None:
    root = _root_with_financials(local_tmp)
    (root / "financial_income.csv").write_text(
        "code,EndDate,InfoPublDate,OperatingRevenue,ROE\n"
        "sh600519,2026-06-30,2026-08-15,-,17.7179\n",
        encoding="utf-8",
    )

    outcome = stages.normalize_stage(csv_root=root, as_of=AS_OF, dataset=LONG_DATASET)

    revenue = next(
        item for item in outcome.bars.observations if item.metric == "revenue"
    )
    assert revenue.value is None
    report = outcome.financials.reports[0]
    assert [issue.rule for issue in report.issues] == ["value_missing"]
    assert report.usable == 2


def test_the_two_statement_sets_land_and_normalize_together(local_tmp: Path) -> None:
    """Both a balance sheet and an income statement in one context."""
    root = _root_with_financials(local_tmp)
    (root / "financial_balance.csv").write_text(
        "code,EndDate,InfoPublDate,TotalShareholderEquity,DebtAssetsRatio\n"
        "sh600519,2026-06-30,2026-08-15,262096352174.36,15.1931\n",
        encoding="utf-8",
    )

    outcome = stages.normalize_stage(csv_root=root, as_of=AS_OF, dataset=LONG_DATASET)

    metrics = {item.metric for item in outcome.bars.observations}
    assert {"revenue", "total_equity", "debt_to_asset"} <= metrics
    assert outcome.financials.absent_datasets == ("financial_cashflow",)


def test_each_factor_context_carries_only_its_own_symbol(local_tmp: Path) -> None:
    """A factor must not scan the whole market to measure one symbol.

    At whole-market size the difference is quadratic: 5,565 symbols against
    2.1M observations. The contract is also clearer when a context holds what
    the factor is asked about.
    """
    root = _root_with_financials(local_tmp)
    (root / "financial_balance.csv").write_text(
        "code,EndDate,InfoPublDate,TotalShareholderEquity,DebtAssetsRatio\n"
        "sh600519,2026-06-30,2026-08-15,262096352174.36,15.1931\n"
        "sz000001,2026-06-30,2026-08-15,548214000000.0,90.9067\n",
        encoding="utf-8",
    )
    outcome = stages.normalize_stage(csv_root=root, as_of=AS_OF, dataset=LONG_DATASET)
    index = stages.DatasetIndex(outcome.bars)

    view = index.for_symbol("600519.SH")

    assert view.observations
    assert {item.symbol for item in view.observations} == {"600519.SH"}
    assert all(bar.symbol == "600519.SH" for bar in view.daily_bars)
    assert len(view.observations) < len(outcome.bars.observations)
    # Another symbol's view is different, and a symbol with no rows gets an
    # empty view rather than somebody else's data.
    assert index.for_symbol("000001.SZ").observations != view.observations
    empty = index.for_symbol("999999.SH")
    assert empty.observations == ()
    assert empty.daily_bars == ()


def _date(year: int, month: int, day: int) -> object:
    from datetime import date

    return date(year, month, day)


# ===========================================================================
# 来源：tests/integration/test_market_regime_snapshot.py（5 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Integration tests for MARKET_REGIME snapshot persistence and today CLI integration.
#
# Verifies:
# 1. Daily pipeline persists MARKET_REGIME snapshot with exactly one record.
# 2. Persisted MARKET_REGIME record carries regime_version in lineage.
# 3. Snapshot immutability: same-date changed-content raises SnapshotConflictError.
# 4. Independent artifact validator rules for MARKET_REGIME snapshot.
# 5. `astock today` displays the persisted market regime value.
#


REGIME_SNAPSHOT_ROOT = Path(__file__).resolve().parents[2]


REGIME_SNAPSHOT_FIXTURE_CSV = REGIME_SNAPSHOT_ROOT / "tests" / "fixtures" / "csv"


CONFIGS = REGIME_SNAPSHOT_ROOT / "configs"


MRG_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


REGIME_SNAPSHOT_BENCHMARK_ID = "000985.CSI"


runner = CliRunner()


def _benchmark_bars(count: int = 70) -> tuple[DailyBar, ...]:
    p = REGIME_SNAPSHOT_FIXTURE_CSV / "daily_bars_long.csv"
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        dates = sorted({date.fromisoformat(row["trade_date"]) for row in reader})
    selected_dates = dates[-count:]
    return tuple(
        DailyBar(
            symbol=REGIME_SNAPSHOT_BENCHMARK_ID,
            trade_date=d,
            open=3000.0,
            high=3050.0,
            low=2950.0,
            close=3000.0 + i,
            volume=100000.0,
            amount=1000000.0,
        )
        for i, d in enumerate(selected_dates)
    )


def _run_pipeline(store: JsonSnapshotStore, job_store: JsonJobStore) -> None:
    factor_configs = tuple(
        load_factor_config(path)
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    active_qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    run_daily(
        csv_root=REGIME_SNAPSHOT_FIXTURE_CSV,
        as_of=MRG_AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars_long",
        qualifiers=active_qualifiers,
        benchmark_id=REGIME_SNAPSHOT_BENCHMARK_ID,
        benchmark_bars=_benchmark_bars(70),
    )


def test_step1_daily_pipeline_writes_exactly_one_market_regime_record(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    _run_pipeline(store, job_store)

    # 1. 验证 MARKET_REGIME 快照文件被实际写入
    snap_path = store.path_for(SnapshotKind.MARKET_REGIME, MRG_AS_OF)
    assert snap_path.is_file(), f"Expected snapshot file at {snap_path}"

    # 2. 验证 store 能够查出日期
    assert MRG_AS_OF.date().isoformat() in store.dates(SnapshotKind.MARKET_REGIME)

    # 3. 验证记录数量恰好为 1
    records = store.read(SnapshotKind.MARKET_REGIME, MRG_AS_OF)
    assert len(records) == 1, f"Expected exactly 1 record, got {len(records)}"

    rec = records[0]
    assert isinstance(rec, dict)
    assert rec["regime"] in {
        "BULL",
        "RANGE_UP",
        "RANGE",
        "RANGE_DOWN",
        "BEAR",
        "EXTREME_VOLATILITY",
    }
    assert rec["breadth_ratio"] is not None
    assert rec["index_trend"] is not None
    assert isinstance(rec["reasons"], list)
    assert len(rec["reasons"]) > 0


def test_step2_market_regime_snapshot_carries_lineage_regime_version(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    _run_pipeline(store, job_store)

    records = store.read(SnapshotKind.MARKET_REGIME, MRG_AS_OF)
    assert len(records) == 1
    rec = records[0]
    assert "lineage" in rec
    lineage = rec["lineage"]
    assert isinstance(lineage, dict)
    assert lineage.get("regime_version") == "v1"


def test_step3_same_date_changed_content_raises_snapshot_conflict(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    # 先写入一个同日期的不同内容快照
    conflicting_record = MarketRegimeResult(
        as_of=MRG_AS_OF,
        regime=MarketRegime.BEAR,
        breadth_ratio=0.1,
        index_trend=0.8,
        reasons=("pre-existing contradictory regime",),
        lineage=SnapshotLineage(regime_version="v0_conflict"),
    )
    store.write(SnapshotKind.MARKET_REGIME, MRG_AS_OF, [conflicting_record])

    # 再次尝试直接写入不同记录应当抛出 SnapshotConflictError
    another_record = MarketRegimeResult(
        as_of=MRG_AS_OF,
        regime=MarketRegime.BULL,
        breadth_ratio=0.9,
        index_trend=1.2,
        reasons=("conflicting bull regime",),
        lineage=SnapshotLineage(regime_version="v1"),
    )
    with pytest.raises(SnapshotConflictError):
        store.write(SnapshotKind.MARKET_REGIME, MRG_AS_OF, [another_record])

    # 通过 pipeline 执行也必须在 DETECT_REGIME 阶段抛出冲突阻断
    result = run_daily(
        csv_root=REGIME_SNAPSHOT_FIXTURE_CSV,
        as_of=MRG_AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=tuple(
            load_factor_config(p) for p in sorted((CONFIGS / "factors").glob("*.yaml"))
        ),
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=store,
        job_store=job_store,
        dataset="daily_bars_long",
        qualifiers=load_canonical_qualifiers(),
        benchmark_id=REGIME_SNAPSHOT_BENCHMARK_ID,
        benchmark_bars=_benchmark_bars(70),
    )
    regime_run = next(
        run for run in result.runs if run.job_type is JobStage.DETECT_REGIME
    )
    assert regime_run.status is JobStatus.FAILED
    assert regime_run.error is not None
    assert "SnapshotConflictError" in regime_run.error
    assert SnapshotKind.MARKET_REGIME.value in regime_run.error


def test_step5_artifact_validator_for_market_regime() -> None:
    # 1. 干净的合法记录
    clean_record = {
        "as_of": MRG_AS_OF.isoformat(),
        "regime": "BULL",
        "breadth_ratio": 0.65,
        "index_trend": 1.05,
        "reasons": ["宽度走强", "指数上行"],
        "lineage": {"regime_version": "v1"},
    }
    findings = validate_snapshot("MARKET_REGIME", [clean_record], as_of=MRG_AS_OF)
    assert findings == (), f"Expected clean findings, got {findings}"

    # 2. 缺失必填字段 (缺少 reasons)
    incomplete_record = {
        "as_of": MRG_AS_OF.isoformat(),
        "regime": "BULL",
        "breadth_ratio": 0.65,
        "index_trend": 1.05,
        "lineage": {"regime_version": "v1"},
    }
    incomplete_findings = validate_snapshot(
        "MARKET_REGIME", [incomplete_record], as_of=MRG_AS_OF
    )
    assert any(f.check == "required_keys" for f in incomplete_findings)

    # 3. 记录条数不为 1 (例如空快照或 2 条)
    empty_findings = validate_snapshot("MARKET_REGIME", [], as_of=MRG_AS_OF)
    assert any(f.check == "market_regime_count" for f in empty_findings)

    multi_findings = validate_snapshot(
        "MARKET_REGIME", [clean_record, clean_record], as_of=MRG_AS_OF
    )
    assert any(f.check == "market_regime_count" for f in multi_findings)

    # 4. 非法词表
    bad_vocab_record = dict(clean_record, regime="UNKNOWN_REGIME")
    bad_vocab_findings = validate_snapshot(
        "MARKET_REGIME", [bad_vocab_record], as_of=MRG_AS_OF
    )
    assert any(f.check == "regime_vocabulary" for f in bad_vocab_findings)

    # 5. 空版本号
    empty_ver_record = dict(clean_record, lineage={"regime_version": ""})
    empty_ver_findings = validate_snapshot(
        "MARKET_REGIME", [empty_ver_record], as_of=MRG_AS_OF
    )
    assert any(f.check == "empty_version" for f in empty_ver_findings)


def test_step6_seed_market_regime_and_candidate_today_cli_prints_it(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)

    # 写入 MARKET_REGIME 快照
    regime_record = MarketRegimeResult(
        as_of=MRG_AS_OF,
        regime=MarketRegime.BULL,
        breadth_ratio=0.72,
        index_trend=1.08,
        reasons=("全市场宽度强劲", "基准指数走多"),
        lineage=SnapshotLineage(regime_version="v1"),
    )
    store.write(SnapshotKind.MARKET_REGIME, MRG_AS_OF, [regime_record])

    # 写入 CANDIDATE 快照
    candidate = Candidate(
        symbol="600519.SH",
        as_of=MRG_AS_OF,
        next_action=NextAction.WATCH,
        lineage=SnapshotLineage(
            strategy_version="v1",
            qualification_version="v1",
            candidate_policy_version="v1",
            regime_version="v1",
            market_validation_version="v1",
            signal_version="v1",
            universe_snapshot="2026-09-04:u1",
        ),
        primary_strategy_id="momentum",
        strategy_qualifications=(
            StrategyQualification(
                symbol="600519.SH",
                strategy_id="momentum",
                strategy_version="v1",
                qualification_version="v1",
                qualified=True,
                percentile_pass=True,
                absolute_pass=True,
                rank_percentile=0.98,
                as_of=MRG_AS_OF,
            ),
        ),
        strategy_results=(
            StrategyResult(
                symbol="600519.SH",
                strategy_id="momentum",
                strategy_version="v1",
                as_of=MRG_AS_OF,
                eligible=True,
                score=92.0,
                rank_percentile=0.98,
                lineage=SnapshotLineage(strategy_version="v1"),
            ),
        ),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.BREAKOUT,
        reasons=("qualified momentum breakout",),
        risks=(),
    )
    store.write(SnapshotKind.CANDIDATE, MRG_AS_OF, [candidate])

    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))
    result = runner.invoke(app, ["today", "--as-of", "2026-09-04"])
    assert result.exit_code == 0, result.output
    output = result.output

    assert "as_of: 2026-09-04" in output
    assert "candidates: 1" in output
    assert "market_regime: BULL" in output


# ===========================================================================
# 来源：tests/integration/test_market_signal_pipeline.py（1 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


SIGNAL_PIPELINE_SHANGHAI = ZoneInfo("Asia/Shanghai")


SIGNAL_PIPELINE_AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SIGNAL_PIPELINE_SHANGHAI)


def _signal_pipeline_fr(symbol: str, factor: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=SIGNAL_PIPELINE_AS_OF,
        status=DataStatus.VALUE,
        raw_value=value,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
    )


def test_market_signal_pipeline_end_to_end_assembly() -> None:
    """端到端验证：市场环境判定 -> 5维市场验证 (一票否决) -> 信号检测 -> Candidate 闭环生成。"""
    # 1. 构造标的因子
    # 标的 A (300741.SZ): 极端动量突破样本，流动性充沛，趋势优良 -> CONFIRMED + BREAKOUT -> 入选 Candidate
    # 标的 B (688525.SH): 成长策略，但严重破位大跌 (20日跌-20%, 60日跌-35%) -> CONTRADICTED + BREAKDOWN -> 一票否决
    # 标的 C (000526.SZ): 流动性不足 (0.8亿 < 1.0亿) -> CONTRADICTED -> 一票否决
    factors = (
        # 300741.SZ
        _signal_pipeline_fr("300741.SZ", "avg_amount_20d", 400_000_000.0),
        _signal_pipeline_fr("300741.SZ", "ret_20d", 0.35),
        _signal_pipeline_fr("300741.SZ", "ret_60d", 0.50),
        _signal_pipeline_fr("300741.SZ", "proximity_52w_high", 0.98),
        # 688525.SH
        _signal_pipeline_fr("688525.SH", "avg_amount_20d", 300_000_000.0),
        _signal_pipeline_fr("688525.SH", "ret_20d", -0.20),
        _signal_pipeline_fr("688525.SH", "ret_60d", -0.35),
        _signal_pipeline_fr("688525.SH", "proximity_52w_high", 0.50),
        # 000526.SZ
        _signal_pipeline_fr("000526.SZ", "avg_amount_20d", 80_000_000.0),
        _signal_pipeline_fr("000526.SZ", "ret_20d", 0.05),
        _signal_pipeline_fr("000526.SZ", "ret_60d", 0.10),
        _signal_pipeline_fr("000526.SZ", "proximity_52w_high", 0.88),
    )

    symbols = ["300741.SZ", "688525.SH", "000526.SZ"]

    strategy_results = (
        StrategyResult(
            symbol="300741.SZ",
            strategy_id="momentum",
            strategy_version="v1",
            as_of=SIGNAL_PIPELINE_AS_OF,
            eligible=True,
            score=0.95,
            rank_percentile=0.98,
            lineage=SnapshotLineage(strategy_version="v1"),
        ),
        StrategyResult(
            symbol="688525.SH",
            strategy_id="growth",
            strategy_version="v1",
            as_of=SIGNAL_PIPELINE_AS_OF,
            eligible=True,
            score=0.92,
            rank_percentile=0.95,
            lineage=SnapshotLineage(strategy_version="v1"),
        ),
        StrategyResult(
            symbol="000526.SZ",
            strategy_id="momentum",
            strategy_version="v1",
            as_of=SIGNAL_PIPELINE_AS_OF,
            eligible=True,
            score=0.88,
            rank_percentile=0.91,
            lineage=SnapshotLineage(strategy_version="v1"),
        ),
    )

    qualifications = (
        StrategyQualification(
            symbol="300741.SZ",
            strategy_id="momentum",
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=0.98,
        ),
        StrategyQualification(
            symbol="688525.SH",
            strategy_id="growth",
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=0.95,
        ),
        StrategyQualification(
            symbol="000526.SZ",
            strategy_id="momentum",
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=0.91,
        ),
    )

    # 1. 运行市场环境阶段
    regime_res = market_regime_stage(
        as_of=SIGNAL_PIPELINE_AS_OF,
        breadth_ratio=0.62,
        index_trend=0.03,
    )
    assert regime_res.regime == MarketRegime.BULL

    # 2. 运行市场验证阶段（提供完整的5维证据）
    validation_results = market_validation_stage(
        symbols=symbols,
        factor_results=factors,
        as_of=SIGNAL_PIPELINE_AS_OF,
        strategy_by_symbol={s: "momentum" for s in symbols},
        vol_ratio_by_symbol={
            "300741.SZ": 1.5,
            "688525.SH": 0.6,
            "000526.SZ": 1.0,
        },
        industry_excess_by_symbol={
            "300741.SZ": 0.15,
            "688525.SH": -0.15,
            "000526.SZ": 0.01,
        },
        relative_strength_by_symbol={
            "300741.SZ": 0.20,
            "688525.SH": -0.25,
            "000526.SZ": 0.05,
        },
    )
    assert len(validation_results) == 3
    mv_map = {r.symbol: r.status for r in validation_results}
    assert mv_map["300741.SZ"] == MarketValidation.CONFIRMED
    assert mv_map["688525.SH"] == MarketValidation.CONTRADICTED  # 破位负向 >= 2
    assert mv_map["000526.SZ"] == MarketValidation.CONTRADICTED  # 流动性警戒线一票否决

    # 3. 运行技术信号阶段
    signal_results = signal_stage(
        symbols=symbols,
        factor_results=factors,
        as_of=SIGNAL_PIPELINE_AS_OF,
        strategy_by_symbol={s: "momentum" for s in symbols},
        market_regime=regime_res.regime,
    )
    assert len(signal_results) == 3
    sig_map = {r.symbol: r.signal for r in signal_results}
    assert sig_map["300741.SZ"] == Signal.BREAKOUT
    assert sig_map["688525.SH"] == Signal.BREAKDOWN

    # 4. 运行 Candidate 装配阶段 (搭配真实 RepresentativeCandidatePolicy)
    policy = RepresentativeCandidatePolicy(
        version="v1", soft_reserve_per_strategy=1, max_candidates=10
    )
    lineage = SnapshotLineage(
        factor_version="v1",
        strategy_version="v1",
        qualification_version="v1",
        regime_version="v1",
        signal_version="v1",
        candidate_policy_version="v1",
    )

    candidates = candidate_stage(
        strategy_results=strategy_results,
        qualifications=qualifications,
        market_validation_by_symbol=mv_map,
        signal_by_symbol=sig_map,
        lineage=lineage,
        as_of=SIGNAL_PIPELINE_AS_OF,
        policy=policy,
    )

    # 验证候选结果：只有 300741.SZ 通过验证进入候选集，其余被 CONTRADICTED 一票否决
    assert len(candidates) == 1
    c = candidates[0]
    assert c.symbol == "300741.SZ"
    assert c.market_validation == MarketValidation.CONFIRMED
    assert c.signal == Signal.BREAKOUT
    assert c.lineage.regime_versions() == frozenset({"v1"})
    assert c.lineage.signal_versions() == frozenset({"v1"})


# ===========================================================================
# 来源：tests/integration/test_post_valuation_analysis_flow.py（2 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 最新估值进入正式策略快照的等价链路测试（任务 3）。
#
# 规格：`docs/superpowers/specs/2026-09-20-candidate-readiness-upgrade-design.md`
# 计划：`docs/superpowers/plans/2026-09-20-valuation-to-qualification-readiness-implementation-plan.md` 任务 3。
#
# 钉住的关键不变量：
# 1. 形式快照与只读分析等价：同一时点、同一输入下，正式 FACTOR/STRATEGY 快照内容
#    与只读研究分析结果语义完全一致；
# 2. 时点隔离：新日期的估值变化只改变估值相关因子与策略（Value/GARP），不改变纯成长因子；
# 3. 候选门禁持续生效：未批准绝对质量规则前，Candidate 保持为空且 BUILD_CANDIDATES 阶段 BLOCKED。
#


ROOT = Path(__file__).resolve().parents[2]


PV_CONFIGS = ROOT / "configs"


OLD_AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


NEW_AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


def _setup_raw_root(root: Path) -> None:
    """构建包含日线、证券、财务与两期估值的完整测试环境。"""
    root.mkdir(parents=True, exist_ok=True)
    # 1. securities.csv
    sec_content = (
        "symbol,name,exchange,list_date,is_st,is_delisting_board,suspended_trading_days\n"
        "000001.SZ,平安银行,SZSE,1991-04-03,false,false,0\n"
        "000002.SZ,万科A,SZSE,1991-01-29,false,false,0\n"
    )
    (root / "securities.csv").write_text(sec_content, encoding="utf-8")

    # 2. daily_bars.csv (两只标的各提供 25 天日线，成交额 2 亿满足流动性门槛)
    bar_rows = [
        "symbol,trade_date,open,high,low,close,pre_close,volume,amount,turnover_rate,pct_change,adj_factor"
    ]
    for day in range(1, 26):
        d_str = f"2026-08-{day:02d}"
        bar_rows.append(
            f"000001.SZ,{d_str},10.0,10.5,9.8,10.0,10.0,20000000.0,200000000.0,0.01,0.0,1.0"
        )
        bar_rows.append(
            f"000002.SZ,{d_str},20.0,20.5,19.8,20.0,20.0,10000000.0,200000000.0,0.01,0.0,1.0"
        )
    # 最近的交易日 2026-09-17
    bar_rows.append(
        "000001.SZ,2026-09-17,10.0,10.5,9.8,10.0,10.0,20000000.0,200000000.0,0.01,0.0,1.0"
    )
    bar_rows.append(
        "000002.SZ,2026-09-17,20.0,20.5,19.8,20.0,20.0,10000000.0,200000000.0,0.01,0.0,1.0"
    )
    (root / "daily_bars.csv").write_text("\n".join(bar_rows) + "\n", encoding="utf-8")

    # 3. 财务报表 (包含 3 年历史以支持 CAGR 计算)
    # Income
    inc_rows = [
        "code,EndDate,InfoPublDate,OperatingRevenue,ParentNetProfit,GrossIncomeRatio",
        "sz000001,2026-06-30,2026-08-15,50000000000.0,15000000000.0,40.0",
        "sz000001,2025-06-30,2025-08-15,45000000000.0,13000000000.0,40.0",
        "sz000001,2024-06-30,2024-08-15,40000000000.0,11000000000.0,40.0",
        "sz000001,2023-06-30,2023-08-15,35000000000.0,9000000000.0,40.0",
        "sz000002,2026-06-30,2026-08-15,30000000000.0,8000000000.0,35.0",
        "sz000002,2025-06-30,2025-08-15,27000000000.0,7000000000.0,35.0",
        "sz000002,2024-06-30,2024-08-15,24000000000.0,6000000000.0,35.0",
        "sz000002,2023-06-30,2023-08-15,21000000000.0,5000000000.0,35.0",
    ]
    (root / "financial_income.csv").write_text(
        "\n".join(inc_rows) + "\n", encoding="utf-8"
    )

    # Balance
    bal_rows = [
        "code,EndDate,InfoPublDate,TotalAssets,TotalLiabilities,ParentEquity",
        "sz000001,2026-06-30,2026-08-15,500000000000.0,400000000000.0,100000000000.0",
        "sz000002,2026-06-30,2026-08-15,300000000000.0,200000000000.0,100000000000.0",
    ]
    (root / "financial_balance.csv").write_text(
        "\n".join(bal_rows) + "\n", encoding="utf-8"
    )

    # Cashflow
    cash_rows = [
        "code,EndDate,InfoPublDate,NetOperatingCashFlow",
        "sz000001,2026-06-30,2026-08-15,12000000000.0",
        "sz000002,2026-06-30,2026-08-15,7000000000.0",
    ]
    (root / "financial_cashflow.csv").write_text(
        "\n".join(cash_rows) + "\n", encoding="utf-8"
    )

    # 4. neodata 估值数据 (两期: 2026-09-17 与 2026-09-19)
    val_dir = root / "neodata" / "valuation"
    val_dir.mkdir(parents=True, exist_ok=True)

    def _val_csv(pe1: float, peg1: float, pe2: float, peg2: float) -> str:
        b1 = (
            "**标的代码（统一输出字段名）**: 000001.SZ\n\n"
            "  **标的名称**: 平安银行\n\n"
            f"  **滚动市盈率（倍）**: {pe1}\n\n"
            "  **市盈率历史分位数（%）**: 50.0\n\n"
            "  **市净率（倍）**: 1.0\n\n"
            "  **市净率历史分位数（%）**: 50.0\n\n"
            "  **个股历史估值时序数据列表（仅股票历史模式）**:\n\n"
            "  | 估值日期（YYYYMMDD） | 静态市盈率（倍） | 动态市盈率（倍） | 扣非后滚动市盈率（倍） | 滚动市销率（倍） | 静态市销率（倍） | 动态市销率（倍） | 滚动市现率-经营现金流（倍） | 静态市现率-经营现金流（倍） | 动态市现率-经营现金流（倍） | 静态市现率-现金流净额（倍） | 动态市现率-现金流净额（倍） | 静态股息率（%） | 滚动股息率（%） | 企业价值（亿元） | PEG（市盈率相对盈利增长比率） |\n"
            "  | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
            f"  | 20260916 | -- | 10.0 | 10.0 | 2.0 | -- | 2.0 | 5.0 | -- | 5.0 | -- | -- | -- | -- | 1000.0 | {peg1} |\n"
        )
        b2 = (
            "**标的代码（统一输出字段名）**: 000002.SZ\n\n"
            "  **标的名称**: 万科A\n\n"
            f"  **滚动市盈率（倍）**: {pe2}\n\n"
            "  **市盈率历史分位数（%）**: 40.0\n\n"
            "  **市净率（倍）**: 0.8\n\n"
            "  **市净率历史分位数（%）**: 40.0\n\n"
            "  **个股历史估值时序数据列表（仅股票历史模式）**:\n\n"
            "  | 估值日期（YYYYMMDD） | 静态市盈率（倍） | 动态市盈率（倍） | 扣非后滚动市盈率（倍） | 滚动市销率（倍） | 静态市销率（倍） | 动态市销率（倍） | 滚动市现率-经营现金流（倍） | 静态市现率-经营现金流（倍） | 动态市现率-经营现金流（倍） | 静态市现率-现金流净额（倍） | 动态市现率-现金流净额（倍） | 静态股息率（%） | 滚动股息率（%） | 企业价值（亿元） | PEG（市盈率相对盈利增长比率） |\n"
            "  | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
            f"  | 20260916 | -- | 8.0 | 8.0 | 1.5 | -- | 1.5 | 4.0 | -- | 4.0 | -- | -- | -- | -- | 800.0 | {peg2} |\n"
        )
        escaped1 = b1.replace('"', '""')
        escaped2 = b2.replace('"', '""')
        return (
            "type,desc,content\n"
            f'统一估值查询,统一估值查询,"{escaped1}"\n'
            f'统一估值查询,统一估值查询,"{escaped2}"\n'
        )

    (val_dir / "2026-09-17.csv").write_text(
        _val_csv(5.0, 1.2, 4.0, 0.9), encoding="utf-8"
    )
    (val_dir / "2026-09-19.csv").write_text(
        _val_csv(8.0, 1.8, 6.0, 1.3), encoding="utf-8"
    )

    # 5. benchmark 与 industry 证据
    import shutil

    csv_fixture = ROOT / "tests" / "fixtures" / "csv"
    bm_src = csv_fixture / "benchmark_bars.csv"
    if bm_src.is_file():
        shutil.copy(bm_src, root / "benchmark_bars.csv")

    ind_dir = root / "westock" / "industry"
    ind_dir.mkdir(parents=True, exist_ok=True)
    ind_src = csv_fixture / "westock" / "industry" / "2026-09-04.csv"
    if ind_src.is_file():
        shutil.copy(ind_src, ind_dir / "2026-09-04.csv")
        shutil.copy(ind_src, ind_dir / "2026-09-17.csv")
        shutil.copy(ind_src, ind_dir / "2026-09-19.csv")


def _canonical_factors(
    factors: tuple[FactorResult, ...], symbols: tuple[str, ...]
) -> tuple[tuple[object, ...], ...]:
    sym_set = set(symbols)
    return tuple(
        sorted(
            (f.symbol, f.factor, f.status.value, f.raw_value)
            for f in factors
            if f.symbol in sym_set
        )
    )


def _canonical_strategies(
    strategies: tuple[StrategyResult, ...], symbols: tuple[str, ...]
) -> tuple[tuple[object, ...], ...]:
    sym_set = set(symbols)
    return tuple(
        sorted(
            (s.strategy_id, s.symbol, s.eligible, s.score, s.rank_percentile)
            for s in strategies
            if s.symbol in sym_set
        )
    )


def test_formal_snapshot_equals_verified_readonly_analysis(local_tmp: Path) -> None:
    """证明正式管线写入的 FACTOR/STRATEGY 快照与只读研究分析结果语义完全一致。"""
    raw_root = local_tmp / "raw"
    _setup_raw_root(raw_root)

    u_cfg = load_universe_config(PV_CONFIGS / "universe.yaml")
    f_cfgs = tuple(
        load_factor_config(p) for p in sorted((PV_CONFIGS / "factors").glob("*.yaml"))
    )
    scanners = load_scanners(PV_CONFIGS / "strategies")

    # 1. 只读分析 (Research Analysis)
    research, preview = run_research_analysis(
        csv_root=raw_root,
        as_of=NEW_AS_OF,
        universe_config=u_cfg,
        factor_configs=f_cfgs,
        scanners=scanners,
    )

    # 2. 正式管线 (run_daily)
    formal = run_daily(
        csv_root=raw_root,
        as_of=NEW_AS_OF,
        universe_config=u_cfg,
        factor_configs=f_cfgs,
        scanners=scanners,
        strategy_directory=PV_CONFIGS / "strategies",
        store=JsonSnapshotStore(local_tmp / "snapshots"),
        job_store=JsonJobStore(local_tmp / "jobs"),
        candidate_policy=None,
        qualifiers=None,
    )

    symbols = research.research_symbols
    assert len(symbols) == 2
    assert set(symbols) == {"000001.SZ", "000002.SZ"}

    # 等价性断言
    assert _canonical_factors(formal.factor_results, symbols) == _canonical_factors(
        preview.factor_results, symbols
    )
    assert _canonical_strategies(
        formal.strategy_results, symbols
    ) == _canonical_strategies(preview.strategy_results, symbols)

    # 候选门禁断言：BUILD_CANDIDATES BLOCKED，无候选发布
    assert formal.candidates == ()
    assert JobStage.BUILD_CANDIDATES in formal.blocked_stages


def test_newer_valuation_changes_only_valuation_dependent_evidence(
    local_tmp: Path,
) -> None:
    """证明新估值生效只改变估值相关因子与策略结果，纯成长因子与结果保持不变。"""
    raw_root = local_tmp / "raw"
    _setup_raw_root(raw_root)

    u_cfg = load_universe_config(PV_CONFIGS / "universe.yaml")
    f_cfgs = tuple(
        load_factor_config(p) for p in sorted((PV_CONFIGS / "factors").glob("*.yaml"))
    )
    scanners = load_scanners(PV_CONFIGS / "strategies")

    _, old_run = run_research_analysis(
        csv_root=raw_root,
        as_of=OLD_AS_OF,
        universe_config=u_cfg,
        factor_configs=f_cfgs,
        scanners=scanners,
    )

    _, new_run = run_research_analysis(
        csv_root=raw_root,
        as_of=NEW_AS_OF,
        universe_config=u_cfg,
        factor_configs=f_cfgs,
        scanners=scanners,
    )

    old_factors = {(f.symbol, f.factor): f for f in old_run.factor_results}
    new_factors = {(f.symbol, f.factor): f for f in new_run.factor_results}

    # 1. 估值因子发生变化
    assert old_factors[("000001.SZ", "pe_ttm")].raw_value == 5.0
    assert new_factors[("000001.SZ", "pe_ttm")].raw_value == 8.0
    assert old_factors[("000001.SZ", "peg")].raw_value == 1.2
    assert new_factors[("000001.SZ", "peg")].raw_value == 1.8

    # 2. 纯成长因子保持不变
    growth_factors = ("revenue_yoy", "net_profit_parent_yoy", "revenue_cagr_3y")
    for sym in ("000001.SZ", "000002.SZ"):
        for gf in growth_factors:
            assert old_factors[(sym, gf)].raw_value == new_factors[(sym, gf)].raw_value
            assert old_factors[(sym, gf)].status == new_factors[(sym, gf)].status


# ===========================================================================
# 来源：tests/integration/test_qualification_pipeline.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 资格管线集成测试：qualification_stage 必须读取股票完整 Factor 证据。
#
# 覆盖计划 Task 5 的四个场景：
# 1. Growth 资格能读到不在策略评分快照里的 ``roe_ttm``；
# 2. Growth 缺 ``roe_ttm`` 时失败关闭；
# 3. Dividend 单位回归：``dividend_paid_ratio``（单位 %）绝不参与绝对判定；
# 4. GARP 回归：``pe_ttm`` 参与绝对判定，``pe_percentile`` 不参与。
#
# 装配使用真实生产规则（``configs/qualifications``），以获得生产级强证据。
#


QUALIFICATION_PIPELINE_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


QUALIFIERS = load_canonical_qualifiers()


SYMBOL = "600000.SH"


def _qualification_pipeline_factor(
    name: str,
    value: float,
    *,
    symbol: str = SYMBOL,
    status: DataStatus = DataStatus.VALUE,
) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=QUALIFICATION_PIPELINE_AS_OF,
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
        as_of=QUALIFICATION_PIPELINE_AS_OF,
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
            _qualification_pipeline_factor("revenue_yoy", 8.0),
            _qualification_pipeline_factor("revenue_cagr_3y", 6.0),
            _qualification_pipeline_factor("net_profit_parent_yoy", 20.0),
            _qualification_pipeline_factor("net_profit_parent_cagr_3y", 12.0),
        ),
    )
    factor_results = (
        _qualification_pipeline_factor("net_profit_parent_yoy", 20.0),
        _qualification_pipeline_factor("revenue_yoy", 8.0),
        _qualification_pipeline_factor("roe_ttm", 9.0),
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
            _qualification_pipeline_factor("revenue_yoy", 8.0),
            _qualification_pipeline_factor("net_profit_parent_yoy", 20.0),
        ),
    )
    factor_results = (
        _qualification_pipeline_factor("net_profit_parent_yoy", 20.0),
        _qualification_pipeline_factor("revenue_yoy", 8.0),
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
            _qualification_pipeline_factor("dividend_paid_ratio", 79.0),
        ),
    )
    factor_results = (
        _qualification_pipeline_factor("dividend_yield_ttm", 3.5),
        _qualification_pipeline_factor("dividend_payout_ttm", 0.50),
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
            _qualification_pipeline_factor("net_profit_parent_yoy", 20.0),
            _qualification_pipeline_factor("roe_ttm", 12.0),
        ),
    )
    factor_results = (
        _qualification_pipeline_factor("pe_ttm", 30.0),
        _qualification_pipeline_factor("net_profit_parent_yoy", 20.0),
        _qualification_pipeline_factor("roe_ttm", 12.0),
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
        _qualification_pipeline_factor("pe_ttm", 40.0),
        _qualification_pipeline_factor("net_profit_parent_yoy", 20.0),
        _qualification_pipeline_factor("roe_ttm", 12.0),
    )
    qualifications_fail = qualification_stage(
        strategy_results=(garp_result,),
        factor_results=expensive,
        qualifiers=QUALIFIERS,
    )
    assert qualifications_fail[0].absolute_pass is False
    assert any("pe_ttm" in risk for risk in qualifications_fail[0].risks)


# ===========================================================================
# 来源：tests/integration/test_research_universe_flow.py（8 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Cold-start bootstrap for a broad listing.
#
# A whole-market cold start cannot be one long all-or-nothing fetch: a single bad
# symbol would lose the work of every symbol before it, and a rerun would start
# over. These tests pin the three properties that make the flow usable —
# per-symbol failure isolation, resume by coverage rather than by restart, and a
# success condition measured in valid bars instead of calendar days.
#
# The provider is a fake on purpose: a test that reaches AkShare would report
# whether the network is up, not whether the flow is correct.
#


RESEARCH_UNIVERSE_AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


END_DATE = date(2026, 9, 17)


BAR_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
)


class FakeBarProvider:
    """Serves one symbol's history on demand, and can be told to fail.

    `histories` maps a symbol to (first day with data, days between rows). A
    step greater than one stands for a sparse instrument whose history fills a
    calendar window more slowly than a daily one.
    """

    def __init__(
        self,
        histories: dict[str, tuple[date, int]],
        *,
        failing: set[str] | None = None,
    ) -> None:
        self.histories = histories
        self.failing = set(failing or ())
        self.requests: list[tuple[str, date, date]] = []

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        self.requests.append((symbol, start_date, end_date))
        fetched_at = datetime.now(UTC)
        first, step = self.histories.get(symbol, (end_date, 1))

        if symbol in self.failing:
            return RawDataset(
                provider="fake",
                dataset="daily_bars",
                fetched_at=fetched_at,
                provider_version="test",
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
                message=f"{symbol} could not be fetched",
            )

        rows: list[tuple[str, ...]] = []
        day = first
        while day <= end_date:
            if day >= start_date:
                rows.append(
                    (symbol, day.isoformat(), "1", "1", "1", "1", "1", "1000", "0.01")
                )
            day += timedelta(days=step)

        if not rows:
            return RawDataset(
                provider="fake",
                dataset="daily_bars",
                fetched_at=fetched_at,
                provider_version="test",
                status=DataStatus.NULL,
                row_count=0,
            )
        return RawDataset(
            provider="fake",
            dataset="daily_bars",
            fetched_at=fetched_at,
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=BAR_COLUMNS, rows=tuple(rows)),
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        raise AssertionError("the bootstrap flow must use fetch_symbol_bars")


def _bars_path(root: Path) -> Path:
    return root / "daily_bars.csv"


def _parts_dir(root: Path) -> Path:
    return root / "bootstrap" / END_DATE.isoformat() / "parts"


def _checkpoint(root: Path) -> BootstrapCheckpoint:
    """每块落地都经检查点落分片，所以每个调用点都要传入它。"""
    return BootstrapCheckpoint(root, as_of=END_DATE, required_valid_bars=20)


def _staged_symbols(root: Path) -> set[str]:
    parts = _parts_dir(root)
    if not parts.is_dir():
        return set()
    return {path.stem for path in parts.glob("*.csv")}


def _symbols_in_file(path: Path) -> set[str]:
    columns, rows = read_raw_rows(path)
    if "symbol" not in columns:
        return set()
    index = columns.index("symbol")
    return {row[index] for row in rows}


def test_a_failed_symbol_keeps_the_symbols_that_succeeded(
    local_tmp: Path,
) -> None:
    provider = FakeBarProvider(
        {
            "000001.SZ": (date(2026, 8, 1), 1),
            "600519.SH": (date(2026, 8, 1), 1),
            "300750.SZ": (date(2026, 8, 1), 1),
        },
        failing={"600519.SH"},
    )

    result = land_bar_chunks(
        fallback_source=provider,
        root=local_tmp,
        as_of=RESEARCH_UNIVERSE_AS_OF,
        symbols=("000001.SZ", "600519.SH", "300750.SZ"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        batch_size=2,
        checkpoint=_checkpoint(local_tmp),
    )

    assert isinstance(result, ChunkSyncResult)
    assert result.completed_symbols == ("000001.SZ", "300750.SZ")
    assert result.failed_symbols == ("600519.SH",)
    assert result.rows_written > 0
    # The failure is visible in the file's absence of the symbol, never as a
    # row of invented values.
    assert _symbols_in_file(_bars_path(local_tmp)) == {"000001.SZ", "300750.SZ"}


def test_a_rerun_retries_only_the_coverage_that_is_missing(local_tmp: Path) -> None:
    histories = {
        "000001.SZ": (date(2026, 8, 1), 1),
        "600519.SH": (date(2026, 8, 1), 1),
    }
    first_run = FakeBarProvider(histories, failing={"600519.SH"})
    land_bar_chunks(
        fallback_source=first_run,
        root=local_tmp,
        as_of=RESEARCH_UNIVERSE_AS_OF,
        symbols=("000001.SZ", "600519.SH"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        batch_size=10,
        checkpoint=_checkpoint(local_tmp),
    )

    second_run = FakeBarProvider(histories)
    result = land_bar_chunks(
        fallback_source=second_run,
        root=local_tmp,
        as_of=RESEARCH_UNIVERSE_AS_OF,
        symbols=("000001.SZ", "600519.SH"),
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        batch_size=10,
        checkpoint=_checkpoint(local_tmp),
    )

    assert [symbol for symbol, _, _ in second_run.requests] == ["600519.SH"]
    assert result.completed_symbols == ("600519.SH",)
    assert _symbols_in_file(_bars_path(local_tmp)) == {"000001.SZ", "600519.SH"}


def test_a_finished_symbol_is_on_disk_before_the_scheduler_forgets_it(
    local_tmp: Path,
) -> None:
    """Persistence per completion is what makes a crash resumable.

    落盘的形状变了两次（分片 + 清单；有界完成顺序调度），要钉住的性质没变：一有标的完成
    就得先在磁盘上，之后才能腾出 in-flight 名额去请求下一只。
    """
    symbols = ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ")
    seen_parts: list[set[str]] = []
    seen_file: list[bool] = []
    provider = FakeBarProvider({symbol: (date(2026, 8, 1), 1) for symbol in symbols})
    original = provider.fetch_symbol_bars
    max_inflight = 2

    def watching(symbol: str, *, as_of: datetime, start_date: date, end_date: date):
        seen_parts.append(_staged_symbols(local_tmp))
        seen_file.append(_bars_path(local_tmp).exists())
        return original(symbol, as_of=as_of, start_date=start_date, end_date=end_date)

    provider.fetch_symbol_bars = watching  # type: ignore[method-assign]

    land_bar_chunks(
        fallback_source=provider,
        root=local_tmp,
        as_of=RESEARCH_UNIVERSE_AS_OF,
        symbols=symbols,
        start_date=date(2026, 8, 1),
        end_date=END_DATE,
        batch_size=10,
        max_inflight=max_inflight,
        checkpoint=_checkpoint(local_tmp),
    )

    # 第 k 只标的被请求时，至少 k - max_inflight 只更早的标的已经把分片落在磁盘上：
    # 名额是靠"结果已消费"腾出来的，而消费就是先落盘、再记账。
    for requested, staged in enumerate(seen_parts, start=1):
        assert len(staged) >= max(requested - max_inflight, 0), (
            f"请求第 {requested} 只时只落盘了 {sorted(staged)}；"
            "完成的标的必须先落盘再让调度器继续提交"
        )
    assert seen_file == [False, False, False, False], (
        "整份 daily_bars.csv 不得在取数过程中被反复重写；它只在落地调用结束时压实一次"
    )


def test_short_history_is_extended_backward_until_it_is_enough(
    local_tmp: Path,
) -> None:
    provider = FakeBarProvider(
        {
            "600519.SH": (date(2026, 1, 1), 1),
            "300750.SZ": (date(2026, 6, 1), 3),
        }
    )
    requirement = BootstrapRequirement(
        factor_name="avg_amount_20d", required_valid_bars=20
    )

    result = bootstrap_liquidity_history(
        batch_source=None,
        fallback_source=provider,
        root=local_tmp,
        as_of=RESEARCH_UNIVERSE_AS_OF,
        symbols=("600519.SH", "300750.SZ"),
        requirement=requirement,
        end_date=END_DATE,
        batch_size=10,
    )

    sparse = next(item for item in result.coverage if item.symbol == "300750.SZ")
    assert sparse.valid_bars >= requirement.required_valid_bars
    assert sparse.satisfied is True
    # The sparse symbol needed a wider window than the first request carried.
    widths = {start for symbol, start, _ in provider.requests if symbol == "300750.SZ"}
    assert min(widths) < max(widths), "the flow must extend backward, not give up"


def test_history_that_runs_out_is_reported_short_not_padded(local_tmp: Path) -> None:
    provider = FakeBarProvider({"688981.SH": (date(2026, 9, 10), 1)})
    requirement = BootstrapRequirement(
        factor_name="avg_amount_20d", required_valid_bars=20
    )

    result = bootstrap_liquidity_history(
        batch_source=None,
        fallback_source=provider,
        root=local_tmp,
        as_of=RESEARCH_UNIVERSE_AS_OF,
        symbols=("688981.SH",),
        requirement=requirement,
        end_date=END_DATE,
        batch_size=10,
    )

    coverage = result.coverage[0]
    assert coverage.satisfied is False
    assert coverage.valid_bars == 8
    columns, rows = read_raw_rows(_bars_path(local_tmp))
    assert len(rows) == 8, "no row may be invented to reach the requirement"
    assert columns == BAR_COLUMNS


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "csv"


def _universe_config() -> UniverseConfig:
    return load_universe_config(
        Path(__file__).resolve().parents[2] / "configs" / "universe.yaml"
    )


def _factor_configs() -> tuple[FactorConfig, ...]:
    directory = Path(__file__).resolve().parents[2] / "configs" / "factors"
    return tuple(load_factor_config(path) for path in sorted(directory.glob("*.yaml")))


def test_the_research_universe_is_a_subset_of_the_listing_prefilter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two layers must agree: nothing reaches research that the prefilter dropped."""
    seen: list[tuple[str, ...]] = []
    original = analysis.factor_stage

    def watching(*, outcome, factor_configs, as_of):
        seen.append(tuple(config.name for config in factor_configs))
        return original(outcome=outcome, factor_configs=factor_configs, as_of=as_of)

    # Patch where the flow looks it up: `analysis` imported the stage directly.
    monkeypatch.setattr(analysis, "factor_stage", watching)

    state = compute_research_universe(
        csv_root=FIXTURE_ROOT,
        as_of=datetime(2026, 9, 4, 15, 0, tzinfo=UTC),
        universe_config=_universe_config(),
        factor_configs=_factor_configs(),
        dataset="daily_bars_long",
    )

    assert set(state.research_symbols) <= set(state.listing_prefilter_symbols)
    assert state.research_symbols, "the fixture carries symbols that must survive"
    assert seen == [("avg_amount_20d",)], (
        "deciding membership must compute the liquidity measure only, not all "
        f"24 factors; saw {seen}"
    )


def test_the_research_command_reports_an_observational_target_and_writes_nothing(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_root = local_tmp / "snapshots"
    watchlist_root = local_tmp / "watchlist"
    job_root = local_tmp / "jobs"
    for root in (snapshot_root, watchlist_root, job_root):
        root.mkdir()
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(FIXTURE_ROOT))
    monkeypatch.setenv("ASTOCK_DATASET", "daily_bars_long")
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snapshot_root))
    monkeypatch.setenv("ASTOCK_WATCHLIST_ROOT", str(watchlist_root))
    monkeypatch.setenv("ASTOCK_JOB_ROOT", str(job_root))

    result = CliRunner().invoke(app, ["universe", "research", "--as-of", "2026-09-04"])

    assert result.exit_code == 0, result.output
    assert "not a quota" in result.stdout
    assert "research universe" in result.stdout
    assert list(snapshot_root.iterdir()) == []
    assert list(watchlist_root.iterdir()) == []
    assert list(job_root.iterdir()) == []


SECURITIES_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "list_date",
    "is_st",
    "is_delisting_board",
    "suspended_trading_days",
]


def _write_listing(root: Path, *, broad: int, research: int) -> tuple[str, ...]:
    """Write a listing where only `research` symbols survive the prefilter.

    The other 60 are ST or too young, which is the cheapest way to build a
    broad/production-shaped split without inventing a business rule: those two
    exclusions already exist in `configs/universe.yaml`.
    """
    rows = [
        "symbol,name,exchange,list_date,is_st,is_delisting_board,suspended_trading_days"
    ]
    surviving: list[str] = []
    for index in range(broad):
        symbol = f"{index:06d}.SZ"
        if index < research:
            surviving.append(symbol)
            rows.append(f"{symbol},name{index},SZSE,2015-01-05,False,False,")
        elif index % 2 == 0:
            rows.append(f"{symbol},name{index},SZSE,2015-01-05,True,False,")
        else:
            rows.append(f"{symbol},name{index},SZSE,2026-09-10,False,False,")
    (root / "securities.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return tuple(surviving)


def _write_bars(root: Path, symbols: tuple[str, ...], *, days: int) -> None:
    rows = ["symbol,trade_date,open,high,low,close,volume,amount,turnover_rate"]
    for symbol in symbols:
        for offset in range(days):
            day = date(2026, 9, 17) - timedelta(days=offset)
            rows.append(f"{symbol},{day.isoformat()},10,11,9,10.5,1000,200000000,0.01")
    (root / "daily_bars.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


class RecordingProvider:
    """Narrow provider that records every symbol it was asked to enrich."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="recording",
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=datetime.now(UTC),
        )

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        self.asked.append(symbol)
        row = (symbol, end_date.isoformat(), "10", "11", "9", "10.5", "1", "1", "0.01")
        return RawDataset(
            provider="recording",
            dataset="daily_bars",
            fetched_at=datetime.now(UTC),
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=1,
            payload=RawPayload(columns=BAR_COLUMNS, rows=(row,)),
        )


def test_only_the_research_universe_is_asked_for_expensive_history(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """100 broad symbols / 40 research symbols: 40 requests, not 100."""
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_listing(csv_root, broad=100, research=40)
    _write_bars(csv_root, surviving, days=30)

    provider = RecordingProvider()
    monkeypatch.setattr("astock_lens.cli.app._bulk_provider", lambda: provider)
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(csv_root))

    result = CliRunner().invoke(app, ["sync-research", "--as-of", "2026-09-17"])

    assert result.exit_code == 0, result.output
    # The set is the claim, not the call count: a symbol short of history is
    # asked again with a wider window, and that retry is the resumable flow
    # working. What may never happen is a request for a symbol outside the
    # research population.
    assert set(provider.asked) == set(surviving), (
        "only the research population may be enriched; asked for "
        f"{sorted(set(provider.asked) - set(surviving))}"
    )
    assert len(set(provider.asked)) == 40
    # 命令自己给出进度（设计文档 §3.6）：外部 watcher 不再是唯一手段。
    assert "processed 40/40" in result.stdout, result.stdout
    assert "sym/s" in result.stdout, result.stdout
    assert "valuation enrichment: BLOCKED_PENDING_INDUSTRY_PATH" in result.stdout


# ===========================================================================
# 来源：tests/integration/test_stock_discovery_workflow.py（3 例）
# ===========================================================================
# # mypy: disable-error-code="import-untyped"
# 模块 docstring（逐字折为注释）：
# 每日策略快照到选股查询集成测试（任务 6）。
#
# 契约验证：
# 1. 日常管线运行（或准备阶段产出）后：
#    - UNIVERSE 快照存在
#    - FACTOR 快照存在
#    - STRATEGY 快照存在
#    - CANDIDATE 快照不存在 / 阶段保持安全阻断（BLOCKED）
# 2. 终端只读筛选与画像命令可用：
#    - `astock screen growth --as-of 2026-09-17 --top 20` 正常输出有序排名
#    - `astock stock 600519.SH --as-of 2026-09-17` 正常输出 Universe、因子、策略并说明 Candidate 阻断
# 3. API 端点完整支持策略选股与单股研究画像：
#    - GET /strategies?as_of=...
#    - GET /strategies/{strategy_id}/results?as_of=...
#    - GET /stocks/{symbol}?as_of=...
# 4. 读写一致性契约（Read-After-Write Consistency）：
#    - stored StrategyResult -> discovery service -> API response
#    - 严格保持 symbol、score、rank_percentile、strategy_version
#    - 严格保留 None，绝不静默兜底为 0.0
#


DISCOVERY_WORKFLOW_ROOT = Path(__file__).resolve().parents[2]


DISCOVERY_WORKFLOW_CSV_ROOT = DISCOVERY_WORKFLOW_ROOT / "tests" / "fixtures" / "csv"


SHANGHAI = ZoneInfo("Asia/Shanghai")


DAY_2026_09_17 = "2026-09-17"


AS_OF_2026_09_17 = datetime(2026, 9, 17, 15, 0, tzinfo=SHANGHAI)


DAY_2026_09_04 = "2026-09-04"


AS_OF_2026_09_04 = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _invoke_cli(
    snapshot_root: Path,
    watchlist_root: Path,
    job_root: Path,
    *args: str,
    dataset: str = "daily_bars_long",
    csv_root: Path = DISCOVERY_WORKFLOW_CSV_ROOT,
) -> Result:
    """运行 CLI 命令，注入测试隔离环境。"""
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_CSV_ROOT": str(csv_root),
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_WATCHLIST_ROOT": str(watchlist_root),
            "ASTOCK_JOB_ROOT": str(job_root),
            "ASTOCK_DATASET": dataset,
        },
    )


def _seed_daily_stage_outputs(root: Path, as_of: datetime) -> None:
    """模拟每日阶段落盘产物（UNIVERSE、FACTOR、STRATEGY 存在，CANDIDATE 缺失/阻断）。"""
    store = JsonSnapshotStore(root)

    # 1. UNIVERSE snapshot
    universe = UniverseSnapshot(
        as_of=as_of,
        snapshot_id=f"{as_of.strftime('%Y-%m-%d')}:univ_v1",
        config_digest="digest_mock_17",
        lineage=SnapshotLineage(
            universe_snapshot=f"{as_of.strftime('%Y-%m-%d')}:univ_v1"
        ),
        included=("600519.SH", "000001.SZ", "300750.SZ"),
        exclusions=(
            UniverseExclusion(
                symbol="000002.SZ", rule=UniverseRule.ST, detail="ST flagged"
            ),
        ),
        deferred_rules=(),
    )
    store.write(SnapshotKind.UNIVERSE, as_of, [universe])

    # 2. FACTOR snapshot
    factors = [
        FactorResult(
            symbol="600519.SH",
            factor="revenue_yoy",
            as_of=as_of,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=0.185,
        ),
        FactorResult(
            symbol="600519.SH",
            factor="avg_amount_20d",
            as_of=as_of,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=5_000_000_000.0,
        ),
        FactorResult(
            symbol="000001.SZ",
            factor="avg_amount_20d",
            as_of=as_of,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=1_200_000_000.0,
        ),
    ]
    store.write(SnapshotKind.FACTOR, as_of, factors)

    # 3. STRATEGY snapshot (包含 growth 与 momentum)
    strategy_results = [
        StrategyResult(
            symbol="600519.SH",
            strategy_id="growth",
            strategy_version="v1.0",
            as_of=as_of,
            eligible=True,
            lineage=SnapshotLineage(strategy_version="v1.0"),
            score=92.5,
            rank_percentile=0.98,
            confidence=0.95,
            reasons=("strong_revenue_growth",),
            risks=(),
        ),
        StrategyResult(
            symbol="000001.SZ",
            strategy_id="growth",
            strategy_version="v1.0",
            as_of=as_of,
            eligible=True,
            lineage=SnapshotLineage(strategy_version="v1.0"),
            score=81.0,
            rank_percentile=0.85,
            confidence=0.90,
            reasons=("steady_growth",),
            risks=(),
        ),
        StrategyResult(
            symbol="300750.SZ",
            strategy_id="growth",
            strategy_version="v1.0",
            as_of=as_of,
            eligible=True,
            lineage=SnapshotLineage(strategy_version="v1.0"),
            score=75.0,
            rank_percentile=0.72,
            confidence=0.80,
            reasons=("emerging_growth",),
            risks=(),
        ),
        StrategyResult(
            symbol="000002.SZ",
            strategy_id="growth",
            strategy_version="v1.0",
            as_of=as_of,
            eligible=False,
            lineage=SnapshotLineage(strategy_version="v1.0"),
            score=None,
            rank_percentile=None,
            confidence=None,
            reasons=(),
            risks=("high_debt",),
        ),
        # 补充一条 momentum 结果以验证多策略共存与隔离
        StrategyResult(
            symbol="600519.SH",
            strategy_id="momentum",
            strategy_version="v1.0",
            as_of=as_of,
            eligible=True,
            lineage=SnapshotLineage(strategy_version="v1.0"),
            score=88.0,
            rank_percentile=0.92,
            confidence=0.85,
            reasons=("momentum_trend",),
            risks=(),
        ),
    ]
    store.write(SnapshotKind.STRATEGY, as_of, strategy_results)

    # 4. CANDIDATE snapshot 刻意不写（保持 absent / blocked 状态）


def test_stock_discovery_workflow_seeded_growth(local_tmp: Path) -> None:
    """验证完整的 Daily 阶段产出 -> 选股筛选 -> 单股画像 -> API 查询闭环。"""
    snapshot_root = local_tmp / "snapshots"
    watchlist_root = local_tmp / "watchlist"
    job_root = local_tmp / "jobs"

    _seed_daily_stage_outputs(snapshot_root, AS_OF_2026_09_17)

    # 断言 1: UNIVERSE / FACTOR / STRATEGY 快照文件存在
    assert (
        snapshot_root / SnapshotKind.UNIVERSE.value / f"{DAY_2026_09_17}.json"
    ).is_file()
    assert (
        snapshot_root / SnapshotKind.FACTOR.value / f"{DAY_2026_09_17}.json"
    ).is_file()
    assert (
        snapshot_root / SnapshotKind.STRATEGY.value / f"{DAY_2026_09_17}.json"
    ).is_file()

    # 断言 2: CANDIDATE 快照文件严格不存在（保持 ABSENT / BLOCKED）
    assert not (
        snapshot_root / SnapshotKind.CANDIDATE.value / f"{DAY_2026_09_17}.json"
    ).exists()

    # 断言 3: CLI 命令 `astock screen growth --as-of 2026-09-17 --top 20` 正常运行并按排名输出
    res_screen = _invoke_cli(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        DAY_2026_09_17,
        "--top",
        "20",
    )
    assert res_screen.exit_code == 0, res_screen.output
    assert f"growth — {DAY_2026_09_17}" in res_screen.stdout
    assert "coverage: total=4 eligible=3 scored=3 ranked=3" in res_screen.stdout
    assert "showing: 3" in res_screen.stdout

    # 验证排名前 3 的标的及格式
    assert "1  600519.SH  score=92.50  percentile=0.9800" in res_screen.stdout
    assert "2  000001.SZ  score=81.00  percentile=0.8500" in res_screen.stdout
    assert "3  300750.SZ  score=75.00  percentile=0.7200" in res_screen.stdout
    # eligible=False 的 000002.SZ 默认不应显示
    assert "000002.SZ" not in res_screen.stdout

    # 断言 4: CLI 命令 `astock stock 600519.SH --as-of 2026-09-17` 正常输出画像
    res_stock = _invoke_cli(
        snapshot_root,
        watchlist_root,
        job_root,
        "stock",
        "600519.SH",
        "--as-of",
        DAY_2026_09_17,
    )
    assert res_stock.exit_code == 0, res_stock.output
    assert f"600519.SH ({DAY_2026_09_17})" in res_stock.stdout
    assert "universe: included" in res_stock.stdout
    assert (
        "growth v1.0: score 92.50 rank_percentile 0.980 eligible=True"
        in res_stock.stdout
    )
    # 明确标明当天没有发布 Candidate（只陈述事实，不猜测原因）
    assert "candidate: not published for this date" in res_stock.stdout

    # 断言 5: API 接口端点全量验证
    client = TestClient(
        create_app(snapshot_root=snapshot_root, watchlist_root=watchlist_root)
    )

    # 5.1 GET /strategies?as_of=...
    resp_strategies = client.get("/strategies", params={"as_of": DAY_2026_09_17})
    assert resp_strategies.status_code == 200
    summaries = resp_strategies.json()
    assert isinstance(summaries, list)
    growth_sum = next(s for s in summaries if s["strategy_id"] == "growth")
    assert growth_sum["total_count"] == 4
    assert growth_sum["eligible_count"] == 3
    assert growth_sum["scored_count"] == 3
    assert growth_sum["ranked_count"] == 3

    # 5.2 GET /strategies/{strategy_id}/results?as_of=...
    resp_growth_results = client.get(
        "/strategies/growth/results",
        params={"as_of": DAY_2026_09_17, "limit": 20},
    )
    assert resp_growth_results.status_code == 200
    results_body = resp_growth_results.json()
    assert results_body["strategy_id"] == "growth"
    assert results_body["coverage"]["total_count"] == 4
    items = results_body["items"]
    assert len(items) == 3
    assert [it["symbol"] for it in items] == ["600519.SH", "000001.SZ", "300750.SZ"]
    assert [it["rank"] for it in items] == [1, 2, 3]
    assert items[0]["score"] == 92.5
    assert items[0]["rank_percentile"] == 0.98

    # 5.3 GET /stocks/{symbol}?as_of=...
    resp_profile = client.get(f"/stocks/600519.SH?as_of={DAY_2026_09_17}")
    assert resp_profile.status_code == 200
    profile_body = resp_profile.json()
    assert profile_body["symbol"] == "600519.SH"
    assert profile_body["as_of"] == DAY_2026_09_17
    assert profile_body["candidate_status"] == "not_published"
    assert profile_body["candidate"] is None
    assert profile_body["universe"]["included"] is True
    strat_ids = [s["strategy_id"] for s in profile_body["strategies"]]
    assert "growth" in strat_ids
    assert "momentum" in strat_ids


def test_read_after_write_consistency(local_tmp: Path) -> None:
    """Step 2: 验证写后读一致性（Read-After-Write Consistency）。

    链路：
    stored StrategyResult -> discovery service -> API response
    严格保持 symbol、score、rank_percentile、strategy_version。
    """
    snapshot_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snapshot_root)

    original_top = StrategyResult(
        symbol="600519.SH",
        strategy_id="growth",
        strategy_version="v2.1.0-alpha",
        as_of=AS_OF_2026_09_17,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v2.1.0-alpha"),
        score=95.4321,
        rank_percentile=0.9876,
        confidence=0.95,
        reasons=("dominant_market_share", "exceptional_margins"),
        risks=(),
    )
    original_unscored = StrategyResult(
        symbol="000002.SZ",
        strategy_id="growth",
        strategy_version="v2.1.0-alpha",
        as_of=AS_OF_2026_09_17,
        eligible=False,
        lineage=SnapshotLineage(strategy_version="v2.1.0-alpha"),
        score=None,
        rank_percentile=None,
        confidence=None,
        reasons=(),
        risks=("industry_cycle_risk",),
    )

    # 1. 写入快照存储
    store.write(
        SnapshotKind.STRATEGY,
        AS_OF_2026_09_17,
        [original_top, original_unscored],
    )

    # 2. 从快照读出并送入 discovery service
    loaded_records = store.read(SnapshotKind.STRATEGY, AS_OF_2026_09_17)
    loaded_models = [StrategyResult.model_validate(r) for r in loaded_records]

    screened = screen_strategy(
        loaded_models,
        StrategyScreenQuery(strategy_id="growth", eligible_only=False),
    )

    # 2.1 验证 discovery service 输出一致性
    assert len(screened.items) == 2
    item_top = screened.items[0]
    assert item_top.symbol == original_top.symbol
    assert item_top.score == original_top.score
    assert item_top.rank_percentile == original_top.rank_percentile
    assert item_top.strategy_version == original_top.strategy_version

    item_unscored = screened.items[1]
    assert item_unscored.symbol == original_unscored.symbol
    assert item_unscored.score is None
    assert item_unscored.rank_percentile is None
    assert item_unscored.strategy_version == original_unscored.strategy_version

    # 3. 通过 API /strategies/growth/results 查询并验证响应
    client = TestClient(create_app(snapshot_root=snapshot_root))
    resp_api = client.get(
        "/strategies/growth/results",
        params={"as_of": DAY_2026_09_17, "eligible_only": "false"},
    )
    assert resp_api.status_code == 200
    api_payload = resp_api.json()
    assert api_payload["strategy_id"] == "growth"
    assert len(api_payload["items"]) == 2

    api_top = api_payload["items"][0]
    assert api_top["symbol"] == original_top.symbol
    assert api_top["score"] == original_top.score
    assert api_top["rank_percentile"] == original_top.rank_percentile
    assert api_top["strategy_version"] == original_top.strategy_version

    api_unscored = api_payload["items"][1]
    assert api_unscored["symbol"] == original_unscored.symbol
    assert api_unscored["score"] is None
    assert api_unscored["rank_percentile"] is None
    assert api_unscored["strategy_version"] == original_unscored.strategy_version


def test_daily_pipeline_to_discovery_workflow_end_to_end(local_tmp: Path) -> None:
    """真实运行 daily 管线（--allow-incomplete）验证产出与选股发现联动。

    以长测试夹具（2026-09-04，daily_bars_long）执行真实 daily 管线，
    断言 formal STRATEGY snapshot 落盘，CANDIDATE snapshot 保持 absent，
    随后 screen 和 API 端点可无缝读取。
    """
    snapshot_root = local_tmp / "snapshots"
    watchlist_root = local_tmp / "watchlist"
    job_root = local_tmp / "jobs"

    # 1. 运行 daily 管线
    daily_res = _invoke_cli(
        snapshot_root,
        watchlist_root,
        job_root,
        "daily",
        "--as-of",
        DAY_2026_09_04,
        "--allow-incomplete",
    )
    assert daily_res.exit_code == 0, daily_res.output
    assert "daily pipeline incomplete: 1 blocked, 0 failed" in daily_res.output

    # 2. 检查生成的快照文件
    assert (
        snapshot_root / SnapshotKind.UNIVERSE.value / f"{DAY_2026_09_04}.json"
    ).is_file()
    assert (
        snapshot_root / SnapshotKind.FACTOR.value / f"{DAY_2026_09_04}.json"
    ).is_file()
    assert (
        snapshot_root / SnapshotKind.STRATEGY.value / f"{DAY_2026_09_04}.json"
    ).is_file()
    # Candidate 快照在审批通过后正式落盘生成
    assert (
        snapshot_root / SnapshotKind.CANDIDATE.value / f"{DAY_2026_09_04}.json"
    ).is_file()

    # 3. 运行 screen momentum
    screen_res = _invoke_cli(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "momentum",
        "--as-of",
        DAY_2026_09_04,
        "--top",
        "5",
    )
    assert screen_res.exit_code == 0, screen_res.output
    assert f"momentum — {DAY_2026_09_04}" in screen_res.stdout
    assert "coverage: total=6 eligible=6 scored=6 ranked=6" in screen_res.stdout
    assert "showing: 5" in screen_res.stdout
    assert "300750.SZ" in screen_res.stdout

    # 4. 运行 stock 查看单股画像
    stock_res = _invoke_cli(
        snapshot_root,
        watchlist_root,
        job_root,
        "stock",
        "300750.SZ",
        "--as-of",
        DAY_2026_09_04,
    )
    assert stock_res.exit_code == 0, stock_res.output
    assert f"300750.SZ ({DAY_2026_09_04})" in stock_res.stdout
    assert "universe: included" in stock_res.stdout
    assert "candidate: WATCH" in stock_res.stdout

    # 5. API 查询
    client = TestClient(
        create_app(snapshot_root=snapshot_root, watchlist_root=watchlist_root)
    )

    resp_strats = client.get("/strategies", params={"as_of": DAY_2026_09_04})
    assert resp_strats.status_code == 200
    m_cov = next(s for s in resp_strats.json() if s["strategy_id"] == "momentum")
    assert m_cov["ranked_count"] == 6

    resp_m_res = client.get(
        "/strategies/momentum/results", params={"as_of": DAY_2026_09_04}
    )
    assert resp_m_res.status_code == 200
    assert len(resp_m_res.json()["items"]) == 6

    resp_stock = client.get(f"/stocks/300750.SZ?as_of={DAY_2026_09_04}")
    assert resp_stock.status_code == 200
    assert resp_stock.json()["candidate_status"] == "published"
    assert resp_stock.json()["candidate"] is not None
    assert resp_stock.json()["candidate"]["symbol"] == "300750.SZ"

    resp_candidates = client.get("/candidates", params={"as_of": DAY_2026_09_04})
    assert resp_candidates.status_code == 200
    assert len(resp_candidates.json()) > 0


# ===========================================================================
# 来源：tests/integration/test_valuation_pipeline.py（6 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 估值数据进入管线的端到端测试。
#
# 这条链路此前只到归一化层就断了：`scan` / `daily` 读不到估值，于是 Value / GARP
# 在真实运行里永远"缺证据"。这里钉住接好之后的四件事：
#
# 1. 落地的估值能被管线按取数日选出来；
# 2. 未来日期的落地文件不可见（时点由文件选择保证）；
# 3. 归一化后的估值观测进入因子上下文，且每个因子只看到自己标的的行；
# 4. 估值因子因此能给出 `VALUE`，而不是 `NOT_APPLICABLE`。
#


VALUATION_ROOT = Path(__file__).resolve().parents[2]


VALUATION_CSV_FIXTURES = VALUATION_ROOT / "tests" / "fixtures" / "csv"


FIXTURES = VALUATION_ROOT / "tests" / "fixtures" / "neodata"


VAL_CFG = VALUATION_ROOT / "configs"


AS_OF_V = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


VAL_LONG_DS = "daily_bars_long"


def _blocks(dataset: str) -> tuple[tuple[str, str, str], ...]:
    payload = json.loads((FIXTURES / f"{dataset}.json").read_text(encoding="utf-8"))
    return tuple(
        (
            str(b.get("type") or ""),
            str(b.get("desc") or ""),
            str(b.get("content") or ""),
        )
        for b in payload["data"]["apiData"]["apiRecall"]
    )


class Stub:
    """回放录制的估值响应。"""

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="neodata",
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=AS_OF_V,
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        rows = _blocks("valuation")
        return RawDataset(
            provider="neodata",
            dataset=request.dataset,
            fetched_at=AS_OF_V,
            provider_version="v1",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=PAYLOAD_COLUMNS, rows=rows),
        )


def _root(local_tmp: Path, *, landed: bool = True) -> Path:
    for name in ("daily_bars_long.csv", "securities.csv"):
        shutil.copyfile(VALUATION_CSV_FIXTURES / name, local_tmp / name)
    if landed:
        land_neodata_blocks(
            provider=Stub(),
            root=local_tmp,
            dataset="valuation",
            values=("000568.SZ",),
            as_of=AS_OF_V,
        )
    return local_tmp


def test_a_scan_without_landed_valuations_says_so(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root(local_tmp, landed=False),
        as_of=AS_OF_V,
        dataset=VAL_LONG_DS,
    )

    assert outcome.valuations is not None
    assert outcome.valuations.source_file is None
    assert outcome.valuations.observations == ()
    assert outcome.bars.valuations == ()


def test_landed_valuations_reach_the_factor_context(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root(local_tmp), as_of=AS_OF_V, dataset=VAL_LONG_DS
    )

    assert outcome.valuations is not None
    assert outcome.valuations.source_file is not None
    assert outcome.valuations.source_file.name == "2026-09-17.csv"
    assert outcome.bars.valuations
    assert {item.symbol for item in outcome.bars.valuations} == {"000568.SZ"}

    pe = build_factor(load_factor_config(VAL_CFG / "factors" / "pe_ttm.yaml")).compute(
        FactorContext(symbol="000568.SZ", as_of=AS_OF_V, dataset=outcome.bars)
    )
    assert pe.status is DataStatus.VALUE
    assert pe.raw_value is not None
    assert pe.unit == "x"


def test_a_future_landing_is_invisible_at_the_point_in_time(local_tmp: Path) -> None:
    root = _root(local_tmp, landed=False)
    land_neodata_blocks(
        provider=Stub(),
        root=root,
        dataset="valuation",
        values=("000568.SZ",),
        as_of=datetime(2026, 9, 25, 15, 0, tzinfo=UTC),
    )

    outcome = stages.normalize_stage(csv_root=root, as_of=AS_OF_V, dataset=VAL_LONG_DS)

    assert outcome.valuations is not None
    assert outcome.valuations.source_file is None
    assert outcome.valuations.observations == ()


def test_each_factor_sees_only_its_own_symbol_valuations(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root(local_tmp), as_of=AS_OF_V, dataset=VAL_LONG_DS
    )
    index = stages.DatasetIndex(outcome.bars)

    view = index.for_symbol("000568.SZ")
    other = index.for_symbol("600519.SH")

    assert view.valuations
    assert other.valuations == ()
    assert all(item.symbol == "000568.SZ" for item in view.valuations)


def test_the_reported_metrics_match_what_the_response_carried(
    local_tmp: Path,
) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root(local_tmp), as_of=AS_OF_V, dataset=VAL_LONG_DS
    )

    assert outcome.valuations is not None
    metrics = {item.metric for item in outcome.valuations.observations}
    assert {"pe_ttm", "pb", "peg", "pcf_operating_ttm"} <= metrics
    # 该响应里每一格都读得出来，因此没有失败记录。
    assert outcome.valuations.failures == ()


def test_reading_valuations_twice_gives_the_same_answer(local_tmp: Path) -> None:
    root = _root(local_tmp)

    first = stages.valuation_inputs(root, as_of=AS_OF_V)
    second = stages.valuation_inputs(root, as_of=AS_OF_V)

    assert first.source_file == second.source_file
    assert len(first.observations) == len(second.observations)
