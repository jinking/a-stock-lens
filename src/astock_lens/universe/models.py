"""Universe records.

A snapshot answers two questions, and it answers both explicitly: which symbols
are in scope, and why each of the others is not. A snapshot that listed only
the survivors would make "why is this symbol missing?" unanswerable, which is
the failure mode the design's explainability principle is written against.
"""

from datetime import datetime
from enum import StrEnum

from astock_lens.domain.models import DomainRecord, SnapshotLineage


class UniverseRule(StrEnum):
    """The rules a symbol can fail.

    This vocabulary belongs to the implementation, not to a design document.
    `domain/enums.py` stays reserved for vocabularies the design actually
    enumerates, so these names live next to the code that applies them.
    """

    EXCHANGE = "EXCHANGE"
    ST = "ST"
    DELISTING_BOARD = "DELISTING_BOARD"
    LONG_SUSPENSION = "LONG_SUSPENSION"
    SHORT_LISTING = "SHORT_LISTING"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    NO_MARKET_DATA = "NO_MARKET_DATA"
    NO_LIQUIDITY_MEASURE = "NO_LIQUIDITY_MEASURE"


class UniverseExclusion(DomainRecord):
    """One symbol, one rule it failed, and the evidence for that verdict."""

    symbol: str
    rule: UniverseRule
    detail: str


class DeferredRule(DomainRecord):
    """A rule the configuration switches on but no threshold can evaluate.

    Recorded rather than dropped: a reader must be able to tell "this symbol is
    not on the exchange list" from "this rule never ran".
    """

    rule: UniverseRule
    reason: str


class UniverseSnapshot(DomainRecord):
    """The immutable set of symbols one scan considered, and the reasons why."""

    as_of: datetime
    snapshot_id: str
    config_digest: str
    lineage: SnapshotLineage
    included: tuple[str, ...] = ()
    exclusions: tuple[UniverseExclusion, ...] = ()
    deferred_rules: tuple[DeferredRule, ...] = ()
