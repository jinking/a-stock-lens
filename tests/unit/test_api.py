"""Domain API tests.

The rule these tests pin down: the API reads stored snapshots. It never
recomputes a factor (`docs/ARCHITECTURE.md` §2), and a missing snapshot is a
404 that says so rather than a 500.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astock_lens.api.app import create_app
from astock_lens.candidates.models import Candidate
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import (
    DataStatus,
    MarketValidation,
    NextAction,
    Signal,
    SnapshotKind,
)
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.trade_gate.models import TradeIntent, TradeRiskProposal
from astock_lens.trade_gate.store import JsonTradeLedgerStore
from astock_lens.universe.models import (
    UniverseExclusion,
    UniverseRule,
    UniverseSnapshot,
)
from astock_lens.watchlist.state_machine import open_entry
from astock_lens.watchlist.store import JsonWatchlistStore

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
DAY = "2026-09-04"


def _seed(root: Path) -> None:
    store = JsonSnapshotStore(root)
    store.write(
        SnapshotKind.FACTOR,
        AS_OF,
        [
            FactorResult(
                symbol="600000.SH",
                factor="avg_amount_20d",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=1_014_500.0,
            )
        ],
    )
    store.write(
        SnapshotKind.CANDIDATE,
        AS_OF,
        [
            Candidate(
                symbol="600000.SH",
                as_of=AS_OF,
                next_action=NextAction.IGNORE,
                lineage=SnapshotLineage(factor_version="v1", strategy_version="v1"),
            )
        ],
    )
    store.write(
        SnapshotKind.STRATEGY,
        AS_OF,
        [
            StrategyResult(
                symbol="600000.SH",
                strategy_id="growth",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=90.0,
                rank_percentile=0.98,
                confidence=1.0,
                reasons=("strong_growth",),
            ),
            StrategyResult(
                symbol="600001.SH",
                strategy_id="growth",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=70.0,
                rank_percentile=0.90,
                confidence=0.8,
                reasons=("moderate_growth",),
            ),
            StrategyResult(
                symbol="600002.SH",
                strategy_id="growth",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=False,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=None,
                rank_percentile=None,
                confidence=None,
                reasons=(),
                risks=("negative_revenue",),
            ),
            StrategyResult(
                symbol="600000.SH",
                strategy_id="momentum",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=85.0,
                rank_percentile=0.96,
                confidence=0.9,
                reasons=("high_momentum",),
            ),
            StrategyResult(
                symbol="600003.SH",
                strategy_id="momentum",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=65.0,
                rank_percentile=0.85,
                confidence=0.7,
                reasons=("medium_momentum",),
            ),
        ],
    )


def test_health_route() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "A-Stock Lens"}


def test_factor_route_reads_the_stored_snapshot(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/factors", params={"symbol": "600000.SH", "as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert payload["as_of"] == DAY
    assert [record["symbol"] for record in payload["records"]] == ["600000.SH"]
    assert payload["records"][0]["status"] == "VALUE"


def test_factor_route_is_empty_for_an_unknown_symbol(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/factors", params={"symbol": "999999.SH", "as_of": DAY})

    assert response.status_code == 200
    assert response.json()["records"] == []


MISSING_SNAPSHOT_CASES = (
    # label, route, params, expected detail 片段
    (
        "test_missing_snapshot_is_a_404",
        "/factors",
        {"symbol": "600000.SH", "as_of": DAY},
        DAY,
    ),
    (
        "test_strategies_route_404s_when_no_snapshot",
        "/strategies",
        {"as_of": DAY},
        DAY,
    ),
    (
        "test_strategy_results_missing_snapshot_returns_404",
        "/strategies/growth/results",
        {"as_of": DAY},
        DAY,
    ),
    (
        "test_stock_profile_missing_universe_snapshot_returns_404",
        "/stocks/600000.SH",
        {"as_of": DAY},
        DAY,
    ),
    (
        "test_qualification_results_missing_snapshot_returns_404",
        "/qualifications/growth/results",
        {"as_of": DAY},
        DAY,
    ),
    # test_today_api_missing_candidate_snapshot_returns_404:
    #   Task 5: CANDIDATE 快照不存在时 /today 返回 404。
    (
        "test_today_api_missing_candidate_snapshot_returns_404",
        "/today",
        {"as_of": DAY},
        f"no CANDIDATE snapshot for {DAY}",
    ),
    # test_universe_route_404s_when_no_universe_was_built:
    #   /universe 与 /stocks 同读 UNIVERSE 快照，无快照时经同一个 `_read`
    #   抛出点名日期的 404（原用例断言 404 且 DETAIL 含 as_of）。
    (
        "test_universe_route_404s_when_no_universe_was_built",
        "/universe",
        {"as_of": DAY},
        DAY,
    ),
)


def test_missing_snapshot_is_a_404(local_tmp: Path) -> None:
    """测试 7 条快照路由各自在无快照时返回点名原因的 404（原 7 条缺快照用例收表）。"""
    client = TestClient(create_app(snapshot_root=local_tmp))
    wrong = []
    for label, route, params, expected_detail in MISSING_SNAPSHOT_CASES:
        response = client.get(route, params=params)
        if response.status_code != 404:
            wrong.append(f"{label}: {route} 得到 {response.status_code}，期望 404")
        elif expected_detail not in response.json()["detail"]:
            wrong.append(
                f"{label}: {route} detail 缺少 {expected_detail!r}，"
                f"实际 {response.json()['detail']!r}"
            )
    assert not wrong, "缺快照路由应返回点名原因的 404:\n" + "\n".join(wrong)


def test_candidate_route_reads_the_stored_snapshot(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/candidates", params={"as_of": DAY})

    assert response.status_code == 200
    records = response.json()["records"]
    assert [record["symbol"] for record in records] == ["600000.SH"]
    assert records[0]["next_action"] == "IGNORE"


def test_candidate_route_404s_when_nothing_was_scanned(local_tmp: Path) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/candidates", params={"as_of": DAY})

    assert response.status_code == 404


def test_universe_route_reads_the_stored_snapshot(local_tmp: Path) -> None:
    universe = UniverseSnapshot(
        as_of=AS_OF,
        snapshot_id="2026-09-04:abc123",
        config_digest="abc123",
        lineage=SnapshotLineage(universe_snapshot="2026-09-04:abc123"),
        included=("600000.SH",),
        exclusions=(
            UniverseExclusion(
                symbol="000002.SZ", rule=UniverseRule.ST, detail="flagged"
            ),
        ),
        deferred_rules=(),
    )
    JsonSnapshotStore(local_tmp).write(SnapshotKind.UNIVERSE, AS_OF, [universe])
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/universe", params={"as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert payload["as_of"] == DAY
    assert payload["snapshot"]["included"] == ["600000.SH"]
    assert payload["snapshot"]["exclusions"][0]["rule"] == "ST"


def test_trade_gate_intent_route_is_read_only(tmp_path: Path) -> None:
    intent = TradeIntent(
        id="intent-api",
        symbol="600519.SH",
        action="ENTRY",
        profile="EVENT",
        thesis="test",
        expected_holding_days=3,
        created_at=AS_OF,
        risk=TradeRiskProposal(
            account_nav=10000,
            planned_entry_price=100,
            stop_loss_price=90,
            quantity=10,
            invalidation_rule="跌破90",
        ),
    )
    JsonTradeLedgerStore(tmp_path).write_intent(intent)
    client = TestClient(create_app(trade_root=tmp_path))
    response = client.get("/trade-gate/intents/intent-api")
    assert response.status_code == 200
    assert response.json()["symbol"] == "600519.SH"
    assert client.get("/trade-gate/intents/unknown").status_code == 404


def test_watchlist_route_reads_the_stored_entries(local_tmp: Path) -> None:
    JsonWatchlistStore(local_tmp / "watchlist").write(
        open_entry("600519.SH", at=AS_OF, thesis="brand moat")
    )
    client = TestClient(create_app(watchlist_root=local_tmp / "watchlist"))

    response = client.get("/watchlist")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbols"] == ["600519.SH"]
    assert payload["entries"][0]["state"] == "DISCOVERED"
    assert payload["entries"][0]["thesis"] == "brand moat"


def test_watchlist_route_is_empty_rather_than_missing(local_tmp: Path) -> None:
    """Nothing discovered yet is an answer, not a 404."""
    client = TestClient(create_app(watchlist_root=local_tmp / "watchlist"))

    response = client.get("/watchlist")

    assert response.status_code == 200
    assert response.json() == {"symbols": [], "entries": []}


def test_strategies_route_reads_summaries(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/strategies", params={"as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 2
    assert payload[0]["strategy_id"] == "growth"
    assert payload[0]["total_count"] == 3
    assert payload[0]["eligible_count"] == 2
    assert payload[0]["scored_count"] == 2
    assert payload[0]["ranked_count"] == 2
    assert payload[1]["strategy_id"] == "momentum"
    assert payload[1]["total_count"] == 2
    assert payload[1]["eligible_count"] == 2
    assert payload[1]["scored_count"] == 2
    assert payload[1]["ranked_count"] == 2


def test_strategy_results_default_query(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/strategies/growth/results", params={"as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy_id"] == "growth"
    assert payload["coverage"]["total_count"] == 3
    assert payload["coverage"]["eligible_count"] == 2
    assert payload["coverage"]["scored_count"] == 2
    assert payload["coverage"]["ranked_count"] == 2
    assert len(payload["items"]) == 2
    assert [item["symbol"] for item in payload["items"]] == ["600000.SH", "600001.SH"]
    assert payload["items"][0]["rank"] == 1
    assert payload["items"][0]["rank_percentile"] == 0.98
    assert payload["items"][0]["score"] == 90.0
    assert payload["items"][1]["rank"] == 2
    assert payload["items"][1]["rank_percentile"] == 0.90
    assert payload["items"][1]["score"] == 70.0


def test_strategy_results_eligible_only_false(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get(
        "/strategies/growth/results",
        params={"as_of": DAY, "eligible_only": "false"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 3
    assert [item["symbol"] for item in payload["items"]] == [
        "600000.SH",
        "600001.SH",
        "600002.SH",
    ]
    assert payload["items"][2]["rank"] == 3
    assert payload["items"][2]["eligible"] is False
    assert payload["items"][2]["rank_percentile"] is None


def test_strategy_results_with_limit(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get(
        "/strategies/growth/results",
        params={"as_of": DAY, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage"]["total_count"] == 3
    assert len(payload["items"]) == 1
    assert payload["items"][0]["symbol"] == "600000.SH"


def test_strategy_results_min_percentile(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get(
        "/strategies/growth/results",
        params={"as_of": DAY, "min_percentile": 0.95},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["symbol"] == "600000.SH"
    assert payload["items"][0]["rank_percentile"] == 0.98


INVALID_QUERY_VALUES = (
    ("limit", 0),
    ("limit", -1),
    ("limit", 501),
    ("min_percentile", -0.1),
    ("min_percentile", 1.1),
)


def test_strategy_results_invalid_query_returns_422(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    wrong = []
    for param, value in INVALID_QUERY_VALUES:
        response = client.get(
            "/strategies/growth/results", params={"as_of": DAY, param: value}
        )
        if response.status_code != 422:
            wrong.append(f"{param}={value!r}: {response.status_code}")
    assert not wrong, "非法查询参数应返回 422:\n" + "\n".join(wrong)


def test_strategy_results_unknown_strategy_returns_404(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get(
        "/strategies/unknown_strat/results",
        params={"as_of": DAY},
    )

    assert response.status_code == 404
    assert (
        response.json()["detail"]
        == f"strategy 'unknown_strat' has no stored results for {DAY}"
    )


def _seed_profile_base(root: Path) -> None:
    """Seed universe, factor, and strategy snapshots without candidates."""
    store = JsonSnapshotStore(root)
    universe = UniverseSnapshot(
        as_of=AS_OF,
        snapshot_id="2026-09-04:abc123",
        config_digest="abc123",
        lineage=SnapshotLineage(universe_snapshot="2026-09-04:abc123"),
        included=("600000.SH", "600001.SH"),
        exclusions=(
            UniverseExclusion(
                symbol="000002.SZ", rule=UniverseRule.ST, detail="flagged"
            ),
        ),
        deferred_rules=(),
    )
    store.write(SnapshotKind.UNIVERSE, AS_OF, [universe])
    store.write(
        SnapshotKind.FACTOR,
        AS_OF,
        [
            FactorResult(
                symbol="600000.SH",
                factor="avg_amount_20d",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=1_014_500.0,
            )
        ],
    )
    store.write(
        SnapshotKind.STRATEGY,
        AS_OF,
        [
            StrategyResult(
                symbol="600000.SH",
                strategy_id="growth",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=90.0,
                rank_percentile=0.98,
                confidence=1.0,
                reasons=("strong_growth",),
            )
        ],
    )


def test_stock_profile_no_candidate_snapshot_returns_not_published(
    local_tmp: Path,
) -> None:
    _seed_profile_base(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/stocks/600000.SH", params={"as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert payload["as_of"] == DAY
    assert payload["symbol"] == "600000.SH"
    assert payload["candidate_status"] == "not_published"
    assert payload["candidate"] is None
    assert payload["universe"] == {"included": True, "exclusion_rules": []}
    assert len(payload["factors"]) == 1
    assert payload["factors"][0]["factor"] == "avg_amount_20d"
    assert len(payload["strategies"]) == 1
    assert payload["strategies"][0]["strategy_id"] == "growth"
    assert payload["watchlist"] is None


def test_stock_profile_candidate_not_selected(local_tmp: Path) -> None:
    _seed_profile_base(local_tmp)
    store = JsonSnapshotStore(local_tmp)
    store.write(
        SnapshotKind.CANDIDATE,
        AS_OF,
        [
            Candidate(
                symbol="600001.SH",
                as_of=AS_OF,
                next_action=NextAction.DEEP_RESEARCH,
                lineage=SnapshotLineage(factor_version="v1", strategy_version="v1"),
            )
        ],
    )
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/stocks/600000.SH", params={"as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_status"] == "not_selected"
    assert payload["candidate"] is None


def test_stock_profile_candidate_published(local_tmp: Path) -> None:
    _seed_profile_base(local_tmp)
    store = JsonSnapshotStore(local_tmp)
    qual = StrategyQualification(
        symbol="600000.SH",
        strategy_id="growth",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.95,
        as_of=AS_OF,
        reasons=("strong_growth",),
    )
    store.write(
        SnapshotKind.CANDIDATE,
        AS_OF,
        [
            Candidate(
                symbol="600000.SH",
                as_of=AS_OF,
                next_action=NextAction.DEEP_RESEARCH,
                lineage=SnapshotLineage(factor_version="v1", strategy_version="v1"),
                strategy_qualifications=(qual,),
                market_validation=MarketValidation.CONFIRMED,
                signal=Signal.BREAKOUT,
            )
        ],
    )
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/stocks/600000.SH", params={"as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_status"] == "published"
    assert payload["candidate"] is not None
    assert payload["candidate"]["symbol"] == "600000.SH"
    assert payload["candidate"]["next_action"] == "DEEP_RESEARCH"
    assert payload["candidate"]["market_validation"] == "CONFIRMED"
    assert payload["candidate"]["signal"] == "BREAKOUT"
    assert len(payload["candidate"]["strategy_qualifications"]) == 1
    assert payload["candidate"]["strategy_qualifications"][0]["strategy_id"] == "growth"


def test_stock_profile_excluded_universe(local_tmp: Path) -> None:
    _seed_profile_base(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/stocks/000002.SZ", params={"as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "000002.SZ"
    assert payload["universe"] == {"included": False, "exclusion_rules": ["ST"]}


def test_stock_profile_watchlist_present_and_absent(local_tmp: Path) -> None:
    _seed_profile_base(local_tmp)
    watchlist_dir = local_tmp / "watchlist"
    JsonWatchlistStore(watchlist_dir).write(
        open_entry("600000.SH", at=AS_OF, thesis="growth leader")
    )
    client = TestClient(
        create_app(snapshot_root=local_tmp, watchlist_root=watchlist_dir)
    )

    resp_present = client.get("/stocks/600000.SH", params={"as_of": DAY})
    assert resp_present.status_code == 200
    wl = resp_present.json()["watchlist"]
    assert wl is not None
    assert wl["symbol"] == "600000.SH"
    assert wl["state"] == "DISCOVERED"
    assert wl["thesis"] == "growth leader"

    resp_absent = client.get("/stocks/600001.SH", params={"as_of": DAY})
    assert resp_absent.status_code == 200
    assert resp_absent.json()["watchlist"] is None


def test_stock_profile_factors_and_strategies_deterministic_sorting(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp)
    universe = UniverseSnapshot(
        as_of=AS_OF,
        snapshot_id="2026-09-04:abc123",
        config_digest="abc123",
        lineage=SnapshotLineage(universe_snapshot="2026-09-04:abc123"),
        included=("600000.SH",),
        exclusions=(),
        deferred_rules=(),
    )
    store.write(SnapshotKind.UNIVERSE, AS_OF, [universe])
    store.write(
        SnapshotKind.FACTOR,
        AS_OF,
        [
            FactorResult(
                symbol="600000.SH",
                factor="roe",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=0.15,
            ),
            FactorResult(
                symbol="600000.SH",
                factor="avg_amount_20d",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=1_014_500.0,
            ),
            FactorResult(
                symbol="600000.SH",
                factor="pe_ttm",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=8.5,
            ),
        ],
    )
    store.write(
        SnapshotKind.STRATEGY,
        AS_OF,
        [
            StrategyResult(
                symbol="600000.SH",
                strategy_id="value",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=80.0,
            ),
            StrategyResult(
                symbol="600000.SH",
                strategy_id="growth",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=90.0,
            ),
            StrategyResult(
                symbol="600000.SH",
                strategy_id="dividend",
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(strategy_version="v1"),
                score=75.0,
            ),
        ],
    )
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/stocks/600000.SH", params={"as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert [f["factor"] for f in payload["factors"]] == [
        "avg_amount_20d",
        "pe_ttm",
        "roe",
    ]
    assert [s["strategy_id"] for s in payload["strategies"]] == [
        "dividend",
        "growth",
        "value",
    ]


def test_stock_profile_invalid_as_of_returns_422(local_tmp: Path) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/stocks/600000.SH", params={"as_of": "not-a-date"})

    assert response.status_code == 422


def test_stock_profile_unknown_symbol_not_in_universe(local_tmp: Path) -> None:
    _seed_profile_base(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/stocks/999999.SH", params={"as_of": DAY})

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "999999.SH"
    assert payload["universe"] == {"included": False, "exclusion_rules": []}
    assert payload["factors"] == []
    assert payload["strategies"] == []
    assert payload["candidate_status"] == "not_published"


def test_qualification_results_dual_pass_only(local_tmp: Path) -> None:
    store = JsonSnapshotStore(local_tmp)
    # growth 已批准门槛：net_profit_parent_yoy>=15, revenue_yoy>=5, roe_ttm>=8
    factors = [
        FactorResult(
            symbol="600000.SH",
            factor="net_profit_parent_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=20.0,
        ),
        FactorResult(
            symbol="600000.SH",
            factor="revenue_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=8.0,
        ),
        FactorResult(
            symbol="600000.SH",
            factor="roe_ttm",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=9.0,
        ),
        FactorResult(
            symbol="600001.SH",
            factor="net_profit_parent_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=10.0,
        ),
        FactorResult(
            symbol="600001.SH",
            factor="revenue_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=8.0,
        ),
        FactorResult(
            symbol="600001.SH",
            factor="roe_ttm",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=9.0,
        ),
        FactorResult(
            symbol="600002.SH",
            factor="net_profit_parent_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=25.0,
        ),
        FactorResult(
            symbol="600002.SH",
            factor="revenue_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=12.0,
        ),
        FactorResult(
            symbol="600002.SH",
            factor="roe_ttm",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=10.0,
        ),
        FactorResult(
            symbol="600003.SH",
            factor="net_profit_parent_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=30.0,
        ),
        FactorResult(
            symbol="600003.SH",
            factor="revenue_yoy",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=15.0,
        ),
        FactorResult(
            symbol="600003.SH",
            factor="roe_ttm",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=11.0,
        ),
    ]
    store.write(SnapshotKind.FACTOR, AS_OF, factors)

    strategies = [
        StrategyResult(
            symbol="600000.SH",
            strategy_id="growth",
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            lineage=SnapshotLineage(strategy_version="v1"),
            score=80.0,
            rank_percentile=0.95,
        ),
        StrategyResult(
            symbol="600001.SH",
            strategy_id="growth",
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            lineage=SnapshotLineage(strategy_version="v1"),
            score=75.0,
            rank_percentile=0.95,
        ),
        StrategyResult(
            symbol="600002.SH",
            strategy_id="growth",
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            lineage=SnapshotLineage(strategy_version="v1"),
            score=70.0,
            rank_percentile=0.50,
        ),
        StrategyResult(
            symbol="600003.SH",
            strategy_id="growth",
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            lineage=SnapshotLineage(strategy_version="v1"),
            score=88.0,
            rank_percentile=0.98,
        ),
        StrategyResult(
            symbol="601398.SH",
            strategy_id="momentum",
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            lineage=SnapshotLineage(strategy_version="v1"),
            score=99.0,
            rank_percentile=0.99,
        ),
    ]
    store.write(SnapshotKind.STRATEGY, AS_OF, strategies)

    client = TestClient(create_app(snapshot_root=local_tmp))
    response = client.get(
        "/qualifications/growth/results", params={"as_of": DAY, "limit": 10}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["strategy_id"] == "growth"
    assert data["coverage"]["strategy_eligible_count"] == 4
    assert data["coverage"]["ranked_count"] == 4
    assert data["coverage"]["percentile_pass_count"] == 3
    assert data["coverage"]["absolute_pass_count"] == 3
    assert data["coverage"]["qualified_count"] == 2
    items = data["items"]
    assert len(items) == 2
    assert items[0]["symbol"] == "600003.SH"
    assert items[0]["rank"] == 1
    assert items[1]["symbol"] == "600000.SH"
    assert items[1]["rank"] == 2


def test_qualification_results_limit_validation(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))
    res_zero = client.get(
        "/qualifications/growth/results", params={"as_of": DAY, "limit": 0}
    )
    assert res_zero.status_code == 422
    res_neg = client.get(
        "/qualifications/growth/results", params={"as_of": DAY, "limit": -5}
    )
    assert res_neg.status_code == 422
    res_large = client.get(
        "/qualifications/growth/results", params={"as_of": DAY, "limit": 501}
    )
    assert res_large.status_code == 422


def test_qualification_results_unknown_strategy_returns_404(
    local_tmp: Path,
) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))
    res = client.get(
        "/qualifications/non_existent_strategy/results", params={"as_of": DAY}
    )
    assert res.status_code == 404


def test_qualification_results_invalid_config_fails_loudly(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed(local_tmp)
    bad_dir = tmp_path / "bad_qualifications"
    bad_dir.mkdir()
    monkeypatch.setenv("ASTOCK_QUALIFICATION_DIR", str(bad_dir))

    client = TestClient(create_app(snapshot_root=local_tmp))
    res = client.get("/qualifications/growth/results", params={"as_of": DAY})
    assert res.status_code >= 400
    assert res.status_code != 200


def test_today_api_returns_aggregated_overview(local_tmp: Path) -> None:
    """Task 5: /today 返回聚合概览并保持候选原生权威顺序。"""
    from astock_lens.candidates.models import Candidate
    from astock_lens.domain.enums import MarketValidation, NextAction, Signal
    from astock_lens.qualifications.models import StrategyQualification

    store = JsonSnapshotStore(local_tmp)
    qual = StrategyQualification(
        symbol="601336.SH",
        strategy_id="value",
        strategy_version="v1",
        qualification_version="v1",
        qualified=True,
        percentile_pass=True,
        absolute_pass=True,
        rank_percentile=0.98,
        as_of=AS_OF,
    )
    c1 = Candidate(
        symbol="601336.SH",
        as_of=AS_OF,
        next_action=NextAction.WATCH,
        primary_strategy_id="value",
        strategy_qualifications=(qual,),
        market_validation=MarketValidation.NEUTRAL,
        signal=Signal.VALUE_CONTRARIAN,
        reasons=("qualified for value",),
        lineage=SnapshotLineage(
            universe_snapshot="2026-09-19:u1",
            factor_version="v1",
            strategy_version="v1",
            qualification_version="v1",
            regime_version="v1",
            market_validation_version="v1",
            signal_version="v1",
        ),
    )
    c2 = Candidate(
        symbol="300741.SZ",
        as_of=AS_OF,
        next_action=NextAction.WATCH,
        primary_strategy_id="momentum",
        strategy_qualifications=(),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.BREAKOUT,
        reasons=("qualified for momentum",),
        lineage=SnapshotLineage(
            universe_snapshot="2026-09-19:u1",
            factor_version="v1",
            strategy_version="v1",
            qualification_version="v1",
            regime_version="v1",
            market_validation_version="v1",
            signal_version="v1",
        ),
    )
    store.write(SnapshotKind.CANDIDATE, AS_OF, [c1, c2])

    client = TestClient(create_app(snapshot_root=local_tmp))
    res = client.get("/today", params={"as_of": DAY})
    assert res.status_code == 200
    data = res.json()
    assert data["candidate_count"] == 2
    assert data["counts_by_primary_strategy"] == {"value": 1, "momentum": 1}
    assert data["counts_by_market_validation"] == {"NEUTRAL": 1, "CONFIRMED": 1}
    assert data["counts_by_signal"] == {"VALUE_CONTRARIAN": 1, "BREAKOUT": 1}
    assert len(data["top_candidates"]) == 2
    assert data["top_candidates"][0]["symbol"] == "601336.SH"
    assert data["top_candidates"][1]["symbol"] == "300741.SZ"


def test_today_api_invalid_as_of_returns_422(local_tmp: Path) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))
    res = client.get("/today", params={"as_of": "not-a-date"})
    assert res.status_code == 422


def test_snapshot_dates_valid_kind_returns_sorted_dates_and_latest(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp)
    dt1 = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)
    dt2 = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
    for dt in (dt1, dt2):
        store.write(
            SnapshotKind.CANDIDATE,
            dt,
            [
                Candidate(
                    symbol="600000.SH",
                    as_of=dt,
                    next_action=NextAction.IGNORE,
                    lineage=SnapshotLineage(factor_version="v1", strategy_version="v1"),
                )
            ],
        )

    client = TestClient(create_app(snapshot_root=local_tmp))
    response = client.get("/snapshot-dates", params={"kind": "CANDIDATE"})

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "kind": "CANDIDATE",
        "dates": ["2026-09-17", "2026-09-19"],
        "latest": "2026-09-19",
    }

    default_response = client.get("/snapshot-dates")
    assert default_response.status_code == 200
    assert default_response.json() == payload


def test_snapshot_dates_empty_returns_empty_list_and_none_latest(
    local_tmp: Path,
) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))
    response = client.get("/snapshot-dates", params={"kind": "CANDIDATE"})

    assert response.status_code == 200
    assert response.json() == {
        "kind": "CANDIDATE",
        "dates": [],
        "latest": None,
    }


def test_snapshot_dates_invalid_kind_returns_422(local_tmp: Path) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))
    response = client.get("/snapshot-dates", params={"kind": "INVALID_KIND"})

    assert response.status_code == 422


def test_cors_headers_allowed_origins(local_tmp: Path) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))

    preflight = client.options(
        "/snapshot-dates",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert (
        preflight.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    )
    assert preflight.headers.get("access-control-allow-credentials") == "true"

    preflight_local = client.options(
        "/snapshot-dates",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight_local.status_code == 200
    assert (
        preflight_local.headers.get("access-control-allow-origin")
        == "http://localhost:5173"
    )

    res_127 = client.get(
        "/snapshot-dates",
        params={"kind": "CANDIDATE"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert res_127.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"

    res_local = client.get(
        "/snapshot-dates",
        params={"kind": "CANDIDATE"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert (
        res_local.headers.get("access-control-allow-origin") == "http://localhost:5173"
    )

    res_evil = client.get(
        "/snapshot-dates",
        params={"kind": "CANDIDATE"},
        headers={"Origin": "http://evil.com"},
    )
    assert "access-control-allow-origin" not in res_evil.headers
