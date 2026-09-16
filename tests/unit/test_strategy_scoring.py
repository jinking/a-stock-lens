"""Cross-sectional scoring.

A score states where a symbol sits among the symbols it was ranked against, so
every test here supplies a population. The arithmetic is asserted; the weights
are read from configuration and are deliberately not hard-coded, because
`docs/ARCHITECTURE.md` §8.3 keeps them out of the engine.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import StrategyContext, StrategyResult
from astock_lens.strategies.momentum import MomentumScanner
from astock_lens.strategies.scoring import percentile_ranks

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "strategies" / "momentum.yaml"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)

FACTORS = ("ret_20d", "ret_60d", "proximity_52w_high")


def _config(weights: dict[str, float] | None = None) -> StrategyConfig:
    base = load_strategy_config(CONFIG_PATH)
    if weights is None:
        return base
    return base.model_copy(update={"weights": weights})


def _scanner(weights: dict[str, float] | None = None) -> MomentumScanner:
    return MomentumScanner(_config(weights))


def _result(symbol: str, factor: str, value: float | None) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=AS_OF,
        status=DataStatus.VALUE if value is not None else DataStatus.NULL,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _context(symbol: str, **values: float | None) -> StrategyContext:
    """One context carrying exactly the named factor values."""
    return StrategyContext(
        symbol=symbol,
        as_of=AS_OF,
        factors=tuple(_result(symbol, name, value) for name, value in values.items()),
    )


def _full(symbol: str, ret_20d: float, ret_60d: float, high: float) -> StrategyContext:
    return _context(symbol, ret_20d=ret_20d, ret_60d=ret_60d, proximity_52w_high=high)


def _ranked() -> tuple[StrategyContext, ...]:
    """Three symbols whose factor percentiles are 1, 2/3, and 1/3."""
    return [
        _full("A", 3.0, 3.0, 3.0),
        _full("B", 2.0, 2.0, 2.0),
        _full("C", 1.0, 1.0, 1.0),
    ]


def _scored(
    contexts: list[StrategyContext],
    weights: dict[str, float] | None = None,
) -> dict[str, StrategyResult]:
    return {r.symbol: r for r in _scanner(weights).score_cross_section(contexts)}


# --- percentile ranks --------------------------------------------------------


def test_percentile_ranks_are_monotonic_and_bounded() -> None:
    ranks = percentile_ranks({"a": 1.0, "b": 2.0, "c": 3.0})

    assert ranks["a"] < ranks["b"] < ranks["c"]
    assert ranks["c"] == pytest.approx(1.0)
    assert all(0.0 < rank <= 1.0 for rank in ranks.values())


def test_ties_share_the_average_rank() -> None:
    ranks = percentile_ranks({"a": 5.0, "b": 5.0, "c": 1.0})

    assert ranks["a"] == pytest.approx(ranks["b"])
    assert ranks["c"] < ranks["a"]


def test_a_single_value_maps_to_one() -> None:
    assert percentile_ranks({"only": 3.0}) == {"only": pytest.approx(1.0)}


def test_an_empty_population_is_empty() -> None:
    assert percentile_ranks({}) == {}


# --- the blend ---------------------------------------------------------------


def test_the_score_is_the_weighted_percentile_blend() -> None:
    """Equal weights over three factors give the mean of the three percentiles."""
    scored = _scored(_ranked())

    assert scored["A"].score == pytest.approx(100.0)
    assert scored["B"].score == pytest.approx(200 / 3)
    assert scored["C"].score == pytest.approx(100 / 3)


def test_weights_change_the_ranking_without_touching_the_engine() -> None:
    """A is stronger on the 20-day horizon, B on the 60-day one."""
    contexts = [_full("A", 3.0, 1.0, 1.0), _full("B", 1.0, 3.0, 1.0)]

    equally_weighted = _scored(contexts)
    assert equally_weighted["A"].score == pytest.approx(equally_weighted["B"].score)

    tilted = _scored(
        contexts,
        {"ret_20d": 3.0, "ret_60d": 1.0, "proximity_52w_high": 1.0},
    )
    assert tilted["A"].score is not None
    assert tilted["B"].score is not None
    assert tilted["A"].score > tilted["B"].score


def test_every_score_stays_within_zero_and_one_hundred() -> None:
    for result in _scored(_ranked()).values():
        assert result.score is not None
        assert 0.0 <= result.score <= 100.0


def test_contributions_record_each_factor() -> None:
    top = _scored(_ranked())["A"]

    assert [contribution.factor for contribution in top.contributions] == list(FACTORS)
    assert all(
        contribution.percentile == pytest.approx(1.0)
        for contribution in top.contributions
    )
    assert sum(
        contribution.weighted for contribution in top.contributions
    ) == pytest.approx(1.0)


def test_contributions_are_ordered_as_the_configuration_declares_them() -> None:
    """Weight order comes from the config, so an explanation reads predictably."""
    contributions = _scored(_ranked())["A"].contributions

    assert [contribution.factor for contribution in contributions] == [
        name for name in load_strategy_config(CONFIG_PATH).weights
    ]


# --- population rules --------------------------------------------------------


def test_an_ineligible_symbol_does_not_move_the_ranking() -> None:
    """Ranking against a symbol with missing data would shift everyone else."""
    alone = _scored(_ranked()[:2])
    with_gap = _scored([*_ranked()[:2], _context("Z", ret_20d=None, ret_60d=None)])

    assert with_gap["A"].score == pytest.approx(alone["A"].score)
    assert with_gap["A"].rank_percentile == pytest.approx(alone["A"].rank_percentile)
    assert with_gap["Z"].eligible is False
    assert with_gap["Z"].score is None


def test_a_symbol_missing_a_factor_scores_nothing() -> None:
    scored = _scored(
        [_full("A", 3.0, 3.0, 3.0), _context("B", ret_20d=1.0, ret_60d=1.0)]
    )

    assert scored["B"].eligible is False
    assert scored["B"].score is None
    assert scored["B"].rank_percentile is None


def test_rank_percentile_orders_the_scores() -> None:
    scored = _scored(_ranked())

    assert scored["A"].rank_percentile == pytest.approx(1.0)
    assert scored["B"].rank_percentile == pytest.approx(2 / 3)
    assert scored["C"].rank_percentile == pytest.approx(1 / 3)


def test_rank_percentile_is_absent_for_a_population_of_one() -> None:
    """There is no ranking to be had against a single symbol."""
    scored = _scored([_full("A", 3.0, 3.0, 3.0)])

    assert scored["A"].score == pytest.approx(100.0)
    assert scored["A"].rank_percentile is None


def test_results_come_back_in_the_order_they_were_given() -> None:
    contexts = _ranked()

    returned = _scanner().score_cross_section(contexts)

    assert [result.symbol for result in returned] == [
        context.symbol for context in contexts
    ]


def test_scoring_an_empty_population_is_not_an_error() -> None:
    assert _scanner().score_cross_section([]) == ()


# --- configuration guards ---------------------------------------------------


def test_a_configuration_without_weights_does_not_score() -> None:
    """No reviewed weights means no score, exactly as the previous slice ran."""
    scored = _scored(_ranked(), {})

    assert all(result.score is None for result in scored.values())
    assert all(result.rank_percentile is None for result in scored.values())


def test_confidence_stays_absent() -> None:
    """The design requires the field but defines no algorithm for it (D6)."""
    scored = _scored(_ranked())

    assert all(result.confidence is None for result in scored.values())


def test_weights_must_cover_the_required_factors() -> None:
    with pytest.raises(ValueError, match="weights"):
        _scanner({"ret_20d": 1.0})


def test_a_weight_for_an_unrequired_factor_is_rejected() -> None:
    with pytest.raises(ValueError, match="weights"):
        _scanner(
            {
                "ret_20d": 1.0,
                "ret_60d": 1.0,
                "proximity_52w_high": 1.0,
                "avg_amount_20d": 1.0,
            }
        )


def test_negative_weights_are_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        _scanner({"ret_20d": -1.0, "ret_60d": 1.0, "proximity_52w_high": 1.0})


def test_weights_summing_to_zero_are_rejected() -> None:
    with pytest.raises(ValueError, match="zero"):
        _scanner({"ret_20d": 0.0, "ret_60d": 0.0, "proximity_52w_high": 0.0})


# --- explanation -------------------------------------------------------------


def test_explain_names_the_score_when_there_is_one() -> None:
    top = _scored(_ranked())["A"]

    explanation = _scanner().explain(top)

    assert "100.0" in explanation.summary
    assert [note.factor for note in explanation.factors] == list(FACTORS)


def test_explain_on_an_unscored_result_says_so() -> None:
    unscored = _scored(_ranked(), {})["A"]

    explanation = _scanner().explain(unscored)

    assert "no score" in explanation.summary
