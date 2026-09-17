"""Factors implemented in this repository.

Every parameter comes from a `FactorConfig`. This module holds no window, no
threshold, and no default of its own — a factor that invented one would be
making a product decision the design has not approved.

A factor reports an objective quantity and stops there. Whether more of it is
better belongs to the strategy layer, which is why each one's `direction` is a
description rather than a preference.
"""

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DailyBar, SnapshotLineage
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import (
    Factor,
    FactorContext,
    FactorMetadata,
    FactorResult,
)
from astock_lens.factors.fundamental import (
    METRIC_DEFINITIONS,
    RATIO_DEFINITIONS,
    FundamentalRatioFactor,
    MetricPassthroughFactor,
)
from astock_lens.factors.valuation import VALUATION_FACTORS, ValuationFactor

AVERAGE_AMOUNT_FACTOR_NAME = "avg_amount_20d"
PROXIMITY_HIGH_FACTOR_NAME = "proximity_52w_high"

# `ret_20d` and `ret_60d` are one algorithm at two configured horizons, so the
# class accepts any factor whose name carries this prefix. The prefix is the
# contract; the window is configuration.
RETURN_FACTOR_PREFIX = "ret_"


class AverageAmountFactor:
    """Trailing average of daily turnover amount over a configured window.

    The value is objective: it reports how much was traded. Whether more
    liquidity is good belongs to the strategy layer, which is why `direction`
    is a description ("HIGHER_MEANS_MORE_LIQUID") rather than a preference.

    The input dataset is expected to have passed the Data Quality Gate. That
    boundary is stated rather than re-checked: duplicating the gate here would
    mean two places deciding what "invalid" means.
    """

    def __init__(self, factor_config: FactorConfig) -> None:
        if factor_config.name != AVERAGE_AMOUNT_FACTOR_NAME:
            raise ValueError(
                f"AverageAmountFactor requires the {AVERAGE_AMOUNT_FACTOR_NAME!r} "
                f"configuration, got {factor_config.name!r}"
            )
        self._window = _configured_window(factor_config)
        self.metadata = _metadata(factor_config)

    def compute(self, context: FactorContext) -> FactorResult:
        """Average the trailing window, or report `NULL` if it is incomplete."""
        window = _trailing(context, self._window)
        if window is None:
            return _null_result(context, self.metadata)

        amounts = [bar.amount for bar in window]
        if any(amount is None for amount in amounts):
            return _null_result(context, self.metadata)

        present = [amount for amount in amounts if amount is not None]
        return _value_result(context, self.metadata, sum(present) / self._window)


class TrailingReturnFactor:
    """Price return across the ends of a trailing window.

    A 20-day return spans 21 closes: the latest against the one 20 trading days
    back. The window is never shortened to fit a shorter history, and a missing
    close anywhere inside it yields `NULL` rather than a ratio computed across
    a hole.
    """

    def __init__(self, factor_config: FactorConfig) -> None:
        if not factor_config.name.startswith(RETURN_FACTOR_PREFIX):
            raise ValueError(
                f"TrailingReturnFactor requires a {RETURN_FACTOR_PREFIX}* "
                f"configuration, got {factor_config.name!r}"
            )
        self._window = _configured_window(factor_config)
        self.metadata = _metadata(factor_config)

    def compute(self, context: FactorContext) -> FactorResult:
        """Compare the window ends, or report `NULL` if either is unusable."""
        # One extra bar: the window spans `window` intervals, so it needs
        # `window + 1` observations to have a starting point.
        window = _trailing(context, self._window + 1)
        if window is None:
            return _null_result(context, self.metadata)

        closes = [bar.close for bar in window]
        if any(close is None for close in closes):
            return _null_result(context, self.metadata)

        start = window[0].close
        end = window[-1].close
        if start is None or end is None or start == 0:
            return _null_result(context, self.metadata)

        return _value_result(context, self.metadata, end / start - 1)


class ProximityToHighFactor:
    """Latest close as a fraction of the trailing window's highest high.

    Expressed as a ratio so that higher always means stronger: 1.0 is a symbol
    at its own peak, and 0.8 is one a fifth below it. A peak of zero is
    reported as `NULL` rather than as an infinite ratio.
    """

    def __init__(self, factor_config: FactorConfig) -> None:
        if factor_config.name != PROXIMITY_HIGH_FACTOR_NAME:
            raise ValueError(
                f"ProximityToHighFactor requires the {PROXIMITY_HIGH_FACTOR_NAME!r} "
                f"configuration, got {factor_config.name!r}"
            )
        self._window = _configured_window(factor_config)
        self.metadata = _metadata(factor_config)

    def compute(self, context: FactorContext) -> FactorResult:
        """Divide the latest close by the window peak, or report `NULL`."""
        window = _trailing(context, self._window)
        if window is None:
            return _null_result(context, self.metadata)

        highs = [bar.high for bar in window]
        close = window[-1].close
        if any(high is None for high in highs) or close is None:
            return _null_result(context, self.metadata)

        peak = max(high for high in highs if high is not None)
        if peak <= 0:
            return _null_result(context, self.metadata)

        return _value_result(context, self.metadata, close / peak)


def _configured_window(factor_config: FactorConfig) -> int:
    """Read the window from configuration. There is no default."""
    window = factor_config.params.get("window")
    if window is None:
        raise ValueError(
            f"factor configuration for {factor_config.name!r} must declare "
            "params.window; no default window is assumed"
        )
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")
    return window


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


def _trailing(context: FactorContext, size: int) -> tuple[DailyBar, ...] | None:
    """Return the newest `size` bars at or before `as_of`, or `None`.

    `None` means the history is shorter than the window. Shortening the window
    to fit would silently compare different quantities across symbols.
    """
    usable = sorted(
        (
            bar
            for bar in context.dataset.daily_bars
            if bar.symbol == context.symbol and bar.trade_date <= context.as_of.date()
        ),
        key=lambda bar: bar.trade_date,
    )
    if len(usable) < size:
        return None
    return tuple(usable[-size:])


def _lineage(metadata: FactorMetadata) -> SnapshotLineage:
    return SnapshotLineage(factor_version=metadata.version)


def _null_result(context: FactorContext, metadata: FactorMetadata) -> FactorResult:
    """A `NULL` states that no value exists; it never stands in a zero."""
    return FactorResult(
        symbol=context.symbol,
        factor=metadata.name,
        as_of=context.as_of,
        status=DataStatus.NULL,
        factor_version=metadata.version,
        lineage=_lineage(metadata),
    )


def _value_result(
    context: FactorContext, metadata: FactorMetadata, value: float
) -> FactorResult:
    return FactorResult(
        symbol=context.symbol,
        factor=metadata.name,
        as_of=context.as_of,
        status=DataStatus.VALUE,
        factor_version=metadata.version,
        lineage=_lineage(metadata),
        raw_value=value,
    )


def build_factor(factor_config: FactorConfig) -> Factor:
    """Return the implementation a configuration names.

    An unknown name raises rather than being skipped. A strategy that requires
    a factor nobody implemented would otherwise find every symbol ineligible,
    which reads downstream like a market verdict instead of a missing build.
    """
    if factor_config.name == AVERAGE_AMOUNT_FACTOR_NAME:
        return AverageAmountFactor(factor_config)
    if factor_config.name.startswith(RETURN_FACTOR_PREFIX):
        return TrailingReturnFactor(factor_config)
    if factor_config.name == PROXIMITY_HIGH_FACTOR_NAME:
        return ProximityToHighFactor(factor_config)
    if factor_config.name in RATIO_DEFINITIONS:
        return FundamentalRatioFactor(factor_config)
    if factor_config.name in METRIC_DEFINITIONS:
        return MetricPassthroughFactor(factor_config)
    if factor_config.name in VALUATION_FACTORS:
        return ValuationFactor(factor_config)
    raise ValueError(
        f"no factor implementation is registered for {factor_config.name!r}"
    )
