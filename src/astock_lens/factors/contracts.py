"""Factor engine contracts.

Factors produce objective raw values. Strategy interpretation and scoring live
in the strategy layer and are never computed here.
"""

from datetime import datetime
from typing import Protocol

from astock_lens.data.contracts import NormalizedDataset
from astock_lens.domain.enums import DataStatus, FactorDomain
from astock_lens.domain.models import DomainRecord, SnapshotLineage


class FactorMetadata(DomainRecord):
    """Metadata every factor must declare.

    `frequency`, `direction`, and `null_policy` are free-form because the
    design does not enumerate their vocabularies. Their value sets stay
    explicitly deferred instead of being invented here.
    """

    name: str
    domain: FactorDomain
    description: str
    inputs: tuple[str, ...]
    frequency: str
    direction: str
    null_policy: str
    version: str


class FactorContext(DomainRecord):
    """Inputs available to a factor computation."""

    symbol: str
    as_of: datetime
    dataset: NormalizedDataset


class FactorResult(DomainRecord):
    """One factor value for one symbol at one point in time."""

    symbol: str
    factor: str
    as_of: datetime
    status: DataStatus
    factor_version: str
    lineage: SnapshotLineage
    raw_value: float | None = None


class Factor(Protocol):
    """A first-class versioned factor component."""

    metadata: FactorMetadata

    def compute(self, context: FactorContext) -> FactorResult:
        """Compute the raw factor value for a symbol.

        The result reports a `DataStatus`; missing inputs stay missing.
        """
        ...
