"""Universe construction.

The builder applies configured rules and reports every one of them. It never
repairs data, never substitutes a value it could not measure, and never drops a
rule quietly: a rule whose threshold is `null` is reported in
`UniverseSnapshot.deferred_rules` so a reader can distinguish "this symbol
failed the rule" from "this rule never ran".

Liquidity comes from a `FactorResult`, not from a computation performed here.
The 20-day average turnover is a factor; recomputing it inside the Universe
would create a second definition of the same quantity.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DailyBar, SecurityProfile, SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.universe.config import UniverseConfig
from astock_lens.universe.models import (
    DeferredRule,
    UniverseExclusion,
    UniverseRule,
    UniverseSnapshot,
)

LIQUIDITY_FACTOR = "avg_amount_20d"


class UniverseBuilder:
    """Turn security profiles and a liquidity measure into a universe snapshot."""

    def __init__(self, config: UniverseConfig) -> None:
        self._config = config

    def build(
        self,
        profiles: Sequence[SecurityProfile],
        *,
        as_of: datetime,
        bars: Sequence[DailyBar],
        liquidity: Mapping[str, FactorResult],
    ) -> UniverseSnapshot:
        """Apply every rule to every profile and record the verdicts."""
        _require_timezone(as_of)
        digest = self._config.digest()
        snapshot_id = f"{as_of.date().isoformat()}:{digest[:12]}"

        # Presence is judged on the as-of date itself. A bar dated later does
        # not tell us anything about whether a symbol traded on this day.
        traded = {bar.symbol for bar in bars if bar.trade_date == as_of.date()}

        included: list[str] = []
        exclusions: list[UniverseExclusion] = []

        for profile in sorted(profiles, key=lambda item: item.symbol):
            found = self._evaluate(
                profile, as_of=as_of, traded=traded, liquidity=liquidity
            )
            if found:
                exclusions.extend(found)
            else:
                included.append(profile.symbol)

        return UniverseSnapshot(
            as_of=as_of,
            snapshot_id=snapshot_id,
            config_digest=digest,
            lineage=SnapshotLineage(universe_snapshot=snapshot_id),
            included=tuple(included),
            exclusions=tuple(exclusions),
            deferred_rules=self._deferred_rules(),
        )

    def _evaluate(
        self,
        profile: SecurityProfile,
        *,
        as_of: datetime,
        traded: set[str],
        liquidity: Mapping[str, FactorResult],
    ) -> list[UniverseExclusion]:
        """Return every rule this profile failed, in declaration order."""
        config = self._config
        symbol = profile.symbol
        found: list[UniverseExclusion] = []

        if profile.exchange not in config.exchanges:
            found.append(
                _exclusion(
                    symbol,
                    UniverseRule.EXCHANGE,
                    f"exchange {profile.exchange!r} is not in {list(config.exchanges)}",
                )
            )

        if config.exclude_st and profile.is_st:
            found.append(_exclusion(symbol, UniverseRule.ST, "flagged ST"))

        if config.exclude_delisting_board and profile.is_delisting_board:
            found.append(
                _exclusion(
                    symbol, UniverseRule.DELISTING_BOARD, "on the delisting board"
                )
            )

        if (
            config.exclude_long_suspension
            and config.long_suspension_days is not None
            and profile.suspended_trading_days >= config.long_suspension_days
        ):
            found.append(
                _exclusion(
                    symbol,
                    UniverseRule.LONG_SUSPENSION,
                    f"suspended {profile.suspended_trading_days} days, "
                    f"threshold is {config.long_suspension_days}",
                )
            )

        listing_age = (as_of.date() - profile.list_date).days
        if listing_age < config.min_listing_days:
            found.append(
                _exclusion(
                    symbol,
                    UniverseRule.SHORT_LISTING,
                    f"listed {listing_age} days ago, minimum is "
                    f"{config.min_listing_days}",
                )
            )

        if config.require_valid_market_data and symbol not in traded:
            found.append(
                _exclusion(
                    symbol,
                    UniverseRule.NO_MARKET_DATA,
                    f"no daily bar dated {as_of.date().isoformat()}",
                )
            )

        measure = liquidity.get(symbol)
        value: float | None = measure.raw_value if measure is not None else None
        measured = (
            measure is not None
            and measure.status is DataStatus.VALUE
            and value is not None
        )

        if measured and value is not None:
            if value < config.min_average_turnover_20d:
                found.append(
                    _exclusion(
                        symbol,
                        UniverseRule.LOW_LIQUIDITY,
                        f"20-day average turnover {value} is below the floor "
                        f"{config.min_average_turnover_20d}",
                    )
                )
        elif config.require_valid_market_data:
            found.append(
                _exclusion(
                    symbol,
                    UniverseRule.NO_LIQUIDITY_MEASURE,
                    f"no VALUE result for {LIQUIDITY_FACTOR}",
                )
            )

        return found

    def _deferred_rules(self) -> tuple[DeferredRule, ...]:
        """Report rules that are switched on but cannot be evaluated."""
        config = self._config
        if config.exclude_long_suspension and config.long_suspension_days is None:
            return (
                DeferredRule(
                    rule=UniverseRule.LONG_SUSPENSION,
                    reason=(
                        "exclude_long_suspension is true but long_suspension_days "
                        "is null: no day count has been reviewed, so no symbol is "
                        "excluded on this rule"
                    ),
                ),
            )
        return ()


def _exclusion(symbol: str, rule: UniverseRule, detail: str) -> UniverseExclusion:
    return UniverseExclusion(symbol=symbol, rule=rule, detail=detail)


def _require_timezone(as_of: datetime) -> None:
    """Reject a naive `as_of` rather than guessing what it meant."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError(
            "as_of must be timezone-aware so a universe snapshot cannot be "
            "ambiguous about which instant it describes"
        )
