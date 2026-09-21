"""Candidate context resolution.

Derives deterministic strategy context for multi-strategy qualified symbols
without introducing any cross-strategy score aggregation.
"""

from collections.abc import Sequence

from astock_lens.qualifications.models import StrategyQualification


def primary_qualified_strategy(
    qualifications: Sequence[StrategyQualification],
) -> str:
    """Highest qualified rank_percentile; tie -> strategy_id ASC."""
    qualified = [q for q in qualifications if q.qualified]
    if not qualified:
        raise ValueError("no qualified strategy in qualifications")
    best = min(qualified, key=lambda q: (-q.rank_percentile, q.strategy_id))
    return best.strategy_id
