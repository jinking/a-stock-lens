"""Candidate builder.

The builder assembles evidence; it does not decide what to do with it. The
`next_action` is a parameter, and its default is `IGNORE` — the one action that
asserts nothing. Qualification belongs to `astock_lens.candidates.policy`, so a
builder that derived the action from a score would be making a product decision
nobody approved.

`qualification_reasons` carries the policy's own explanation next to the
strategy evidence, so a stored candidate can say not only what was measured but
why it was selected.
"""

from datetime import datetime

from astock_lens.candidates.models import Candidate
from astock_lens.domain.enums import NextAction
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.contracts import StrategyResult


class CandidateBuilder:
    """Build one candidate from strategy evidence."""

    def build(
        self,
        symbol: str,
        *,
        as_of: datetime,
        strategy_results: tuple[StrategyResult, ...],
        lineage: SnapshotLineage,
        next_action: NextAction = NextAction.IGNORE,
        qualification_reasons: tuple[str, ...] = (),
    ) -> Candidate:
        """Assemble a candidate, refusing evidence that contradicts its lineage."""
        declared = lineage.strategy_versions()
        for result in strategy_results:
            if result.lineage.strategy_version not in declared:
                raise ValueError(
                    f"strategy result for {result.strategy_id!r} carries "
                    f"strategy_version {result.lineage.strategy_version!r}, but the "
                    f"candidate lineage declares {lineage.strategy_version!r}"
                )

        return Candidate(
            symbol=symbol,
            as_of=as_of,
            next_action=next_action,
            lineage=lineage,
            strategy_results=strategy_results,
            reasons=(
                *qualification_reasons,
                *(reason for result in strategy_results for reason in result.reasons),
            ),
            risks=tuple(risk for result in strategy_results for risk in result.risks),
        )
