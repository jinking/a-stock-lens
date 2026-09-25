"""Eligibility-only scanner tests.

The rule these tests pin down: with weights deferred
(`docs/STRATEGY_SYSTEM.md` §5), a scanner may say whether a symbol's evidence
is complete enough to consider, and must not say anything else. No score, no
percentile, no confidence — each of those would be a number nobody reviewed,
and a number reads downstream as a judgement.
"""

from datetime import UTC, datetime

import pytest

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import StrategyContext
from astock_lens.strategies.eligibility import EligibilityScanner

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
SYMBOL = "600519.SH"

NON_VALUE_STATUSES = (
    DataStatus.NULL,
    DataStatus.STALE,
    DataStatus.INVALID,
    DataStatus.SOURCE_ERROR,
    DataStatus.NOT_APPLICABLE,
)


def _config(**overrides: object) -> StrategyConfig:
    payload: dict[str, object] = {
        "id": "quality",
        "version": "v1",
        "description": "quality",
        "required_factors": ["roe_ttm", "gross_margin"],
    }
    payload.update(overrides)
    return StrategyConfig.model_validate(payload)


def _factor(name: str, status: DataStatus, value: float | None = 1.0) -> FactorResult:
    return FactorResult(
        symbol=SYMBOL,
        factor=name,
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
        unit="%",
    )


def _context(*factors: FactorResult) -> StrategyContext:
    return StrategyContext(symbol=SYMBOL, as_of=AS_OF, factors=tuple(factors))


def test_a_symbol_with_every_required_factor_is_eligible() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE, 17.7),
        _factor("gross_margin", DataStatus.VALUE, 89.5),
    )

    verdict = scanner.eligibility(context)

    assert verdict.eligible is True
    assert verdict.reasons == ()
    assert scanner.required_factors() == {"roe_ttm", "gross_margin"}


def test_the_verdict_never_carries_a_score() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE),
        _factor("gross_margin", DataStatus.VALUE),
    )

    result = scanner.score(context)

    assert result.eligible is True
    assert result.score is None
    assert result.rank_percentile is None
    assert result.confidence is None
    assert result.factor_snapshot == context.factors
    assert result.lineage.strategy_version == "v1"


def test_a_missing_factor_makes_the_symbol_ineligible_and_says_which() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(_factor("roe_ttm", DataStatus.VALUE))

    result = scanner.score(context)

    assert result.eligible is False
    assert "gross_margin was not computed for this symbol" in result.risks


def test_any_status_other_than_value_is_not_eligible() -> None:
    """六个状态保持可区分；除 VALUE 外都不算证据。"""
    wrong = []
    for status in NON_VALUE_STATUSES:
        scanner = EligibilityScanner(_config())
        context = _context(
            _factor("roe_ttm", DataStatus.VALUE),
            _factor("gross_margin", status, value=None),
        )
        result = scanner.score(context)
        if (
            result.eligible is not False
            or f"gross_margin is {status}, not VALUE" not in result.risks
        ):
            wrong.append(
                f"{status}: eligible={result.eligible!r} risks={result.risks!r}"
            )
    assert not wrong, "非 VALUE 状态不应算证据:\n" + "\n".join(wrong)


def test_a_population_gets_one_verdict_each_and_no_ranking() -> None:
    scanner = EligibilityScanner(_config())
    contexts = (
        _context(
            _factor("roe_ttm", DataStatus.VALUE),
            _factor("gross_margin", DataStatus.VALUE),
        ),
        _context(_factor("roe_ttm", DataStatus.VALUE)),
    )

    results = scanner.score_cross_section(contexts)

    assert len(results) == 2
    assert [result.eligible for result in results] == [True, False]
    assert all(result.rank_percentile is None for result in results)


def test_the_explanation_states_that_scoring_is_deferred() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE),
        _factor("gross_margin", DataStatus.VALUE),
    )

    explanation = scanner.explain(scanner.score(context))

    assert "no score" in explanation.summary
    assert "not been reviewed" in explanation.summary
    assert {item.factor for item in explanation.factors} == {"roe_ttm", "gross_margin"}


def test_a_scanner_must_declare_what_it_requires() -> None:
    with pytest.raises(ValueError, match="must declare required_factors"):
        EligibilityScanner(_config(required_factors=[]))


def test_a_configured_scanner_with_weights_is_refused_here() -> None:
    """Weights mean a scoring implementation belongs, not this one."""
    with pytest.raises(ValueError, match="does not score"):
        EligibilityScanner(
            _config(required_factors=["roe_ttm"], weights={"roe_ttm": 1.0})
        )


def test_the_result_carries_the_configured_identity() -> None:
    """A verdict must name the scanner and version that produced it."""
    scanner = EligibilityScanner(_config(id="growth", version="v2"))
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE),
        _factor("gross_margin", DataStatus.VALUE),
    )

    result = scanner.score(context)

    assert result.strategy_id == "growth"
    assert result.strategy_version == "v2"
    assert result.as_of == AS_OF
    assert result.symbol == SYMBOL
