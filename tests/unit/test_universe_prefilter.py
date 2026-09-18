"""Listing-only prefilter.

The Research Universe is built in two steps: a cheap prefilter over listing
metadata, then the data-dependent Universe rules. This file pins the boundary
between them: the prefilter may judge only what the listing itself says
(exchange, ST, delisting board, listing age) and must stay silent about
everything that needs bars, liquidity or a strategy score.

The parity test is the anti-duplication guard. If the prefilter ever grows its
own copy of a rule, its verdicts stop matching the UniverseBuilder's and that
test fails.
"""

import inspect
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.domain.models import SecurityProfile
from astock_lens.universe.builder import UniverseBuilder
from astock_lens.universe.config import UniverseConfig, load_universe_config
from astock_lens.universe.models import UniverseRule
from astock_lens.universe.prefilter import PrefilterResult, prefilter_listing

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _config() -> UniverseConfig:
    return load_universe_config(ROOT / "configs" / "universe.yaml")


def _profiles() -> tuple[SecurityProfile, ...]:
    raw = LocalCsvProvider(CSV_ROOT).fetch(
        FetchRequest(dataset="securities", as_of=AS_OF)
    )
    return CsvSecurityNormalizer().normalize(raw, as_of=AS_OF).securities


def _profile(
    symbol: str,
    *,
    exchange: str = "SZSE",
    list_date: date = date(2015, 1, 5),
    is_st: bool = False,
    is_delisting_board: bool = False,
) -> SecurityProfile:
    return SecurityProfile(
        symbol=symbol,
        name=f"name-{symbol}",
        exchange=exchange,
        list_date=list_date,
        is_st=is_st,
        is_delisting_board=is_delisting_board,
    )


def test_a_mature_normal_listing_passes_the_prefilter() -> None:
    result = prefilter_listing((_profile("000001.SZ"),), config=_config(), as_of=AS_OF)

    assert isinstance(result, PrefilterResult)
    assert result.included == ("000001.SZ",)
    assert result.excluded == ()


def test_st_is_excluded_with_the_rule_that_caused_it() -> None:
    result = prefilter_listing(
        (_profile("000002.SZ", is_st=True),), config=_config(), as_of=AS_OF
    )

    assert result.included == ()
    assert [(e.symbol, e.rule, e.detail) for e in result.excluded] == [
        ("000002.SZ", UniverseRule.ST, "flagged ST")
    ]


def test_the_delisting_board_is_excluded() -> None:
    result = prefilter_listing(
        (_profile("000003.SZ", is_delisting_board=True),),
        config=_config(),
        as_of=AS_OF,
    )

    assert result.included == ()
    assert [e.rule for e in result.excluded] == [UniverseRule.DELISTING_BOARD]


def test_an_exchange_outside_the_configuration_is_excluded() -> None:
    result = prefilter_listing(
        (_profile("000004.SZ", exchange="HKEX"),), config=_config(), as_of=AS_OF
    )

    assert result.included == ()
    assert [e.rule for e in result.excluded] == [UniverseRule.EXCHANGE]
    assert "HKEX" in result.excluded[0].detail


def test_a_listing_younger_than_the_configured_age_is_excluded() -> None:
    young = _profile("000005.SZ", list_date=date(2026, 8, 1))

    result = prefilter_listing((young,), config=_config(), as_of=AS_OF)

    assert result.included == ()
    assert [e.rule for e in result.excluded] == [UniverseRule.SHORT_LISTING]
    assert "minimum is 120" in result.excluded[0].detail


def test_the_listing_age_boundary_is_inclusive() -> None:
    """Exactly `min_listing_days` of history passes; one day less does not."""
    config = _config()
    boundary = date(2026, 9, 4).toordinal() - config.min_listing_days

    passed = prefilter_listing(
        (_profile("000006.SZ", list_date=date.fromordinal(boundary)),),
        config=config,
        as_of=AS_OF,
    )
    failed = prefilter_listing(
        (_profile("000007.SZ", list_date=date.fromordinal(boundary + 1)),),
        config=config,
        as_of=AS_OF,
    )

    assert passed.included == ("000006.SZ",)
    assert failed.included == ()


def test_every_rule_a_symbol_breaks_is_reported_not_just_the_first() -> None:
    result = prefilter_listing(
        (
            _profile(
                "000008.SZ", exchange="HKEX", is_st=True, list_date=date(2026, 9, 1)
            ),
        ),
        config=_config(),
        as_of=AS_OF,
    )

    assert [e.rule for e in result.excluded] == [
        UniverseRule.EXCHANGE,
        UniverseRule.ST,
        UniverseRule.SHORT_LISTING,
    ]


def test_data_dependent_rules_are_not_the_prefilter_business() -> None:
    """A symbol with no bar and no liquidity measure still passes the prefilter.

    Those rules need data the listing does not carry; the UniverseBuilder applies
    them later. Judging them here would exclude a symbol before anything ever
    measured it.
    """
    profile = _profile("000009.SZ")

    result = prefilter_listing((profile,), config=_config(), as_of=AS_OF)
    builder_verdict = UniverseBuilder(_config()).build(
        (profile,), as_of=AS_OF, bars=(), liquidity={}
    )

    assert result.included == ("000009.SZ",)
    assert {e.rule for e in builder_verdict.exclusions} == {
        UniverseRule.NO_MARKET_DATA,
        UniverseRule.NO_LIQUIDITY_MEASURE,
    }


def test_the_prefilter_agrees_with_the_universe_builder_on_listing_rules() -> None:
    """Same profiles, same listing verdicts — the rules live in one place."""
    config = _config()
    profiles = _profiles()
    listing_rules = {
        UniverseRule.EXCHANGE,
        UniverseRule.ST,
        UniverseRule.DELISTING_BOARD,
        UniverseRule.SHORT_LISTING,
    }

    prefiltered = prefilter_listing(profiles, config=config, as_of=AS_OF)
    built = UniverseBuilder(config).build(profiles, as_of=AS_OF, bars=(), liquidity={})

    from_prefilter = {
        (e.symbol, e.rule, e.detail)
        for e in prefiltered.excluded
        if e.rule in listing_rules
    }
    from_builder = {
        (e.symbol, e.rule, e.detail)
        for e in built.exclusions
        if e.rule in listing_rules
    }

    assert from_prefilter == from_builder


def test_the_prefilter_takes_no_strategy_configuration() -> None:
    parameters = inspect.signature(prefilter_listing).parameters

    assert set(parameters) == {"securities", "config", "as_of"}
    with pytest.raises(TypeError):
        prefilter_listing(
            (_profile("000001.SZ"),),
            config=_config(),
            as_of=AS_OF,
            strategies=("momentum",),
        )
