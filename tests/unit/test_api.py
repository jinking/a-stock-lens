"""Domain API tests.

The rule these tests pin down: the API reads stored snapshots. It never
recomputes a factor (`docs/ARCHITECTURE.md` §2), and a missing snapshot is a
404 that says so rather than a 500.
"""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

import astock_lens.api.app as api_module
from astock_lens.api.app import create_app
from astock_lens.candidates.models import Candidate
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import DataStatus, NextAction, SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
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
    """ARCHITECTURE.md §2: the API must not recompute factors."""
    source = Path(api_module.__file__).read_text(encoding="utf-8")

    assert "factors.builtin" not in source
    assert "strategies.momentum" not in source
    assert "AverageAmountFactor" not in source
    assert "MomentumScanner" not in source


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
