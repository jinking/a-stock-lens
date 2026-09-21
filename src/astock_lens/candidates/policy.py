"""候选资格判定与横截面选择策略。

Candidate 是研究对象，不是推荐；"哪些标的值得进入研究"是一个显式的产品选择策略。
本模块提供横截面选择契约 CandidatePolicy、输入证据模型 CandidateEvidence 以及
代表性选择实现 RepresentativeCandidatePolicy。
"""

from collections.abc import Sequence
from typing import Protocol, Self

from pydantic import model_validator

from astock_lens.domain.enums import MarketValidation, Signal
from astock_lens.domain.models import DomainRecord
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

CANDIDATE_POLICY_DEFERRED = (
    "candidate qualification policy is Deferred: no approved rule exists, so no "
    "Candidate may be published (a measured score is not a qualification)"
)


class CandidatePolicyNotConfigured(RuntimeError):
    """Raised when CandidatePolicy is not configured."""


class CandidateEvidenceIncomplete(ValueError):
    """Raised when CandidateEvidence is missing upstream market validation or signal."""


class CandidateQualification(DomainRecord):
    """Legacy verdict record kept for backward compatibility."""

    qualified: bool
    reasons: tuple[str, ...] = ()


class CandidateEvidence(DomainRecord):
    """Evidence collected for a single symbol across strategies and market/signal layers."""

    symbol: str
    strategy_results: tuple[StrategyResult, ...]
    strategy_qualifications: tuple[StrategyQualification, ...]
    market_validation: MarketValidation | None
    signal: Signal | None

    @model_validator(mode="after")
    def _validate_evidence(self) -> Self:
        for r in self.strategy_results:
            if r.symbol != self.symbol:
                raise ValueError(
                    f"StrategyResult symbol '{r.symbol}' does not match evidence symbol '{self.symbol}'"
                )
        for q in self.strategy_qualifications:
            if q.symbol != self.symbol:
                raise ValueError(
                    f"StrategyQualification symbol '{q.symbol}' does not match evidence symbol '{self.symbol}'"
                )
        if not any(q.qualified for q in self.strategy_qualifications):
            raise ValueError(
                f"CandidateEvidence for '{self.symbol}' must contain at least one qualified StrategyQualification"
            )
        return self


class CandidateSelection(DomainRecord):
    """Record of a symbol selected for candidate publishing under a specific policy."""

    symbol: str
    policy_version: str
    reasons: tuple[str, ...] = ()


class CandidatePolicy(Protocol):
    """Protocol for cross-sectional candidate selection."""

    version: str

    def select(
        self, evidence: Sequence[CandidateEvidence]
    ) -> tuple[CandidateSelection, ...]:
        """Select candidates from cross-sectional evidence."""
        ...


def _priority_key(evidence: CandidateEvidence) -> tuple[float, int, int, str]:
    """Deterministic lexicographic priority key for global ranking:

    1. best qualified rank_percentile DESC
    2. qualified strategy count DESC
    3. MarketValidation.CONFIRMED before NEUTRAL
    4. symbol ASC
    """
    qualified_quals = [q for q in evidence.strategy_qualifications if q.qualified]
    best_pct = max(q.rank_percentile for q in qualified_quals)
    qual_count = len(qualified_quals)
    mv_priority = 1 if evidence.market_validation == MarketValidation.CONFIRMED else 0
    return (-best_pct, -qual_count, -mv_priority, evidence.symbol)


class RepresentativeCandidatePolicy:
    """Approved representative cross-sectional candidate selection policy.

    Rules:
    - Daily capacity: 20-50, 50 hard cap, no minimum fill (never relaxes criteria to reach 20).
    - Soft reserve: up to `soft_reserve_per_strategy` (default 3) qualified symbols per strategy.
    - Global fill: remaining slots filled by global lexicographic priority.
    - MarketValidation.CONTRADICTED is vetoed.
    - Signal.BREAKDOWN is vetoed (approved decision D1).
    - Incomplete evidence (None market validation or signal) raises CandidateEvidenceIncomplete.
    """

    def __init__(
        self,
        *,
        version: str = "v1",
        soft_reserve_per_strategy: int = 3,
        max_candidates: int = 50,
    ) -> None:
        self.version = version
        self.soft_reserve_per_strategy = soft_reserve_per_strategy
        self.max_candidates = max_candidates

    def select(
        self, evidence: Sequence[CandidateEvidence]
    ) -> tuple[CandidateSelection, ...]:
        # Validate complete upstream evidence
        for item in evidence:
            if item.market_validation is None or item.signal is None:
                raise CandidateEvidenceIncomplete(
                    f"Evidence for symbol '{item.symbol}' is incomplete: "
                    f"market_validation={item.market_validation}, signal={item.signal}"
                )

        # Filter out vetoed evidence (CONTRADICTED market validation or BREAKDOWN signal veto - Decision D1)
        eligible = [
            item
            for item in evidence
            if item.market_validation != MarketValidation.CONTRADICTED
            and item.signal != Signal.BREAKDOWN
        ]
        if not eligible:
            return ()

        # Collect soft reserve by strategy
        strategy_ids = sorted(
            {
                q.strategy_id
                for item in eligible
                for q in item.strategy_qualifications
                if q.qualified
            }
        )

        soft_reserve_symbols: set[str] = set()
        for strategy_id in strategy_ids:
            # Find eligible symbols qualified for this strategy
            strat_items: list[tuple[float, str]] = []
            for item in eligible:
                matching_quals = [
                    q
                    for q in item.strategy_qualifications
                    if q.strategy_id == strategy_id and q.qualified
                ]
                if matching_quals:
                    best_strat_pct = max(q.rank_percentile for q in matching_quals)
                    strat_items.append((best_strat_pct, item.symbol))

            # Rank by strategy's own rank_percentile DESC, symbol ASC
            strat_items.sort(key=lambda pair: (-pair[0], pair[1]))
            for _, sym in strat_items[: self.soft_reserve_per_strategy]:
                soft_reserve_symbols.add(sym)

        # Build initial pool from soft reserve
        selected_evidence: list[CandidateEvidence] = [
            item for item in eligible if item.symbol in soft_reserve_symbols
        ]

        # Global fill for remaining capacity
        remaining_capacity = self.max_candidates - len(selected_evidence)
        if remaining_capacity > 0:
            unselected = [
                item for item in eligible if item.symbol not in soft_reserve_symbols
            ]
            unselected.sort(key=_priority_key)
            selected_evidence.extend(unselected[:remaining_capacity])

        # Deterministic global sorting
        selected_evidence.sort(key=_priority_key)

        return tuple(
            CandidateSelection(
                symbol=item.symbol,
                policy_version=self.version,
                reasons=tuple(
                    f"qualified for {q.strategy_id} (percentile={q.rank_percentile:.4f})"
                    for q in item.strategy_qualifications
                    if q.qualified
                ),
            )
            for item in selected_evidence
        )
