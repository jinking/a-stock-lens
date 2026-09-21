# mypy: disable-error-code="import-untyped"
"""每日策略快照到选股查询集成测试（任务 6）。

契约验证：
1. 日常管线运行（或准备阶段产出）后：
   - UNIVERSE 快照存在
   - FACTOR 快照存在
   - STRATEGY 快照存在
   - CANDIDATE 快照不存在 / 阶段保持安全阻断（BLOCKED）
2. 终端只读筛选与画像命令可用：
   - `astock screen growth --as-of 2026-09-17 --top 20` 正常输出有序排名
   - `astock stock 600519.SH --as-of 2026-09-17` 正常输出 Universe、因子、策略并说明 Candidate 阻断
3. API 端点完整支持策略选股与单股研究画像：
   - GET /strategies?as_of=...
   - GET /strategies/{strategy_id}/results?as_of=...
   - GET /stocks/{symbol}?as_of=...
4. 读写一致性契约（Read-After-Write Consistency）：
   - stored StrategyResult -> discovery service -> API response
   - 严格保持 symbol、score、rank_percentile、strategy_version
   - 严格保留 None，绝不静默兜底为 0.0
"""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from typer.testing import CliRunner, Result

from astock_lens.api.app import create_app
from astock_lens.cli.app import app
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.discovery import StrategyScreenQuery, screen_strategy
from astock_lens.domain.enums import DataStatus, SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.universe.models import (
    UniverseExclusion,
    UniverseRule,
    UniverseSnapshot,
)

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
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
    csv_root: Path = CSV_ROOT,
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
    assert "daily pipeline incomplete: 2 blocked, 0 failed" in daily_res.output

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
    # Candidate 快照在审批通过前保持 absent（被安全阻断）
    assert not (
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
    assert "candidate: not published for this date" in stock_res.stdout

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
    assert resp_stock.json()["candidate_status"] == "not_published"
    assert resp_stock.json()["candidate"] is None

    resp_candidates = client.get("/candidates", params={"as_of": DAY_2026_09_04})
    assert resp_candidates.status_code == 404
    assert (
        f"no CANDIDATE snapshot for {DAY_2026_09_04}"
        in resp_candidates.json()["detail"]
    )
