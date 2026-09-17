"""Weighted scoring tests.

This is the machine that turns a reviewed weight set into a score, so the tests
pin down the conventions a reviewer is agreeing to when they approve numbers:

- the sign of a weight carries polarity, so a factor where lower is better
  (`debt_to_asset`, `goodwill_to_equity`) is oriented before ranking;
- only eligible symbols enter the population, so missing evidence shifts
  nobody's percentile;
- weights must cover the required factors exactly, and a zero weight is
  refused rather than silently ignored;
- `confidence` stays absent, because the design defines no algorithm for it.
"""

from datetime import UTC, datetime

import pytest

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import StrategyContext
from astock_lens.strategies.weighted import WeightedPercentileScanner

AS_OF = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)


def _config(**overrides: object) -> StrategyConfig:
    payload: dict[str, object] = {
        "id": "quality",
        "version": "v1",
        "description": "quality",
        "required_factors": ["roe_ttm", "debt_to_asset"],
        "weights": {"roe_ttm": 1.0, "debt_to_asset": -1.0},
    }
    payload.update(overrides)
    return StrategyConfig.model_validate(payload)


def _factor(symbol: str, name: str, value: float | None) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=AS_OF,
        status=DataStatus.VALUE if value is not None else DataStatus.NULL,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _context(symbol: str, roe: float | None, debt: float | None) -> StrategyContext:
    return StrategyContext(
        symbol=symbol,
        as_of=AS_OF,
        factors=(
            _factor(symbol, "roe_ttm", roe),
            _factor(symbol, "debt_to_asset", debt),
        ),
    )


def _by_symbol(results: object) -> dict[str, object]:
    return {result.symbol: result for result in results}  # type: ignore[attr-defined]


def test_a_negative_weight_orients_a_factor_where_lower_is_better() -> None:
    """High ROE and low leverage must both raise the score."""
    scanner = WeightedPercentileScanner(_config())
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("MIDDLE", roe=15.0, debt=30.0),
        _context("BAD", roe=5.0, debt=90.0),
    )

    results = _by_symbol(scanner.score_cross_section(contexts))

    assert results["GOOD"].score > results["MIDDLE"].score > results["BAD"].score
    assert results["GOOD"].rank_percentile == 1.0
    assert results["BAD"].rank_percentile == pytest.approx(1 / 3)


def test_the_orientation_is_visible_in_the_contribution() -> None:
    """A reader must be able to see that leverage was inverted, not added."""
    scanner = WeightedPercentileScanner(_config())
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("BAD", roe=5.0, debt=90.0),
    )

    result = _by_symbol(scanner.score_cross_section(contexts))["GOOD"]
    contributions = {item.factor: item for item in result.contributions}

    assert contributions["roe_ttm"].percentile == 1.0
    assert contributions["debt_to_asset"].percentile == 1.0  # inverted: 10 < 90
    assert contributions["debt_to_asset"].weight == -1.0


def test_an_ineligible_symbol_shifts_nobody_else() -> None:
    """A missing factor must not move the population's percentiles."""
    scanner = WeightedPercentileScanner(_config())
    with_missing = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("BAD", roe=5.0, debt=90.0),
        _context("UNKNOWN", roe=None, debt=50.0),
    )

    results = _by_symbol(scanner.score_cross_section(with_missing))

    assert results["GOOD"].score == 100.0
    assert results["GOOD"].rank_percentile == 1.0
    assert results["UNKNOWN"].eligible is False
    assert results["UNKNOWN"].score is None
    assert "roe_ttm is NULL, not VALUE" in results["UNKNOWN"].risks


def test_a_single_symbol_population_gets_a_score_but_no_rank() -> None:
    """A percentile against nobody is not a percentile."""
    scanner = WeightedPercentileScanner(_config())

    result = scanner.score_cross_section((_context("ONLY", 20.0, 10.0),))[0]

    assert result.score == 100.0
    assert result.rank_percentile is None


def test_scoring_one_symbol_alone_reports_no_score() -> None:
    """`score()` has no population, so it reports eligibility only."""
    scanner = WeightedPercentileScanner(_config())

    result = scanner.score(_context("ONLY", 20.0, 10.0))

    assert result.eligible is True
    assert result.score is None
    assert result.rank_percentile is None
    assert result.confidence is None


def test_the_explanation_shows_each_factor_and_its_weight() -> None:
    scanner = WeightedPercentileScanner(_config())
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("BAD", roe=5.0, debt=90.0),
    )
    result = scanner.score_cross_section(contexts)[0]

    explanation = scanner.explain(result)

    assert "score" in explanation.summary
    assert {item.factor for item in explanation.factors} == {
        "roe_ttm",
        "debt_to_asset",
    }
    assert any("weight -1.0" in item.note for item in explanation.factors)


def test_weights_must_cover_the_required_factors_exactly() -> None:
    with pytest.raises(ValueError, match="must cover required_factors exactly"):
        WeightedPercentileScanner(_config(weights={"roe_ttm": 1.0}))


def test_a_zero_weight_is_refused() -> None:
    """A factor with no weight does not belong in the strategy's requirements."""
    with pytest.raises(ValueError, match="does not belong"):
        WeightedPercentileScanner(
            _config(weights={"roe_ttm": 1.0, "debt_to_asset": 0.0})
        )


def test_a_strategy_without_weights_is_not_scored_here() -> None:
    with pytest.raises(ValueError, match="declares no weights"):
        WeightedPercentileScanner(_config(weights={}))
