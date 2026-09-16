"""Momentum scanner tests.

The rule these tests pin down: this slice decides *eligibility*, not rank. A
score of `None` states that scoring is not implemented — it never stands in a
plausible-looking number.
"""

from datetime import UTC, datetime
from pathlib import Path

from astock_lens.domain.enums import DataStatus, MarketRegime
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.config import load_strategy_config
from astock_lens.strategies.contracts import StrategyContext
from astock_lens.strategies.momentum import MomentumScanner

CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "strategies" / "momentum.yaml"
)
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _scanner() -> MomentumScanner:
    return MomentumScanner(load_strategy_config(CONFIG_PATH))


def _factor_result(status: DataStatus, value: float | None) -> FactorResult:
    return FactorResult(
        symbol="600000.SH",
        factor="avg_amount_20d",
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _context(*results: FactorResult) -> StrategyContext:
    return StrategyContext(
        symbol="600000.SH",
        as_of=AS_OF,
        factors=results,
        market_regime=MarketRegime.RANGE,
    )


def test_required_factors_come_from_the_config_file() -> None:
    assert _scanner().required_factors() == {"avg_amount_20d"}


def test_eligible_when_every_required_factor_has_a_value() -> None:
    result = _scanner().eligibility(
        _context(_factor_result(DataStatus.VALUE, 1_000_000.0))
    )

    assert result.eligible is True
    assert result.reasons == ()


def test_missing_factor_makes_the_symbol_ineligible() -> None:
    result = _scanner().eligibility(_context())

    assert result.eligible is False
    assert any("avg_amount_20d" in reason for reason in result.reasons)


def test_null_factor_makes_the_symbol_ineligible() -> None:
    result = _scanner().eligibility(_context(_factor_result(DataStatus.NULL, None)))

    assert result.eligible is False
    assert any("NULL" in reason for reason in result.reasons)


def test_scoring_is_explicitly_absent() -> None:
    """No weight has been reviewed, so no score is produced."""
    context = _context(_factor_result(DataStatus.VALUE, 1_000_000.0))

    result = _scanner().score(context)

    assert result.score is None
    assert result.rank_percentile is None
    assert result.confidence is None


def test_score_result_keeps_its_evidence() -> None:
    context = _context(_factor_result(DataStatus.VALUE, 1_000_000.0))

    result = _scanner().score(context)

    assert result.eligible is True
    assert result.factor_snapshot == context.factors
    assert result.strategy_id == "momentum"
    assert result.strategy_version == "v1"
    assert result.lineage.strategy_version == "v1"
    assert any("avg_amount_20d" in reason for reason in result.reasons)


def test_ineligible_context_is_carried_into_risks() -> None:
    result = _scanner().score(_context(_factor_result(DataStatus.NULL, None)))

    assert result.eligible is False
    assert result.risks


def test_explain_reports_per_factor_notes() -> None:
    context = _context(_factor_result(DataStatus.VALUE, 1_000_000.0))

    explanation = _scanner().explain(_scanner().score(context))

    assert explanation.symbol == "600000.SH"
    assert "momentum v1" in explanation.summary
    assert "eligible" in explanation.summary
    assert "eligibility only" in explanation.summary
    assert [note.factor for note in explanation.factors] == ["avg_amount_20d"]
    assert explanation.factors[0].note == "1000000.0"


def test_explain_reports_a_missing_value_as_missing() -> None:
    context = _context(_factor_result(DataStatus.NULL, None))

    explanation = _scanner().explain(_scanner().score(context))

    assert explanation.factors[0].note == "no value (NULL)"
