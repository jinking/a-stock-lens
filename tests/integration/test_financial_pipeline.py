"""End-to-end test for the fundamentals side of the pipeline.

The rule this pins down: a landed statement reaches the factor context as
canonical observations, gated, with the point-in-time fields intact — and a
statement that was never landed is *named* rather than silently treated as an
empty one.
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from astock_lens.pipelines import stages

ROOT = Path(__file__).resolve().parents[2]
CSV_FIXTURES = ROOT / "tests" / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LONG_DATASET = "daily_bars_long"

INCOME_CSV = (
    "code,EndDate,InfoPublDate,OperatingRevenue,ROE,GrossIncomeRatio\n"
    "sh600519,2026-06-30,2026-08-15,90703260964.48,17.7179,89.5552\n"
    "sh600519,2026-03-31,2026-04-25,53909252220.51,10.0565,89.7592\n"
    "sh600519,2026-09-30,2026-11-01,1.0,2.0,3.0\n"
)


def _root_with_financials(local_tmp: Path) -> Path:
    """A raw root holding the bar fixtures plus one landed income statement."""
    for name in ("daily_bars_long.csv", "securities.csv"):
        shutil.copyfile(CSV_FIXTURES / name, local_tmp / name)
    (local_tmp / "financial_income.csv").write_text(INCOME_CSV, encoding="utf-8")
    return local_tmp


def test_a_landed_statement_reaches_the_factor_context(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root_with_financials(local_tmp),
        as_of=AS_OF,
        dataset=LONG_DATASET,
    )

    observations = outcome.bars.observations
    assert observations
    assert {item.metric for item in observations} == {
        "revenue",
        "roe",
        "gross_margin",
    }
    assert all(item.available_at <= AS_OF for item in observations)
    assert all(item.report_period is not None for item in observations)


def test_a_period_published_after_the_scan_is_not_in_the_context(
    local_tmp: Path,
) -> None:
    """The 2026-09-30 period was announced on 2026-11-01, after this scan."""
    outcome = stages.normalize_stage(
        csv_root=_root_with_financials(local_tmp),
        as_of=AS_OF,
        dataset=LONG_DATASET,
    )

    periods = {item.report_period for item in outcome.bars.observations}
    assert periods == {_date(2026, 6, 30), _date(2026, 3, 31)}
    assert outcome.financials.outcomes[0].not_yet_available == 1


def test_statements_that_were_never_landed_are_named(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root_with_financials(local_tmp),
        as_of=AS_OF,
        dataset=LONG_DATASET,
    )

    assert outcome.financials.absent_datasets == (
        "financial_balance",
        "financial_cashflow",
    )
    assert {report.dataset for report in outcome.financials.reports} == {
        "financial_income"
    }


def test_a_scan_without_landed_statements_still_runs_and_says_so(
    local_tmp: Path,
) -> None:
    """Bars must keep working before the first fundamentals sync."""
    shutil.copyfile(
        CSV_FIXTURES / "daily_bars_long.csv", local_tmp / "daily_bars_long.csv"
    )
    shutil.copyfile(CSV_FIXTURES / "securities.csv", local_tmp / "securities.csv")

    outcome = stages.normalize_stage(
        csv_root=local_tmp, as_of=AS_OF, dataset=LONG_DATASET
    )

    assert outcome.bars.observations == ()
    assert outcome.financials.observations == ()
    assert outcome.financials.absent_datasets == (
        "financial_balance",
        "financial_cashflow",
        "financial_income",
    )
    assert outcome.bars.daily_bars


def test_a_missing_value_stays_missing_through_the_pipeline(local_tmp: Path) -> None:
    root = _root_with_financials(local_tmp)
    (root / "financial_income.csv").write_text(
        "code,EndDate,InfoPublDate,OperatingRevenue,ROE\n"
        "sh600519,2026-06-30,2026-08-15,-,17.7179\n",
        encoding="utf-8",
    )

    outcome = stages.normalize_stage(csv_root=root, as_of=AS_OF, dataset=LONG_DATASET)

    revenue = next(
        item for item in outcome.bars.observations if item.metric == "revenue"
    )
    assert revenue.value is None
    report = outcome.financials.reports[0]
    assert [issue.rule for issue in report.issues] == ["value_missing"]
    assert report.usable == 2


def test_the_two_statement_sets_land_and_normalize_together(local_tmp: Path) -> None:
    """Both a balance sheet and an income statement in one context."""
    root = _root_with_financials(local_tmp)
    (root / "financial_balance.csv").write_text(
        "code,EndDate,InfoPublDate,TotalShareholderEquity,DebtAssetsRatio\n"
        "sh600519,2026-06-30,2026-08-15,262096352174.36,15.1931\n",
        encoding="utf-8",
    )

    outcome = stages.normalize_stage(csv_root=root, as_of=AS_OF, dataset=LONG_DATASET)

    metrics = {item.metric for item in outcome.bars.observations}
    assert {"revenue", "total_equity", "debt_to_asset"} <= metrics
    assert outcome.financials.absent_datasets == ("financial_cashflow",)


def _date(year: int, month: int, day: int) -> object:
    from datetime import date

    return date(year, month, day)
