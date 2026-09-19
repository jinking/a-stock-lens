"""Domain API tests.

The rule these tests pin down: the API reads stored snapshots. It never
recomputes a factor (`docs/ARCHITECTURE.md` §2), and a missing snapshot is a
404 that says so rather than a 500.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import astock_lens.api.app as api_module
from astock_lens.api.app import create_app
from astock_lens.candidates.models import Candidate
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import DataStatus, NextAction, SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult
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


def test_missing_snapshot_is_a_404(local_tmp: Path) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/factors", params={"symbol": "600000.SH", "as_of": DAY})

    assert response.status_code == 404
    assert DAY in response.json()["detail"]


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


def test_universe_route_404s_when_no_universe_was_built(local_tmp: Path) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/universe", params={"as_of": DAY})

    assert response.status_code == 404
    assert DAY in response.json()["detail"]


def test_api_never_imports_the_computation_engines() -> None:
    """ARCHITECTURE.md §2: the API must not recompute factors or scanners."""
    source = Path(api_module.__file__).read_text(encoding="utf-8")

    assert "factors.builtin" not in source
    assert "strategies.momentum" not in source
    assert "AverageAmountFactor" not in source
    assert "MomentumScanner" not in source
    assert "astock_lens.pipelines" not in source
    assert "build_scanner" not in source
    assert "strategy_stage" not in source
    assert "factor_stage" not in source
    assert "run_analysis" not in source


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


def test_strategies_route_404s_when_no_snapshot(local_tmp: Path) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get("/strategies", params={"as_of": DAY})

    assert response.status_code == 404
    assert DAY in response.json()["detail"]


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


@pytest.mark.parametrize(
    ("param", "value"),
    [
        ("limit", 0),
        ("limit", -1),
        ("limit", 501),
        ("min_percentile", -0.1),
        ("min_percentile", 1.1),
    ],
)
def test_strategy_results_invalid_query_returns_422(
    local_tmp: Path, param: str, value: object
) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get(
        "/strategies/growth/results",
        params={"as_of": DAY, param: value},
    )

    assert response.status_code == 422


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


def test_strategy_results_missing_snapshot_returns_404(local_tmp: Path) -> None:
    client = TestClient(create_app(snapshot_root=local_tmp))

    response = client.get(
        "/strategies/growth/results",
        params={"as_of": DAY},
    )

    assert response.status_code == 404
    assert DAY in response.json()["detail"]
