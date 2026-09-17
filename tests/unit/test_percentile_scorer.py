"""共享评分组件的约定。

把一份已评审的权重集合变成分数，所以这些测试钉住的是"评审者批准数字时同意的
那套规矩"：

- 权重的符号表达极性，所以"越小越好"的因子（`debt_to_asset`）排名前先反向；
- 只有合格的标的进入横截面，缺证据的标的不挪动别人的百分位；
- 权重必须恰好覆盖必需要求的因子，0 权重被拒绝而不是被静默忽略；
- `confidence` 保持缺席，因为设计没有为它定义算法。

以及一条边界：这个组件**不知道**任何策略的资格规则。调用方注入自己的判定，
组件只负责排名——否则"资格规则"就会重新变成配置推断出来的东西。
"""

from datetime import UTC, datetime

import pytest

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import EligibilityResult, StrategyContext
from astock_lens.strategies.percentile_scorer import (
    WeightedPercentileScorer,
    explain_result,
    validated_weights,
)

AS_OF = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)
WEIGHTS = {"roe_ttm": 1.0, "debt_to_asset": -1.0}


def _config(**overrides: object) -> StrategyConfig:
    payload: dict[str, object] = {
        "id": "quality",
        "version": "v1",
        "description": "quality",
        "required_factors": ["roe_ttm", "debt_to_asset"],
        "weights": dict(WEIGHTS),
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


def _score(contexts: tuple[StrategyContext, ...], **overrides: object):
    scorer = WeightedPercentileScorer()
    return scorer.score_cross_section(
        strategy_id="quality",
        strategy_version="v1",
        contexts=contexts,
        weights=overrides.pop("weights", WEIGHTS),
        **overrides,
    )


def _by_symbol(results: tuple[object, ...]) -> dict[str, object]:
    return {result.symbol: result for result in results}  # type: ignore[attr-defined]


def test_a_negative_weight_orients_a_factor_where_lower_is_better() -> None:
    """High ROE and low leverage must both raise the score."""
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("MIDDLE", roe=15.0, debt=30.0),
        _context("BAD", roe=5.0, debt=90.0),
    )

    results = _by_symbol(_score(contexts))

    assert results["GOOD"].score > results["MIDDLE"].score > results["BAD"].score
    assert results["GOOD"].rank_percentile == 1.0
    assert results["BAD"].rank_percentile == pytest.approx(1 / 3)


def test_the_orientation_is_visible_in_the_contribution() -> None:
    """A reader must be able to see that leverage was inverted, not added."""
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("BAD", roe=5.0, debt=90.0),
    )

    result = _by_symbol(_score(contexts))["GOOD"]
    contributions = {item.factor: item for item in result.contributions}

    assert contributions["roe_ttm"].percentile == 1.0
    assert contributions["debt_to_asset"].percentile == 1.0  # inverted: 10 < 90
    assert contributions["debt_to_asset"].weight == -1.0


def test_an_ineligible_symbol_shifts_nobody_else() -> None:
    """A missing factor must not move the population's percentiles."""
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("BAD", roe=5.0, debt=90.0),
        _context("UNKNOWN", roe=None, debt=50.0),
    )

    results = _by_symbol(_score(contexts))

    assert results["GOOD"].score == 100.0
    assert results["GOOD"].rank_percentile == 1.0
    assert results["UNKNOWN"].eligible is False
    assert results["UNKNOWN"].score is None
    assert "roe_ttm is NULL, not VALUE" in results["UNKNOWN"].risks


def test_a_single_symbol_population_gets_a_score_but_no_rank() -> None:
    """A percentile against nobody is not a percentile."""
    result = _score((_context("ONLY", 20.0, 10.0),))[0]

    assert result.score == 100.0
    assert result.rank_percentile is None


def test_no_contexts_means_no_results() -> None:
    assert _score(()) == ()


def test_the_caller_supplies_the_eligibility_rule() -> None:
    """资格规则由调用方注入，组件不自带某个策略的规则。"""
    seen: list[str] = []

    def nobody_is_eligible(context: StrategyContext) -> EligibilityResult:
        seen.append(context.symbol)
        return EligibilityResult(eligible=False, reasons=("policy",))

    results = _score(
        (
            _context("GOOD", roe=20.0, debt=10.0),
            _context("ALSO_FINE", roe=12.0, debt=20.0),
        ),
        eligibility=nobody_is_eligible,
    )

    # 注入的规则说了算：两个标的的因子都齐备，但判定它们不合格的是调用方，
    # 不是组件里写死的默认规则。
    assert seen == ["GOOD", "ALSO_FINE"]
    assert all(result.eligible is False for result in results)
    assert all(result.score is None for result in results)


def test_the_explanation_shows_each_factor_and_its_weight() -> None:
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("BAD", roe=5.0, debt=90.0),
    )
    result = _score(contexts)[0]

    explanation = explain_result(result)

    assert "score" in explanation.summary
    assert {item.factor for item in explanation.factors} == {
        "roe_ttm",
        "debt_to_asset",
    }
    assert any("weight -1.0" in item.note for item in explanation.factors)


def test_weights_must_cover_the_required_factors_exactly() -> None:
    with pytest.raises(ValueError, match="must cover required_factors exactly"):
        validated_weights(_config(weights={"roe_ttm": 1.0}))


def test_a_zero_weight_is_refused() -> None:
    """A factor with no weight does not belong in the strategy's requirements."""
    with pytest.raises(ValueError, match="does not belong"):
        validated_weights(_config(weights={"roe_ttm": 1.0, "debt_to_asset": 0.0}))


def test_a_strategy_without_weights_has_nothing_to_score() -> None:
    with pytest.raises(ValueError, match="declares no weights"):
        validated_weights(_config(weights={}))
