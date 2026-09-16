"""Factors implemented in this repository.

Every parameter comes from a `FactorConfig`. This module holds no window, no
threshold, and no default of its own — a factor that invented one would be
making a product decision the design has not approved.
"""

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import (
    FactorContext,
    FactorMetadata,
    FactorResult,
)

FACTOR_NAME = "avg_amount_20d"


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
        if factor_config.name != FACTOR_NAME:
            raise ValueError(
                f"AverageAmountFactor requires the {FACTOR_NAME!r} configuration, "
                f"got {factor_config.name!r}"
            )
        window = factor_config.params.get("window")
        if window is None:
            raise ValueError(
                "factor configuration must declare params.window; no default "
                "window is assumed"
            )
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")

        self._window = window
        self.metadata = FactorMetadata(
            name=factor_config.name,
            domain=factor_config.domain,
            description=factor_config.description,
            inputs=factor_config.inputs,
            frequency=factor_config.frequency,
            direction=factor_config.direction,
            null_policy=factor_config.null_policy,
            version=factor_config.version,
        )

    def compute(self, context: FactorContext) -> FactorResult:
        """Average the trailing window, or report `NULL` if it is incomplete."""
        usable = sorted(
            (
                bar
                for bar in context.dataset.daily_bars
                if bar.symbol == context.symbol
                and bar.trade_date <= context.as_of.date()
            ),
            key=lambda bar: bar.trade_date,
        )
        window = usable[-self._window :]

        if len(window) < self._window:
            return self._null_result(context)

        amounts = [bar.amount for bar in window]
        if any(amount is None for amount in amounts):
            return self._null_result(context)

        present = [amount for amount in amounts if amount is not None]
        return FactorResult(
            symbol=context.symbol,
            factor=self.metadata.name,
            as_of=context.as_of,
            status=DataStatus.VALUE,
            factor_version=self.metadata.version,
            lineage=self._lineage(),
            raw_value=sum(present) / self._window,
        )

    def _null_result(self, context: FactorContext) -> FactorResult:
        """A `NULL` states that no value exists; it never stands in a zero."""
        return FactorResult(
            symbol=context.symbol,
            factor=self.metadata.name,
            as_of=context.as_of,
            status=DataStatus.NULL,
            factor_version=self.metadata.version,
            lineage=self._lineage(),
        )

    def _lineage(self) -> SnapshotLineage:
        return SnapshotLineage(factor_version=self.metadata.version)
