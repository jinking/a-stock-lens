"""Bootstrap-history requirement for the Research Universe.

A cold start cannot know which symbols are liquid before it has some price
history: `avg_amount_20d` is *measured* over a window, so the window has to be
fetched before the Universe rule can compare it against the approved floor. How
many bars that takes is not a number this module may choose — it is the window
the configured liquidity factor declares, read from `configs/factors/*.yaml`.

Two failure modes are kept loud:

- the liquidity factor is not among the configured factors at all;
- the factor is configured but its window has not been reviewed (`window: null`,
  the same convention `configs/universe.yaml` uses for deferred rules).

Neither falls back to a default. A guessed window would silently change which
symbols qualify for research, which is a product decision, not an
implementation detail.
"""

from collections.abc import Sequence

from astock_lens.domain.models import DomainRecord
from astock_lens.factors.config import FactorConfig

# The Universe owns the name of the factor its liquidity rule consumes. It is
# imported rather than restated so the bootstrap can never measure a different
# quantity from the one the Universe compares against its floor.
from astock_lens.universe.builder import LIQUIDITY_FACTOR


class BootstrapRequirementNotConfigured(RuntimeError):
    """Raised when no reviewed liquidity window can be resolved from config."""


class BootstrapRequirement(DomainRecord):
    """How much price history the liquidity rule needs before it can be applied."""

    factor_name: str
    required_valid_bars: int


def liquidity_bootstrap_requirement(
    factor_configs: Sequence[FactorConfig],
) -> BootstrapRequirement:
    """Derive the bootstrap window from the configured liquidity factor.

    Only the factor's own window is consulted; the threshold it will be compared
    against lives in `configs/universe.yaml` and is not this module's business.
    """
    for config in factor_configs:
        if config.name != LIQUIDITY_FACTOR:
            continue
        window = config.params.get("window")
        if window is None:
            raise BootstrapRequirementNotConfigured(
                f"{LIQUIDITY_FACTOR} declares no window (its 'window' parameter "
                "is null): no reviewed window exists, so the bootstrap length "
                "cannot be derived and must not be guessed"
            )
        if window <= 0:
            raise BootstrapRequirementNotConfigured(
                f"{LIQUIDITY_FACTOR} declares window {window}, which cannot "
                "describe a trailing average"
            )
        return BootstrapRequirement(factor_name=config.name, required_valid_bars=window)

    raise BootstrapRequirementNotConfigured(
        f"no factor configuration for {LIQUIDITY_FACTOR}: the Universe's "
        "liquidity rule cannot be bootstrapped without the window its factor "
        "is defined over"
    )
