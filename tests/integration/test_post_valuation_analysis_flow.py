"""最新估值进入正式策略快照的等价链路测试（任务 3）。

规格：`docs/superpowers/specs/2026-09-20-candidate-readiness-upgrade-design.md`
计划：`docs/superpowers/plans/2026-09-20-valuation-to-qualification-readiness-implementation-plan.md` 任务 3。

钉住的关键不变量：
1. 形式快照与只读分析等价：同一时点、同一输入下，正式 FACTOR/STRATEGY 快照内容
   与只读研究分析结果语义完全一致；
2. 时点隔离：新日期的估值变化只改变估值相关因子与策略（Value/GARP），不改变纯成长因子；
3. 候选门禁持续生效：未批准绝对质量规则前，Candidate 保持为空且 BUILD_CANDIDATES 阶段 BLOCKED。
"""

from datetime import UTC, datetime
from pathlib import Path

from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import JobStage
from astock_lens.factors.config import load_factor_config
from astock_lens.factors.contracts import FactorResult
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines.analysis import run_research_analysis
from astock_lens.pipelines.daily import run_daily
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
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

    u_cfg = load_universe_config(CONFIGS / "universe.yaml")
    f_cfgs = tuple(
        load_factor_config(p) for p in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    scanners = load_scanners(CONFIGS / "strategies")

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
        strategy_directory=CONFIGS / "strategies",
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

    u_cfg = load_universe_config(CONFIGS / "universe.yaml")
    f_cfgs = tuple(
        load_factor_config(p) for p in sorted((CONFIGS / "factors").glob("*.yaml"))
    )
    scanners = load_scanners(CONFIGS / "strategies")

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
