"""按已评审权重的百分位评分组件。

`docs/STRATEGY_SYSTEM.md` §5 把每个 Scanner 的权重与阈值列为 `Deferred`；本模块
是那件事之后的机器：把一份**已评审**的权重集合变成分数，于是"批准一组权重"是
配置动作，不是编码任务。

## 它不是 Strategy 类型

这个组件不认识 growth / quality / dividend / value / garp。它只认识"一组上下文
+ 一份权重"，因此它不能被当成"策略实现"来用：谁有资格进入这个横截面，由每个
Scanner 自己的 `eligibility` 决定，组件通过 `eligibility` 参数接收那个判定。
默认规则只是最朴素的一条（要求的因子都在场），它不是任何策略的专属规则。

## 权重怎么读

`weights` 必须恰好覆盖 `required_factors`，权重的**符号**表达极性：

- **正** —— 值越大越好（ROE、毛利率、增长）；
- **负** —— 先把因子反向，再排名（资产负债率、商誉占权益）。

把极性写成一个数的符号，而不是发明第二套词表，是为了让"这个权重到底什么意思"
一眼可见：一个幅度对评审者无意义的权重，就是没人认真想过的权重。

混合公式是 `Σ(|w| · 有向百分位) / Σ|w|`，缩放到 0–100。百分位只在**有资格的
总体**内计算，所以缺证据的标的不会挪动别人的名次。`confidence` 保持 `None`：
设计要求这个字段但没定义算法，而资格判定已经要求因子全在场，"覆盖率"会是一个
恒定值的伪装测量。
"""

from collections.abc import Callable, Mapping, Sequence

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import (
    EligibilityResult,
    Explanation,
    FactorContribution,
    FactorExplanation,
    StrategyContext,
    StrategyResult,
)
from astock_lens.strategies.scoring import percentile_ranks

SCORE_CEILING = 100.0

EligibilityRule = Callable[[StrategyContext], EligibilityResult]


class WeightedPercentileScorer:
    """把一组上下文与一份权重合成为横截面分数。"""

    def score_cross_section(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        contexts: Sequence[StrategyContext],
        weights: Mapping[str, float],
        eligibility: EligibilityRule | None = None,
    ) -> tuple[StrategyResult, ...]:
        """Rank a population, orienting each factor by its weight's sign.

        `eligibility` 由调用方的 Scanner 注入：这个组件不该知道某个策略的资格
        规则是什么，只知道拿到资格的那些上下文要一起排名。
        """
        if not contexts:
            return ()

        verdict_of = eligibility or (
            lambda context: required_values_are_present(context, weights)
        )
        verdicts = [verdict_of(context) for context in contexts]
        population = [
            context
            for context, verdict in zip(contexts, verdicts, strict=True)
            if verdict.eligible
        ]

        oriented = {
            name: percentile_ranks(
                {
                    context.symbol: _oriented_value(context, name, weights[name])
                    for context in population
                }
            )
            for name in weights
        }
        total_weight = sum(abs(weight) for weight in weights.values())
        blends = {
            context.symbol: sum(
                abs(weights[name]) * oriented[name][context.symbol] for name in weights
            )
            / total_weight
            for context in population
        }
        ranks = percentile_ranks(blends) if len(blends) > 1 else {}

        results: list[StrategyResult] = []
        for context, verdict in zip(contexts, verdicts, strict=True):
            if verdict.eligible:
                results.append(
                    evidence_result(
                        context=context,
                        verdict=verdict,
                        strategy_id=strategy_id,
                        strategy_version=strategy_version,
                        score=SCORE_CEILING * blends[context.symbol],
                        rank_percentile=ranks.get(context.symbol),
                        contributions=_contributions(
                            context, oriented, weights, total_weight
                        ),
                    )
                )
            else:
                results.append(
                    evidence_result(
                        context=context,
                        verdict=verdict,
                        strategy_id=strategy_id,
                        strategy_version=strategy_version,
                    )
                )
        return tuple(results)


def required_values_are_present(
    context: StrategyContext, weights: Mapping[str, float]
) -> EligibilityResult:
    """默认资格规则：每个要求的因子都必须真的带值。

    这是最朴素的规则，也是目前六个策略共用的一条。它只作为默认值存在：一个
    策略有了自己的资格语义（增长要两端同时成立、分红要看现金流覆盖）时，替换
    自己 Scanner 里的 `eligibility` 即可，不需要动这个组件。
    """
    observed = {result.factor: result for result in context.factors}
    reasons: list[str] = []

    for name in weights:
        result = observed.get(name)
        if result is None:
            reasons.append(f"{name} was not computed for this symbol")
        elif result.status is not DataStatus.VALUE:
            reasons.append(f"{name} is {result.status}, not VALUE")

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))


def evidence_result(
    *,
    context: StrategyContext,
    verdict: EligibilityResult,
    strategy_id: str,
    strategy_version: str,
    score: float | None = None,
    rank_percentile: float | None = None,
    contributions: tuple[FactorContribution, ...] = (),
) -> StrategyResult:
    """把一次判定组装成 `StrategyResult`，证据与理由一起带上。"""
    return StrategyResult(
        symbol=context.symbol,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        as_of=context.as_of,
        eligible=verdict.eligible,
        lineage=SnapshotLineage(strategy_version=strategy_version),
        score=score,
        rank_percentile=rank_percentile,
        confidence=None,
        reasons=tuple(
            f"{result.factor}={result.raw_value}"
            if result.raw_value is not None
            else f"{result.factor} is {result.status}"
            for result in context.factors
        ),
        risks=verdict.reasons,
        factor_snapshot=context.factors,
        contributions=contributions,
    )


def explain_result(result: StrategyResult) -> Explanation:
    """Make a score expandable to factor level."""
    verdict = "eligible" if result.eligible else "not eligible"
    outcome = (
        f"score {result.score:.2f}"
        if result.score is not None
        else "no score (needs a cross-section)"
    )
    return Explanation(
        symbol=result.symbol,
        strategy_id=result.strategy_id,
        as_of=result.as_of,
        summary=f"{result.strategy_id} {result.strategy_version}: {verdict}; {outcome}",
        factors=_notes(result),
    )


def validated_weights(config: StrategyConfig) -> dict[str, float]:
    """Check that the reviewed weights describe exactly the required factors."""
    weights = dict(config.weights)
    if not weights:
        raise ValueError(
            f"strategy {config.id!r} declares no weights, so there is nothing to "
            "score; a strategy without reviewed weights has no implementation to "
            "build a score from"
        )

    declared = set(config.required_factors)
    configured = set(weights)
    if declared != configured:
        raise ValueError(
            "weights must cover required_factors exactly: "
            f"missing={sorted(declared - configured)}, "
            f"unexpected={sorted(configured - declared)}"
        )

    zero = sorted(name for name, value in weights.items() if value == 0)
    if zero:
        raise ValueError(
            f"a zero weight means the factor does not belong to the strategy: {zero}"
        )
    return weights


def _contributions(
    context: StrategyContext,
    oriented: Mapping[str, Mapping[str, float]],
    weights: Mapping[str, float],
    total_weight: float,
) -> tuple[FactorContribution, ...]:
    """Record each factor's oriented share, in configuration order."""
    return tuple(
        FactorContribution(
            factor=name,
            percentile=oriented[name][context.symbol],
            weight=weights[name],
            weighted=abs(weights[name]) * oriented[name][context.symbol] / total_weight,
        )
        for name in weights
    )


def _oriented_value(context: StrategyContext, name: str, weight: float) -> float:
    """Return a factor's value, negated when a lower value ranks better."""
    value = _value_of(context, name)
    return value if weight > 0 else -value


def _value_of(context: StrategyContext, name: str) -> float:
    """Return a required factor's value, which eligibility has already checked."""
    for result in context.factors:
        if result.factor == name and result.raw_value is not None:
            return result.raw_value
    raise ValueError(
        f"{name} has no value for {context.symbol}; eligibility should have "
        "kept this context out of the population"
    )


def _notes(result: StrategyResult) -> tuple[FactorExplanation, ...]:
    """One line per factor, showing its oriented percentile and weight."""
    contributions = {item.factor: item for item in result.contributions}
    notes: list[FactorExplanation] = []
    for item in result.factor_snapshot:
        contribution = contributions.get(item.factor)
        if contribution is None:
            notes.append(
                FactorExplanation(
                    factor=item.factor,
                    note=(
                        f"{item.raw_value}"
                        if item.raw_value is not None
                        else f"no value ({item.status})"
                    ),
                )
            )
            continue
        notes.append(
            FactorExplanation(
                factor=item.factor,
                note=(
                    f"{item.raw_value} (oriented percentile "
                    f"{contribution.percentile:.3f}, weight {contribution.weight})"
                ),
            )
        )
    return tuple(notes)
