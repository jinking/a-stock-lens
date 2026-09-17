"""Candidate builder.

The builder assembles evidence; it does not decide what to do with it.
Qualification belongs to `astock_lens.candidates.policy`, so a
builder that derived the action from a score would be making a product decision
nobody approved.
"""

from datetime import datetime

from astock_lens.candidates.models import Candidate
from astock_lens.candidates.policy import CandidateEvidence, CandidateSelection
from astock_lens.domain.enums import NextAction
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult


class CandidateBuilder:
    """Build one candidate from selection and evidence."""

    def build(
        self,
        symbol: str | None = None,
        *,
        evidence: CandidateEvidence | None = None,
        selection: CandidateSelection | None = None,
        as_of: datetime,
        strategy_results: tuple[StrategyResult, ...] = (),
        lineage: SnapshotLineage,
        next_action: NextAction | None = None,
        qualification_reasons: tuple[str, ...] = (),
    ) -> Candidate:
        """Assemble a candidate from selection and evidence, or fallback for legacy calls."""
        if evidence is not None:
            if selection is None:
                raise ValueError("selection is required when evidence is provided")
            if evidence.symbol != selection.symbol:
                raise ValueError(
                    f"Symbol mismatch: evidence symbol '{evidence.symbol}' != selection symbol '{selection.symbol}'"
                )

            # Retain only StrategyResults corresponding to qualified=True qualifications
            qualified_strategy_ids = {
                q.strategy_id for q in evidence.strategy_qualifications if q.qualified
            }
            qualified_results = tuple(
                r
                for r in evidence.strategy_results
                if r.strategy_id in qualified_strategy_ids
            )
            qualified_quals = tuple(
                q for q in evidence.strategy_qualifications if q.qualified
            )

            # Update lineage with qualification_version and candidate_policy_version
            qual_versions = ",".join(
                sorted({q.qualification_version for q in qualified_quals})
            )
            updated_lineage = lineage.model_copy(
                update={
                    "qualification_version": qual_versions,
                    "candidate_policy_version": selection.policy_version,
                }
            )

            action = next_action if next_action is not None else NextAction.WATCH

            return Candidate(
                symbol=selection.symbol,
                as_of=as_of,
                next_action=action,
                lineage=updated_lineage,
                candidate_policy_version=selection.policy_version,
                strategy_results=qualified_results,
                strategy_qualifications=qualified_quals,
                market_validation=evidence.market_validation,
                signal=evidence.signal,
                reasons=(
                    *selection.reasons,
                    *(r for res in qualified_results for r in res.reasons),
                ),
                risks=tuple(r for res in qualified_results for r in res.risks),
            )

        # Legacy fallback
        sym = symbol or (strategy_results[0].symbol if strategy_results else "")
        declared = lineage.strategy_versions()
        for result in strategy_results:
            if result.lineage.strategy_version not in declared:
                raise ValueError(
                    f"strategy result for {result.strategy_id!r} carries "
                    f"strategy_version {result.lineage.strategy_version!r}, but the "
                    f"candidate lineage declares {lineage.strategy_version!r}"
                )

        action = next_action if next_action is not None else NextAction.IGNORE
        return Candidate(
            symbol=sym,
            as_of=as_of,
            next_action=action,
            lineage=lineage,
            candidate_policy_version="legacy",
            strategy_results=strategy_results,
            reasons=(
                *qualification_reasons,
                *(reason for result in strategy_results for reason in result.reasons),
            ),
            risks=tuple(risk for result in strategy_results for risk in result.risks),
        )
