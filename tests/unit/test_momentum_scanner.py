"""Momentum scanner tests.

The rule these tests pin down: `score()` answers for one symbol, and a
percentile needs a population, so it decides *eligibility* and does not rank. A
score of `None` states that no cross-section was available — it never stands in
a plausible-looking number. The ranking itself is covered by
`test_strategy_scoring.py`.

Factor names are read from the configuration rather than written here, so the
scanner's contract stays under test when the strategy's factor set changes.
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
CONFIG = load_strategy_config(CONFIG_PATH)
REQUIRED = CONFIG.required_factors
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _scanner() -> MomentumScanner:
    return MomentumScanner(CONFIG)


def _factor_result(name: str, status: DataStatus, value: float | None) -> FactorResult:
    return FactorResult(
        symbol="600000.SH",
        factor=name,
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _valued() -> tuple[FactorResult, ...]:
    """Every configured factor, each carrying a value."""
    return tuple(
        _factor_result(name, DataStatus.VALUE, 1_000_000.0) for name in REQUIRED
    )


def _null_last() -> tuple[FactorResult, ...]:
    return (*_valued()[:-1], _factor_result(REQUIRED[-1], DataStatus.NULL, None))


def _context(*results: FactorResult) -> StrategyContext:
    return StrategyContext(
        symbol="600000.SH",
        as_of=AS_OF,
        factors=results,
        market_regime=MarketRegime.RANGE,
    )


def test_required_factors_come_from_the_config_file() -> None:
    assert _scanner().required_factors() == set(REQUIRED)


def test_eligible_when_every_required_factor_has_a_value() -> None:
    result = _scanner().eligibility(_context(*_valued()))

    assert result.eligible is True
    assert result.reasons == ()


def test_missing_factor_makes_the_symbol_ineligible() -> None:
    result = _scanner().eligibility(_context(*_valued()[:-1]))

    assert result.eligible is False
    assert any(REQUIRED[-1] in reason for reason in result.reasons)


def test_null_factor_makes_the_symbol_ineligible() -> None:
    result = _scanner().eligibility(_context(*_null_last()))

    assert result.eligible is False
    assert any("NULL" in reason for reason in result.reasons)


def test_scoring_is_explicitly_absent_for_a_lone_symbol() -> None:
    """One symbol, no population to rank against, so no score is invented."""
    result = _scanner().score(_context(*_valued()))

    assert result.score is None
    assert result.rank_percentile is None
    assert result.confidence is None
    assert result.contributions == ()


def test_score_result_keeps_its_evidence() -> None:
    context = _context(*_valued())

    result = _scanner().score(context)

    assert result.eligible is True
    assert result.factor_snapshot == context.factors
    assert result.strategy_id == "momentum"
    assert result.strategy_version == "v1"
    assert result.lineage.strategy_version == "v1"
    assert any(REQUIRED[0] in reason for reason in result.reasons)


def test_ineligible_context_is_carried_into_risks() -> None:
    result = _scanner().score(_context(*_null_last()))

    assert result.eligible is False
    assert result.risks


def test_explain_reports_per_factor_notes() -> None:
    context = _context(*_valued())

    explanation = _scanner().explain(_scanner().score(context))

    assert explanation.symbol == "600000.SH"
    assert "momentum v1" in explanation.summary
    assert "eligible" in explanation.summary
    assert "eligibility only" in explanation.summary
    assert [note.factor for note in explanation.factors] == list(REQUIRED)
    assert explanation.factors[0].note == "1000000.0"


def test_explain_reports_a_missing_value_as_missing() -> None:
    context = _context(*_null_last())

    explanation = _scanner().explain(_scanner().score(context))

    assert explanation.factors[-1].note == "no value (NULL)"
