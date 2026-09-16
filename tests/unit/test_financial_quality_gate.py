"""Financial quality gate tests.

The gate reports; it never repairs and never drops. These tests pin down the
difference between the three ways a measurement can be absent, because getting
that wrong is how a gap turns into a zero:

- the source has no value (`NULL`, not a defect);
- the source's text could not be read (`INVALID`, and the key is set aside);
- the same key appears twice (`INVALID`).

A statement that yielded nothing at all is P1, which is what makes the module
that needs fundamentals degrade loudly instead of scoring nothing.
"""

from datetime import UTC, date, datetime

from astock_lens.data.normalize.financials import FinancialNormalizeFailure
from astock_lens.data.quality.financial_gate import (
    FinancialQualityGate,
    usable_observations,
)
from astock_lens.domain.enums import DataStatus, ErrorSeverity
from astock_lens.domain.models import FinancialObservation

AS_OF = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)
REPORT_PERIOD = date(2026, 6, 30)
ANNOUNCE = date(2026, 8, 15)
AVAILABLE_AT = datetime(2026, 8, 15, 15, 0, tzinfo=UTC)


def _observation(
    *,
    symbol: str = "600519.SH",
    metric: str = "revenue",
    value: float | None = 1.0,
    report_period: date = REPORT_PERIOD,
) -> FinancialObservation:
    return FinancialObservation(
        symbol=symbol,
        metric=metric,
        report_period=report_period,
        announce_date=ANNOUNCE,
        available_at=AVAILABLE_AT,
        as_of=AS_OF,
        source="westock-cli",
        value=value,
        unit="CNY",
    )


def _gate() -> FinancialQualityGate:
    return FinancialQualityGate()


def test_a_clean_observation_produces_no_findings() -> None:
    observations = (_observation(),)

    report = _gate().check(observations, dataset="financial_income", as_of=AS_OF)

    assert report.checked == 1
    assert report.usable == 1
    assert report.issues == ()
    assert usable_observations(observations, report) == observations


def test_a_missing_value_is_null_not_a_defect() -> None:
    observations = (_observation(value=None),)

    report = _gate().check(observations, dataset="financial_income", as_of=AS_OF)

    assert [issue.rule for issue in report.issues] == ["value_missing"]
    assert report.issues[0].status is DataStatus.NULL
    assert report.issues[0].severity is ErrorSeverity.P2
    # A `NULL` stays usable on purpose: a factor has to be able to report it.
    assert report.usable == 1
    assert usable_observations(observations, report) == observations


def test_an_unreadable_cell_makes_the_key_invalid() -> None:
    observation = _observation(value=None)
    failures = (
        FinancialNormalizeFailure(
            column="OperatingRevenue",
            raw_value="oops",
            reason="'oops' is not a number",
            symbol=observation.symbol,
            metric=observation.metric,
            report_period=observation.report_period,
        ),
    )

    report = _gate().check(
        (observation,),
        dataset="financial_income",
        as_of=AS_OF,
        failures=failures,
    )

    assert [issue.rule for issue in report.issues] == ["value_not_numeric"]
    assert report.issues[0].status is DataStatus.INVALID
    assert report.usable == 0
    assert usable_observations((observation,), report) == ()


def test_a_duplicated_key_is_invalid_and_dropped_together() -> None:
    observations = (_observation(value=1.0), _observation(value=2.0))

    report = _gate().check(observations, dataset="financial_income", as_of=AS_OF)

    # Both copies are reported, the way the daily-bar gate reports both rows of
    # a duplicated (symbol, trade_date) key.
    assert {issue.rule for issue in report.issues} == {"duplicate_primary_key"}
    assert len(report.issues) == 2
    assert report.usable == 0
    # Both copies go: leaving an arbitrary survivor would pick a value nobody
    # chose between.
    assert usable_observations(observations, report) == ()


def test_different_periods_are_not_duplicates() -> None:
    observations = (
        _observation(report_period=date(2026, 6, 30)),
        _observation(report_period=date(2026, 3, 31)),
    )

    report = _gate().check(observations, dataset="financial_income", as_of=AS_OF)

    assert report.issues == ()
    assert report.usable == 2


def test_an_empty_statement_is_a_blocking_p1_finding() -> None:
    report = _gate().check((), dataset="financial_income", as_of=AS_OF)

    assert [issue.rule for issue in report.issues] == ["dataset_empty"]
    assert report.issues[0].status is DataStatus.SOURCE_ERROR
    assert report.issues[0].severity is ErrorSeverity.P1
    assert report.issues == report.blocking()


def test_a_single_bad_measurement_does_not_block_a_whole_market_scan() -> None:
    report = _gate().check(
        (_observation(value=None),), dataset="financial_income", as_of=AS_OF
    )

    assert report.blocking() == ()


def test_findings_carry_the_key_a_reader_needs() -> None:
    observations = (_observation(symbol="000001.SZ", metric="net_margin", value=None),)

    report = _gate().check(observations, dataset="financial_income", as_of=AS_OF)

    issue = report.issues[0]
    assert issue.symbol == "000001.SZ"
    assert issue.metric == "net_margin"
    assert issue.report_period == REPORT_PERIOD
