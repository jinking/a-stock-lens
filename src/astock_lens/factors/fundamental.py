"""Fundamental factors.

These factors read the canonical `FinancialObservation` records the data layer
produced, and they are the first ones whose value depends on *when* it is
asked: a fundamental factor must use the newest period already published at
`as_of`, and must never see a report the market had not received yet
(`spec §5.1`).

What this module does not do:

- it does not fetch, parse or repair anything — the normalized dataset is its
  only input (`ARCHITECTURE.md` §4.3);
- it does not invent an annualization. The source publishes TTM fields, so the
  ratios that need a trailing year use those instead of a sum this code
  assembled from quarters;
- it does not invent a threshold. Its only parameter is a freshness bound, and
  a configuration that has not decided one writes `null` for it.

Missing evidence is reported in the documented states, with one precedence
rule stated explicitly: `NOT_APPLICABLE` (this instrument's statements do not
carry the line) outranks `NULL` (the line exists without a value), which
outranks `STALE`. A factor that cannot be computed says which of those
happened rather than returning a number-shaped placeholder.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import FinancialObservation, SnapshotLineage
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import (
    FactorContext,
    FactorInputRef,
    FactorMetadata,
    FactorResult,
)


@dataclass(frozen=True)
class RatioSpec:
    """One fundamental factor: one canonical metric divided by another."""

    numerator: str
    denominator: str


@dataclass(frozen=True)
class MetricSpec:
    """One factor that surfaces a single canonical metric.

    The source already computes these figures (growth rates, margins,
    leverage) and the factor engine's contract is `FactorResult`, so a metric a
    strategy needs has to exist as a factor to reach it. Nothing is recomputed
    and no threshold is applied: the factor reports the metric, at the point in
    time it was published.
    """

    metric: str
    unit: str


# Code owns which metrics a factor combines; YAML owns its metadata and any
# threshold. That split is the deliberate choice `ARCHITECTURE.md` §8.3 makes —
# "algorithms are code, weights and thresholds are configuration" — and it is
# why no general YAML expression language exists here.
RATIO_DEFINITIONS: Mapping[str, RatioSpec] = {
    # Quality: how much of reported profit turned into operating cash.
    "ocf_to_net_profit": RatioSpec(
        numerator="net_operating_cashflow_ttm",
        denominator="net_profit_parent_ttm",
    ),
    # Leverage: debt that costs money, measured against owner capital.
    "interest_bearing_debt_to_equity": RatioSpec(
        numerator="interest_bearing_debt",
        denominator="total_equity",
    ),
    # Balance-sheet risk: how much of equity is goodwill, which funds nothing.
    "goodwill_to_equity": RatioSpec(
        numerator="goodwill",
        denominator="total_equity",
    ),
    # Dividend sustainability: the share of trailing profit paid out, which
    # matters more than the headline yield.
    "dividend_payout_ttm": RatioSpec(
        numerator="dividend_ttm",
        denominator="net_profit_parent_ttm",
    ),
    # Efficiency: trailing revenue against the inventory the company holds.
    "revenue_ttm_to_inventory": RatioSpec(
        numerator="revenue_ttm",
        denominator="inventories",
    ),
}

# Factors that surface one metric each, for the strategy dimensions the ratio
# factors above do not cover.
METRIC_DEFINITIONS: Mapping[str, MetricSpec] = {
    # Growth: how fast the business is actually expanding.
    "revenue_yoy": MetricSpec("revenue_yoy", "%"),
    "net_profit_parent_yoy": MetricSpec("net_profit_parent_yoy", "%"),
    "revenue_cagr_3y": MetricSpec("revenue_cagr_3y", "%"),
    "net_profit_parent_cagr_3y": MetricSpec("net_profit_parent_cagr_3y", "%"),
    # Quality: durable profitability and the balance sheet behind it.
    "roe_ttm": MetricSpec("roe_ttm", "%"),
    "gross_margin": MetricSpec("gross_margin", "%"),
    "debt_to_asset": MetricSpec("debt_to_asset", "%"),
}

# A ratio of two comparable quantities is dimensionless; the unit is recorded
# so a reader of a snapshot never has to guess.
RATIO_UNIT = "x"

# The freshness key a configuration must declare, even when it declares `null`.
STALE_AFTER_DAYS = "stale_after_days"


class FundamentalRatioFactor:
    """A ratio of two canonical financial metrics at one point in time."""

    def __init__(self, factor_config: FactorConfig) -> None:
        spec = RATIO_DEFINITIONS.get(factor_config.name)
        if spec is None:
            raise ValueError(
                f"{factor_config.name!r} is not a fundamental ratio factor; "
                f"implemented ratios are {sorted(RATIO_DEFINITIONS)}"
            )
        self._spec = spec
        self._stale_after_days = _configured_staleness(factor_config)
        _require_declared_inputs(factor_config, spec)
        self.metadata = _metadata(factor_config)

    def compute(self, context: FactorContext) -> FactorResult:
        """Divide the newest published numerator by the newest published divisor."""
        numerator = _latest(context, self._spec.numerator)
        denominator = _latest(context, self._spec.denominator)
        inputs = (numerator.ref, denominator.ref)

        reason = _blocking_status(
            numerator, denominator, self._stale_after_days, context
        )
        if reason is not None:
            return _result(
                context, self.metadata, status=reason, inputs=inputs, unit=RATIO_UNIT
            )

        dividend = _value_of(numerator)
        divisor = _value_of(denominator)
        if divisor == 0:
            # A zero divisor is a real value, not a missing one; the ratio
            # simply does not exist, and saying so is the honest answer.
            return _result(
                context,
                self.metadata,
                status=DataStatus.INVALID,
                inputs=inputs,
                unit=RATIO_UNIT,
            )

        return _result(
            context,
            self.metadata,
            status=DataStatus.VALUE,
            inputs=inputs,
            unit=RATIO_UNIT,
            value=dividend / divisor,
        )


class MetricPassthroughFactor:
    """A factor that reports one canonical metric, at its point in time."""

    def __init__(self, factor_config: FactorConfig) -> None:
        spec = METRIC_DEFINITIONS.get(factor_config.name)
        if spec is None:
            raise ValueError(
                f"{factor_config.name!r} is not a passthrough metric factor; "
                f"implemented metrics are {sorted(METRIC_DEFINITIONS)}"
            )
        self._spec = spec
        self._stale_after_days = _configured_staleness(factor_config)
        _require_declared_metric(factor_config, spec)
        self.metadata = _metadata(factor_config)

    def compute(self, context: FactorContext) -> FactorResult:
        """Report the newest value of the metric that `as_of` could have seen."""
        item = _latest(context, self._spec.metric)
        inputs = (item.ref,)
        reason = _single_status(item, self._stale_after_days, context)
        if reason is not None:
            return _result(
                context,
                self.metadata,
                status=reason,
                inputs=inputs,
                unit=self._spec.unit,
            )

        return _result(
            context,
            self.metadata,
            status=DataStatus.VALUE,
            inputs=inputs,
            unit=self._spec.unit,
            value=_value_of(item),
        )


@dataclass(frozen=True)
class _Input:
    """What the observations say about one required metric."""

    metric: str
    observation: FinancialObservation | None
    reported_at_all: bool

    @property
    def ref(self) -> FactorInputRef:
        if self.observation is None:
            return FactorInputRef(metric=self.metric)
        return FactorInputRef(
            metric=self.metric,
            report_period=self.observation.report_period,
            announce_date=self.observation.announce_date,
            value=self.observation.value,
        )


def _latest(context: FactorContext, metric: str) -> _Input:
    """The newest observation of `metric` that was published by `as_of`."""
    mine = [
        item
        for item in context.dataset.observations
        if item.symbol == context.symbol and item.metric == metric
    ]
    available = [item for item in mine if item.available_at <= context.as_of]
    if not available:
        # `reported_at_all` separates "this instrument never reports the line"
        # from "it reports it, just not yet at this point of view".
        return _Input(metric=metric, observation=None, reported_at_all=bool(mine))

    newest = max(available, key=lambda item: (item.report_period, item.available_at))
    return _Input(metric=metric, observation=newest, reported_at_all=True)


def _blocking_status(
    numerator: _Input,
    denominator: _Input,
    stale_after_days: int | None,
    context: FactorContext,
) -> DataStatus | None:
    """Return the state that prevents a value, or `None` when one exists.

    Precedence, from most to least specific: not applicable (the statement has
    no such line at all), null (the line exists without a value), stale (the
    value is older than the reviewed freshness bound).
    """
    for item in (numerator, denominator):
        if item.observation is None:
            return (
                DataStatus.NULL if item.reported_at_all else DataStatus.NOT_APPLICABLE
            )

    for item in (numerator, denominator):
        assert item.observation is not None
        if item.observation.value is None:
            return DataStatus.NULL

    if stale_after_days is not None:
        for item in (numerator, denominator):
            assert item.observation is not None
            announced = item.observation.announce_date
            if announced is None:
                return DataStatus.NULL
            if (context.as_of.date() - announced).days > stale_after_days:
                return DataStatus.STALE

    return None


def _single_status(
    item: _Input, stale_after_days: int | None, context: FactorContext
) -> DataStatus | None:
    """The same precedence, for a factor that needs only one metric."""
    return _blocking_status(item, item, stale_after_days, context)


def _value_of(item: _Input) -> float:
    """Read an input's value, which `_blocking_status` has already vetted."""
    assert item.observation is not None
    assert item.observation.value is not None
    return item.observation.value


def _configured_staleness(factor_config: FactorConfig) -> int | None:
    """Read the freshness bound, which the configuration must state.

    A missing key is an error, while `null` is a decision: it records that no
    freshness requirement has been reviewed, so the factor never reports
    `STALE`. Defaulting the key here would decide something nobody decided.
    """
    if STALE_AFTER_DAYS not in factor_config.params:
        raise ValueError(
            f"factor configuration for {factor_config.name!r} must declare "
            f"params.{STALE_AFTER_DAYS}; write null to record that no freshness "
            "requirement has been reviewed"
        )

    configured = factor_config.params[STALE_AFTER_DAYS]
    if configured is None:
        return None
    if configured <= 0:
        raise ValueError(
            f"params.{STALE_AFTER_DAYS} must be positive when set, got {configured}"
        )
    return configured


def _require_declared_inputs(factor_config: FactorConfig, spec: RatioSpec) -> None:
    """Keep the configuration and the algorithm from drifting apart."""
    declared = set(factor_config.inputs)
    expected = {spec.numerator, spec.denominator}
    if declared != expected:
        raise ValueError(
            f"factor configuration for {factor_config.name!r} must declare "
            f"inputs {sorted(expected)}, got {sorted(declared)}"
        )


def _require_declared_metric(factor_config: FactorConfig, spec: MetricSpec) -> None:
    """Keep the configuration and the algorithm from drifting apart."""
    declared = set(factor_config.inputs)
    if declared != {spec.metric}:
        raise ValueError(
            f"factor configuration for {factor_config.name!r} must declare "
            f"inputs [{spec.metric!r}], got {sorted(declared)}"
        )


def _metadata(factor_config: FactorConfig) -> FactorMetadata:
    """Copy declared metadata; the factor invents none of it."""
    return FactorMetadata(
        name=factor_config.name,
        domain=factor_config.domain,
        description=factor_config.description,
        inputs=factor_config.inputs,
        frequency=factor_config.frequency,
        direction=factor_config.direction,
        null_policy=factor_config.null_policy,
        version=factor_config.version,
    )


def _result(
    context: FactorContext,
    metadata: FactorMetadata,
    *,
    status: DataStatus,
    inputs: Sequence[FactorInputRef],
    value: float | None = None,
    unit: str | None = None,
) -> FactorResult:
    """Build a result; a status that is not `VALUE` carries no number."""
    return FactorResult(
        symbol=context.symbol,
        factor=metadata.name,
        as_of=context.as_of,
        status=status,
        factor_version=metadata.version,
        lineage=SnapshotLineage(factor_version=metadata.version),
        raw_value=value if status is DataStatus.VALUE else None,
        inputs=tuple(inputs),
        unit=unit,
    )
