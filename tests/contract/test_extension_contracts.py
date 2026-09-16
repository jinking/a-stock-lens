from astock_lens.data.contracts import DataProvider, Normalizer
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
