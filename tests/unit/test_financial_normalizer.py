"""Financial normalizer tests.

The rules these tests pin down are the ones that decide whether a fundamental
factor can be trusted at all:

- every observation carries `report_period`, `announce_date` and a
  timezone-aware `available_at` that is not after the requested `as_of`
  (`spec §5.1`, `DATA_MODEL.md` §2);
- a row whose publication date cannot be read produces nothing, because the
  design forbids letting such a record reach a point-in-time factor;
- a `-` stays a missing value (`None`), never zero, and unreadable text becomes
  a failure record rather than a silent `None`.

The fixture replay covers the real source shape; the small synthetic tables
cover the edge cases the fixture does not contain.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.normalize.financials import (
    FINANCIAL_METRICS,
    METRIC_BY_COLUMN,
    FinancialStatementNormalizer,
)
from astock_lens.data.providers.westock import CommandResult, parse_tables
from astock_lens.domain.enums import DataStatus

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "westock"

AS_OF = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)
FETCHED_AT = datetime(2026, 9, 16, 15, 5, tzinfo=UTC)

# 2026-08-15 15:00 +08:00 is the publication of the H1-2026 report.
AFTER_H1 = datetime(2026, 8, 16, 15, 0, tzinfo=UTC)
BEFORE_H1 = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)


def _markdown(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    return f"{header}\n{separator}\n{body}\n"


def _raw(text: str, *, status: DataStatus = DataStatus.VALUE) -> RawDataset:
    table = parse_tables(text)[0]
    return RawDataset(
        provider="westock-cli",
        dataset="financial_income",
        fetched_at=FETCHED_AT,
        provider_version="v1",
        status=status,
        row_count=len(table.rows),
        payload=RawPayload(columns=table.columns, rows=table.rows),
    )


def _replayed(dataset: str) -> RawDataset:
    """The recorded command output, turned into a raw dataset as the provider does."""
    table = parse_tables((FIXTURES / f"{dataset}.md").read_text(encoding="utf-8"))[0]
    return RawDataset(
        provider="westock-cli",
        dataset=dataset,
        fetched_at=FETCHED_AT,
        provider_version="v1",
        status=DataStatus.VALUE,
        row_count=len(table.rows),
        payload=RawPayload(columns=table.columns, rows=table.rows),
    )


def test_recorded_income_statement_normalizes_with_time_on_every_record() -> None:
    outcome = FinancialStatementNormalizer().normalize(
        _replayed("financial_income"), as_of=AS_OF
    )

    assert outcome.source_status is DataStatus.VALUE
    assert outcome.observations
    # Three symbols, eight periods, and one observation per mapped metric that
    # the source actually publishes.
    published = sum(
        1 for metric in FINANCIAL_METRICS if metric.column not in outcome.absent_columns
    )
    assert len(outcome.observations) == 24 * published

    for observation in outcome.observations:
        assert observation.report_period is not None
        assert observation.announce_date is not None
        assert observation.available_at.tzinfo is not None
        assert observation.available_at <= observation.as_of == AS_OF
        assert observation.source == "westock-cli"


def test_columns_the_source_does_not_publish_are_named() -> None:
    outcome = FinancialStatementNormalizer().normalize(
        _replayed("financial_income"), as_of=AS_OF
    )

    # Balance-sheet and cash-flow fields are absent from an income statement:
    # that is a fact about the source shape, not a reason to invent a value.
    assert "TotalShareholderEquity" in outcome.absent_columns
    assert "NetOperateCashFlow" in outcome.absent_columns
    assert "OperatingRevenue" not in outcome.absent_columns


def test_units_are_carried_so_a_reader_never_guesses_the_scale() -> None:
    outcome = FinancialStatementNormalizer().normalize(
        _replayed("financial_income"), as_of=AS_OF
    )
    units = {(item.metric, item.unit) for item in outcome.observations}

    assert ("roe", "%") in units
    assert ("revenue", "CNY") in units
    assert ("eps", "CNY/share") in units
    assert ("net_margin", "%") in units


def test_a_row_published_after_the_requested_point_in_time_is_excluded_and_counted() -> (
    None
):
    raw = _raw(
        _markdown(
            ("code", "EndDate", "InfoPublDate", "OperatingRevenue"),
            (
                ("sh600519", "2026-06-30", "2026-08-15", "90703260964.48"),
                ("sh600519", "2026-03-31", "2026-04-25", "53909252220.51"),
            ),
        )
    )

    outcome = FinancialStatementNormalizer().normalize(raw, as_of=BEFORE_H1)

    assert outcome.not_yet_available == 1
    assert [item.report_period for item in outcome.observations] == [date(2026, 3, 31)]


def test_the_whole_report_becomes_usable_once_its_publication_time_has_passed() -> None:
    raw = _raw(
        _markdown(
            ("code", "EndDate", "InfoPublDate", "OperatingRevenue"),
            (("sh600519", "2026-06-30", "2026-08-15", "90703260964.48"),),
        )
    )

    outcome = FinancialStatementNormalizer().normalize(raw, as_of=AFTER_H1)

    assert outcome.not_yet_available == 0
    assert len(outcome.observations) == 1
    assert outcome.observations[0].available_at == datetime(
        2026, 8, 15, 15, 0, tzinfo=outcome.observations[0].available_at.tzinfo
    )


def test_a_missing_marker_stays_a_missing_value() -> None:
    raw = _raw(
        _markdown(
            ("code", "EndDate", "InfoPublDate", "OperatingRevenue"),
            (("sh600519", "2026-06-30", "2026-08-15", "-"),),
        )
    )

    outcome = FinancialStatementNormalizer().normalize(raw, as_of=AS_OF)

    assert outcome.failures == ()
    assert len(outcome.observations) == 1
    assert outcome.observations[0].value is None


def test_unreadable_text_becomes_a_failure_not_a_zero() -> None:
    raw = _raw(
        _markdown(
            ("code", "EndDate", "InfoPublDate", "OperatingRevenue"),
            (("sh600519", "2026-06-30", "2026-08-15", "not-a-number"),),
        )
    )

    outcome = FinancialStatementNormalizer().normalize(raw, as_of=AS_OF)

    assert outcome.observations[0].value is None
    assert len(outcome.failures) == 1
    failure = outcome.failures[0]
    assert failure.symbol == "600519.SH"
    assert failure.metric == "revenue"
    assert failure.raw_value == "not-a-number"


def test_a_row_without_a_publication_date_produces_nothing() -> None:
    raw = _raw(
        _markdown(
            ("code", "EndDate", "InfoPublDate", "OperatingRevenue"),
            (("sh600519", "2026-06-30", "-", "90703260964.48"),),
        )
    )

    outcome = FinancialStatementNormalizer().normalize(raw, as_of=AS_OF)

    assert outcome.observations == ()
    assert any(failure.column == "InfoPublDate" for failure in outcome.failures)
    assert "point-in-time" in outcome.failures[0].reason


def test_an_unreadable_instrument_code_produces_nothing() -> None:
    raw = _raw(
        _markdown(
            ("code", "EndDate", "InfoPublDate", "OperatingRevenue"),
            (("xx600519", "2026-06-30", "2026-08-15", "1.0"),),
        )
    )

    outcome = FinancialStatementNormalizer().normalize(raw, as_of=AS_OF)

    assert outcome.observations == ()
    assert outcome.failures[0].column == "code"


def test_an_empty_source_reports_its_status_rather_than_inventing_rows() -> None:
    raw = RawDataset(
        provider="westock-cli",
        dataset="financial_income",
        fetched_at=FETCHED_AT,
        provider_version="v1",
        status=DataStatus.NULL,
        row_count=0,
    )

    outcome = FinancialStatementNormalizer().normalize(raw, as_of=AS_OF)

    assert outcome.source_status is DataStatus.NULL
    assert outcome.observations == ()
    assert outcome.failures == ()


def test_every_mapped_metric_has_a_unique_source_column() -> None:
    columns = [metric.column for metric in FINANCIAL_METRICS]
    names = [metric.metric for metric in FINANCIAL_METRICS]

    assert len(columns) == len(set(columns))
    assert len(names) == len(set(names))
    assert set(METRIC_BY_COLUMN) == set(columns)


def test_the_normalizer_never_reaches_for_a_provider() -> None:
    """`ARCHITECTURE.md` §4.3: normalizing reads data, it never fetches it.

    The module may borrow the source's code vocabulary, but it must not own a
    transport, a subprocess or a network call of its own.
    """
    source = Path("src/astock_lens/data/normalize/financials.py").read_text(
        encoding="utf-8"
    )

    assert "subprocess" not in source
    assert "urlopen" not in source
    assert "Runner" not in source
    assert ".fetch(" not in source
    assert "requests" not in source


def test_the_recorded_shape_is_not_mutated_by_normalizing() -> None:
    raw = _replayed("financial_income")
    before = raw.payload

    FinancialStatementNormalizer().normalize(raw, as_of=AS_OF)

    assert raw.payload is before
    assert raw.payload is not None
    assert raw.row_count == len(raw.payload.rows)


def test_a_command_that_answered_nothing_is_not_treated_as_an_empty_market() -> None:
    runner = lambda argv: CommandResult(returncode=0, stdout="", stderr="")
    from astock_lens.data.contracts import FetchRequest
    from astock_lens.data.providers.westock import WestockCliProvider

    raw = WestockCliProvider("/opt/westock", runner=runner).fetch(
        FetchRequest(dataset="financial_income", as_of=AS_OF, symbols=("600519.SH",))
    )
    outcome = FinancialStatementNormalizer().normalize(raw, as_of=AS_OF)

    assert raw.status is DataStatus.NULL
    assert outcome.source_status is DataStatus.NULL


def test_every_metric_declares_a_unit() -> None:
    missing = [metric.metric for metric in FINANCIAL_METRICS if not metric.unit]
    assert not missing, f"缺少单位的指标: {missing}"
