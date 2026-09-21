"""Industry market evidence contract and calculator.

Auditable evidence layer: provides industry 20-day return, benchmark return,
and industry excess return without guessing or relabeling classification hierarchy.

Guarantees:
- Rejects requests for SW1 if canonical source only provides SW2 (no silent relabeling);
- Raises IndustryEvidenceUnavailable when industry membership, member returns, or benchmark returns are missing;
- Industry return is calculated deterministically from verified member returns.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from astock_lens.data.industry import IndustryMembership
from astock_lens.domain.models import DomainRecord


class IndustryEvidenceUnavailable(RuntimeError):
    """Raised when industry hierarchy or sufficient member returns are unavailable."""


class IndustryEvidence(DomainRecord):
    """Auditable industry-level market evidence for one symbol."""

    symbol: str
    industry_id: str
    industry_level: str
    industry_return_20d: float
    benchmark_return_20d: float
    industry_excess_return_20d: float
    as_of: datetime
    member_count: int = 0


def build_industry_evidence(
    *,
    symbol: str,
    membership: IndustryMembership | None,
    all_memberships: Sequence[IndustryMembership],
    member_returns_20d: Mapping[str, float],
    benchmark_return_20d: float | None,
    requested_level: str = "SW2",
    as_of: datetime,
) -> IndustryEvidence:
    """Build auditable industry excess return evidence for a symbol.

    Constraints:
    - If membership is None or symbol not mapped -> IndustryEvidenceUnavailable;
    - Canonical WeStock sector source is strictly SW2. If requested_level == "SW1",
      raises IndustryEvidenceUnavailable rather than falsely relabeling SW2 as SW1;
    - If benchmark_return_20d is None -> IndustryEvidenceUnavailable;
    - Computes industry_return_20d as equal-weighted mean of member returns with valid ret_20d;
    - If no members in the industry have valid returns -> IndustryEvidenceUnavailable;
    - industry_excess_return_20d = industry_return_20d - benchmark_return_20d.
    """
    if membership is None or membership.symbol != symbol:
        raise IndustryEvidenceUnavailable(
            f"No industry membership recorded for {symbol}"
        )

    # Canonical source currently only provides SW2. Never guess or relabel SW2 as SW1.
    if requested_level.upper() == "SW1":
        raise IndustryEvidenceUnavailable(
            f"SW1 hierarchy unavailable from canonical source for {symbol} (only SW2 is supported)"
        )
    if requested_level.upper() != "SW2":
        raise IndustryEvidenceUnavailable(
            f"Unsupported industry level {requested_level!r} for {symbol}"
        )

    if benchmark_return_20d is None:
        raise IndustryEvidenceUnavailable(
            f"Benchmark return is missing for industry excess calculation on {symbol}"
        )

    industry_id = membership.industry_id
    industry_members = [
        m.symbol for m in all_memberships if m.industry_id == industry_id
    ]
    if not industry_members:
        industry_members = [symbol]

    valid_returns = [
        member_returns_20d[m_sym]
        for m_sym in industry_members
        if m_sym in member_returns_20d and member_returns_20d[m_sym] is not None
    ]

    if not valid_returns:
        raise IndustryEvidenceUnavailable(
            f"No valid 20d returns found for industry {industry_id} ({membership.industry_name})"
        )

    industry_ret_20d = sum(valid_returns) / len(valid_returns)
    excess_ret = industry_ret_20d - benchmark_return_20d

    return IndustryEvidence(
        symbol=symbol,
        industry_id=industry_id,
        industry_level="SW2",
        industry_return_20d=industry_ret_20d,
        benchmark_return_20d=benchmark_return_20d,
        industry_excess_return_20d=excess_ret,
        as_of=as_of,
        member_count=len(valid_returns),
    )
