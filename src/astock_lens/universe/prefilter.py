"""Listing-only prefilter for the Research Universe.

The Research Universe is what expensive enrichment and strategy scoring are
allowed to touch, so it is built in two steps: this prefilter judges a symbol
from listing metadata alone (exchange, ST flag, delisting board, listing age),
and only the survivors are worth spending a bootstrap history on. The
data-dependent Universe rules — trades on the as-of date, liquidity, suspension
— are applied afterwards by `UniverseBuilder`, which is also the layer that
publishes the formal snapshot.

Two rules keep this module honest:

- **It owns no rule semantics.** Each check is the same function the
  `UniverseBuilder` calls, so the two layers cannot drift into disagreeing
  about what "ST" means or what the listing-age boundary is.
- **It judges only what the listing carries.** A symbol with no bars, no
  liquidity measure or no reviewed suspension threshold passes here and is
  judged later by the layer that has that evidence. Excluding it here would
  make it invisible before anything ever measured it.

The prefilter is deliberately a *population* tool, not a verdict: it returns
the symbols worth enriching plus the exclusions that explain the rest.
"""

from collections.abc import Sequence
from datetime import datetime

from astock_lens.domain.models import DomainRecord, SecurityProfile
from astock_lens.universe.builder import (
    delisting_board_exclusion,
    exchange_exclusion,
    require_timezone,
    short_listing_exclusion,
    st_exclusion,
)
from astock_lens.universe.config import UniverseConfig
from astock_lens.universe.models import UniverseExclusion

# The listing-only rules, in the order their verdicts are reported. Long
# suspension is absent on purpose: it needs a reviewed day count that no design
# document has approved, so the prefilter must not evaluate it.
LISTING_RULE_CHECKS = (
    exchange_exclusion,
    st_exclusion,
    delisting_board_exclusion,
    short_listing_exclusion,
)


class PrefilterResult(DomainRecord):
    """Which symbols a listing-level screen kept, and why it dropped the rest."""

    included: tuple[str, ...]
    excluded: tuple[UniverseExclusion, ...]


def prefilter_listing(
    securities: Sequence[SecurityProfile],
    *,
    config: UniverseConfig,
    as_of: datetime,
) -> PrefilterResult:
    """Apply the listing-only rules to every profile, in symbol order.

    Every failed rule is reported rather than only the first, for the same
    reason the Universe snapshot reports them all: a reader asking "why is this
    symbol missing?" must get the complete answer.
    """
    require_timezone(as_of)

    included: list[str] = []
    excluded: list[UniverseExclusion] = []
    for profile in sorted(securities, key=lambda item: item.symbol):
        found = [
            exclusion
            for exclusion in (
                check(profile, config, as_of) for check in LISTING_RULE_CHECKS
            )
            if exclusion is not None
        ]
        if found:
            excluded.extend(found)
        else:
            included.append(profile.symbol)

    return PrefilterResult(included=tuple(included), excluded=tuple(excluded))
