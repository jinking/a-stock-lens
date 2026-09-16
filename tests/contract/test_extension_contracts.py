from pathlib import Path

from astock_lens.data.contracts import DataProvider, Normalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.factors.contracts import Factor
from astock_lens.research.contracts import DeepResearchAdapter
from astock_lens.signals.contracts import SignalDetector
from astock_lens.strategies.contracts import StrategyPlugin


def test_required_contract_methods_are_stable() -> None:
    assert {"health", "fetch"} <= set(DataProvider.__dict__)
    assert {"normalize"} <= set(Normalizer.__dict__)
    assert {"compute"} <= set(Factor.__dict__)
    assert {"required_factors", "eligibility", "score", "explain"} <= set(
        StrategyPlugin.__dict__
    )
    assert {"detect"} <= set(SignalDetector.__dict__)
    assert {"submit", "status", "result"} <= set(DeepResearchAdapter.__dict__)


def test_local_csv_provider_satisfies_the_provider_contract() -> None:
    """The assignment is the assertion: the type checker verifies conformance."""
    provider: DataProvider = LocalCsvProvider(Path("."))

    assert provider is not None
