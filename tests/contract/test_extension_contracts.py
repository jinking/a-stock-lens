from pathlib import Path

from astock_lens.data.contracts import DataProvider, Normalizer
from astock_lens.data.providers.akshare_provider import AkShareProvider
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.snapshots.store import JsonSnapshotStore, SnapshotStore
from astock_lens.factors.contracts import Factor
from astock_lens.research.contracts import DeepResearchAdapter
from astock_lens.signals.contracts import SignalDetector
from astock_lens.strategies.contracts import StrategyPlugin
from astock_lens.watchlist.store import JsonWatchlistStore, WatchlistStore


def test_required_contract_methods_are_stable() -> None:
    assert {"health", "fetch"} <= set(DataProvider.__dict__)
    assert {"normalize"} <= set(Normalizer.__dict__)
    assert {"compute"} <= set(Factor.__dict__)
    assert {"required_factors", "eligibility", "score", "explain"} <= set(
        StrategyPlugin.__dict__
    )
    assert {"score_cross_section"} <= set(StrategyPlugin.__dict__)
    assert {"detect"} <= set(SignalDetector.__dict__)
    assert {"submit", "status", "result"} <= set(DeepResearchAdapter.__dict__)


def test_local_csv_provider_satisfies_the_provider_contract() -> None:
    """The assignment is the assertion: the type checker verifies conformance."""
    provider: DataProvider = LocalCsvProvider(Path("."))

    assert provider is not None


def test_akshare_provider_satisfies_the_provider_contract() -> None:
    """Both providers are interchangeable behind the same protocol."""
    provider: DataProvider = AkShareProvider()

    assert provider is not None


def test_westock_bars_provider_satisfies_the_provider_contract() -> None:
    from astock_lens.data.providers.westock_bars import WestockBarsProvider

    provider: DataProvider = WestockBarsProvider()

    assert provider is not None


def test_snapshot_store_contract_is_stable() -> None:
    assert {"write", "read"} <= set(SnapshotStore.__dict__)


def test_json_snapshot_store_satisfies_the_snapshot_contract() -> None:
    """Both stores are interchangeable, so both are bound to this protocol."""
    store: SnapshotStore = JsonSnapshotStore(Path("."))

    assert store is not None


def test_watchlist_store_contract_is_stable() -> None:
    assert {"write", "read", "symbols"} <= set(WatchlistStore.__dict__)


def test_json_watchlist_store_satisfies_the_contract() -> None:
    """Both watchlist backends are bound to the same protocol."""
    store: WatchlistStore = JsonWatchlistStore(Path("."))

    assert store is not None
