"""Factor registry.

The set of factors available to one computation run. Registration order is
preserved because it is the order a run will report in, and a stable order
makes snapshot diffs readable.
"""

from collections.abc import Sequence

from astock_lens.factors.builtin import build_factor
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import Factor


class FactorRegistry:
    """A name-indexed set of factor implementations."""

    def __init__(self) -> None:
        self._factors: dict[str, Factor] = {}

    def register(self, factor: Factor) -> None:
        """Add a factor. A duplicate name is a programming error."""
        name = factor.metadata.name
        if name in self._factors:
            raise ValueError(f"factor {name!r} is already registered")
        self._factors[name] = factor

    def get(self, name: str) -> Factor:
        """Return a registered factor, or raise if the name is unknown."""
        if name not in self._factors:
            raise KeyError(f"factor {name!r} is not registered")
        return self._factors[name]

    def names(self) -> tuple[str, ...]:
        """Return registered names in registration order."""
        return tuple(self._factors)


def build_registry(configs: Sequence[FactorConfig]) -> FactorRegistry:
    """Build a registry from configuration files, in the order given.

    An unknown factor name raises here rather than at compute time, so a run
    fails while it is being set up instead of quietly finding every symbol
    ineligible.
    """
    registry = FactorRegistry()
    for config in configs:
        registry.register(build_factor(config))
    return registry
