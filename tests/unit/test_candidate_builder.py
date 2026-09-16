"""Candidate builder tests.

The rule these tests pin down: the builder assembles, it does not decide. The
`next_action` is a parameter whose default is the inert `IGNORE`, and a
candidate whose evidence disagrees with its declared lineage is refused rather
than published with a contradictory provenance.
"""

from datetime import UTC, datetime

import pytest

from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.domain.enums import DataStatus, NextAction
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LINEAGE = SnapshotLineage(factor_version="v1", strategy_version="v1")


def _strategy_result(
    *,
    strategy_version: str = "v1",
    reasons: tuple[str, ...] = (),
    risks: tuple[str, ...] = (),
) -> StrategyResult:
    return StrategyResult(
        symbol="600000.SH",
        strategy_id="momentum",
        strategy_version=strategy_version,
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version=strategy_version),
        reasons=reasons,
        risks=risks,
        factor_snapshot=(
            FactorResult(
                symbol="600000.SH",
                factor="avg_amount_20d",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=1_000_000.0,
            ),
        ),
    )


def test_next_action_defaults_to_the_inert_choice() -> None:
    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(), lineage=LINEAGE
    )

    assert candidate.next_action is NextAction.IGNORE


def test_signal_and_market_validation_stay_unset() -> None:
    """Neither layer exists in this slice, so neither is fabricated."""
    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(), lineage=LINEAGE
    )

    assert candidate.market_validation is None
    assert candidate.signal is None


def test_lineage_mismatch_is_refused() -> None:
    result = _strategy_result(strategy_version="v2")

    with pytest.raises(ValueError, match="strategy_version"):
        CandidateBuilder().build(
            "600000.SH", as_of=AS_OF, strategy_results=(result,), lineage=LINEAGE
        )


def test_reasons_and_risks_are_aggregated_from_evidence() -> None:
    result = _strategy_result(reasons=("avg_amount_20d=1000000.0",), risks=("thin",))

    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(result,), lineage=LINEAGE
    )

    assert candidate.reasons == ("avg_amount_20d=1000000.0",)
    assert candidate.risks == ("thin",)
    assert candidate.strategy_results == (result,)


def test_candidate_is_a_research_object_not_a_recommendation() -> None:
    candidate = CandidateBuilder().build(
        "600000.SH", as_of=AS_OF, strategy_results=(), lineage=LINEAGE
    )

    assert candidate.symbol == "600000.SH"
    assert candidate.as_of == AS_OF
    assert candidate.lineage == LINEAGE
    assert candidate.next_action in set(NextAction)
