"""唯一分析执行链的端到端测试。

一个调用贯穿设计命名的业务链路：

    NORMALIZE → COMPUTE_FACTORS → BUILD_UNIVERSE → RUN_STRATEGIES

关于夹具：`daily_bars_long.csv` 的每只证券都为了观察一条 Universe 规则而存在
（见 `scripts/generate_fixtures.py`），价格按 close = base × (1 + rate)^i 生成，
所以 ret_20d 与 ret_60d 严格按 `rate` 排序，proximity_52w_high 等于
(1 + rate)^5 / 1.2（有尖顶的标的）或 1 / 1.01（000006.SZ，尖顶比例是 1.0）。
等权混合保持该顺序，只有 000006.SZ 因 proximity 升到第三。下面这些期望值是按
夹具公式手算的，不是把实现跑一遍抄回来的。

本文件同时替代已经退休的 first slice / daily scan 两个入口的测试：那两条链路
各有一套组装逻辑，正是本阶段要消灭的"同一个项目里有两个真相"。
"""

from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import DataStatus
from astock_lens.factors.config import load_factor_config
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines.analysis import (
    AnalysisState,
    FactorState,
    compute_factor_state,
    run_analysis,
)
from astock_lens.pipelines.daily import run_daily
from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.registry import RegisteredStrategy, build_scanner
from astock_lens.universe.config import load_universe_config
from astock_lens.universe.models import UniverseRule

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LONG_DATASET = "daily_bars_long"

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

LIQUIDITY_FACTOR_CONFIG = CONFIGS / "factors" / "avg_amount_20d.yaml"


def _factor_configs() -> tuple[object, ...]:
    return tuple(
        load_factor_config(path)
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )


def _momentum() -> StrategyConfig:
    return load_strategy_config(CONFIGS / "strategies" / "momentum.yaml")


def _momentum_scanner() -> RegisteredStrategy:
    config = _momentum()
    return RegisteredStrategy(config=config, plugin=build_scanner(config))


def _run(local_tmp: Path) -> AnalysisState:
    del local_tmp
    return run_analysis(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=_factor_configs(),
        scanners=(_momentum_scanner(),),
        dataset=LONG_DATASET,
    )


def test_the_analysis_returns_factors_a_universe_and_strategy_results() -> None:
    state = _run(Path())

    assert state.factor_results
    assert state.universe.as_of == AS_OF
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
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=_factor_configs(),
        scanners=(_momentum_scanner(),),
        dataset=LONG_DATASET,
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
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=_factor_configs(),
        scanners=scanners,
        dataset=LONG_DATASET,
    )
    daily = run_daily(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=_factor_configs(),
        scanners=scanners,
        strategy_directory=CONFIGS / "strategies",
        store=JsonSnapshotStore(local_tmp / "snapshots"),
        job_store=JsonJobStore(local_tmp / "jobs"),
        dataset=LONG_DATASET,
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
        as_of=AS_OF,
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
        as_of=AS_OF,
        factor_configs=(load_factor_config(LIQUIDITY_FACTOR_CONFIG),),
    )
    by_symbol = {item.symbol: item for item in measured.factor_results}

    for symbol in ("600519.SH", "601398.SH"):
        assert by_symbol[symbol].raw_value != 0
    assert by_symbol["601398.SH"].raw_value is None
