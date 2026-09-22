"""Integration tests locking candidate correctness gaps and safety gates.

Spec: docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md
Plan: docs/superpowers/plans/2026-09-21-candidate-correctness-safety-gate.md
"""

from datetime import UTC, datetime
from pathlib import Path

from astock_lens.candidates.policy import RepresentativeCandidatePolicy
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import DataStatus, JobStage, MarketValidation, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.config import load_factor_config
from astock_lens.factors.contracts import FactorResult
from astock_lens.jobs.models import JobStatus
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines.daily import run_daily
from astock_lens.pipelines.stages import market_validation_stage, signal_stage
from astock_lens.qualifications.registry import load_canonical_qualifiers
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _factor(name: str, value: float | None, symbol: str = "600000.SH") -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=AS_OF,
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
        as_of=AS_OF,
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
        as_of=AS_OF,
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
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=(),
        scanners=(),
        strategy_directory=CONFIGS / "strategies",
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
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    factor_names = frozenset(c.name for c in factor_configs)
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    store = JsonSnapshotStore(local_tmp / "snapshots")
    job_store = JsonJobStore(local_tmp / "jobs")

    result = run_daily(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=factor_configs,
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
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
        local_tmp / "snapshots" / "CANDIDATE" / f"{AS_OF.date().isoformat()}.json"
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
            as_of=AS_OF,
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
            as_of=AS_OF,
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
            as_of=AS_OF,
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
            as_of=AS_OF,
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
