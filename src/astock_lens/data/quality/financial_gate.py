"""Data Quality Gate for canonical financial observations.

Same contract as the daily-bar gate: this gate **reports**, it never repairs,
and it never drops a record from the sequence it was handed. Callers decide
what to do with the verdict through `usable_observations()`, so the judgement
stays visible in the report after the bad records have been set aside.

The rules come from `docs/ARCHITECTURE.md` §4.4 and `docs/DATA_MODEL.md` §2:

- a statement that yielded nothing is a **P1** finding (the module that needs
  fundamentals has to degrade, loudly);
- a cell the source left empty is `NULL`, not zero, and is **not** a defect —
  the source is allowed to have no value;
- a cell the normalizer could not read is `INVALID`;
- a duplicated `(symbol, metric, report_period)` key is `INVALID`, because two
  values for one measurement at one point in time is not a measurement.

Nothing here invents a threshold, and a missing value never becomes a number.
"""

from collections import Counter
from datetime import date, datetime

from astock_lens.data.normalize.financials import FinancialNormalizeFailure
from astock_lens.domain.enums import DataStatus, ErrorSeverity
from astock_lens.domain.models import DomainRecord, FinancialObservation

# A single unusable measurement is P2 ("non-critical missing data; continue with
# a warning"): fundamentals lag by weeks, and one missing ratio must not block a
# whole-market scan.
SEVERITY_BY_RULE: dict[str, ErrorSeverity] = {
    "dataset_empty": ErrorSeverity.P1,
    "value_missing": ErrorSeverity.P2,
    "value_not_numeric": ErrorSeverity.P2,
    "duplicate_primary_key": ErrorSeverity.P2,
}

BLOCKING_SEVERITIES: frozenset[ErrorSeverity] = frozenset(
    {ErrorSeverity.P0, ErrorSeverity.P1}
)


class FinancialQualityIssue(DomainRecord):
    """One rule violation, keyed the way a financial record is keyed."""

    rule: str
    status: DataStatus
    severity: ErrorSeverity
    message: str
    symbol: str | None = None
    metric: str | None = None
    report_period: date | None = None


class FinancialQualityReport(DomainRecord):
    """The gate's verdict for one statement dataset at one point in time."""

    dataset: str
    as_of: datetime
    checked: int
    usable: int
    rules_version: str
    issues: tuple[FinancialQualityIssue, ...] = ()

    def blocking(self) -> tuple[FinancialQualityIssue, ...]:
        """Return the findings that must stop or degrade the current scan."""
        return tuple(
            issue for issue in self.issues if issue.severity in BLOCKING_SEVERITIES
        )


class FinancialQualityGate:
    """Apply the documented validity rules to canonical observations."""

    def __init__(self, rules_version: str = "v1") -> None:
        self._rules_version = rules_version

    def check(
        self,
        observations: tuple[FinancialObservation, ...],
        *,
        dataset: str,
        as_of: datetime,
        failures: tuple[FinancialNormalizeFailure, ...] = (),
    ) -> FinancialQualityReport:
        """Report every violation without touching the input."""
        if not observations and not failures:
            return FinancialQualityReport(
                dataset=dataset,
                as_of=as_of,
                checked=0,
                usable=0,
                rules_version=self._rules_version,
                issues=(
                    FinancialQualityIssue(
                        rule="dataset_empty",
                        status=DataStatus.SOURCE_ERROR,
                        severity=SEVERITY_BY_RULE["dataset_empty"],
                        message=(
                            "the statement yielded no observations, so nothing "
                            "downstream can be computed from it"
                        ),
                    ),
                ),
            )

        keys = [(item.symbol, item.metric, item.report_period) for item in observations]
        key_counts = Counter(keys)
        unreadable = {
            (failure.symbol, failure.metric, failure.report_period)
            for failure in failures
            if failure.metric is not None
        }

        issues: list[FinancialQualityIssue] = []
        invalid: set[tuple[str, str, date]] = set()

        for observation in observations:
            key = (observation.symbol, observation.metric, observation.report_period)

            if key_counts[key] > 1:
                issues.append(
                    _issue(
                        "duplicate_primary_key",
                        DataStatus.INVALID,
                        observation,
                        "the (symbol, metric, report_period) key appears more "
                        "than once",
                    )
                )
                invalid.add(key)

            if key in unreadable:
                issues.append(
                    _issue(
                        "value_not_numeric",
                        DataStatus.INVALID,
                        observation,
                        "the source cell could not be read as a number",
                    )
                )
                invalid.add(key)
            elif observation.value is None:
                issues.append(
                    _issue(
                        "value_missing",
                        DataStatus.NULL,
                        observation,
                        "the source reported no value for this measurement",
                    )
                )

        return FinancialQualityReport(
            dataset=dataset,
            as_of=as_of,
            checked=len(observations),
            usable=sum(1 for key in keys if key not in invalid),
            rules_version=self._rules_version,
            issues=tuple(issues),
        )


def usable_observations(
    observations: tuple[FinancialObservation, ...],
    report: FinancialQualityReport,
) -> tuple[FinancialObservation, ...]:
    """Return the observations the report did not flag as invalid.

    A `NULL` observation stays: "the source has no value for this measurement"
    is information a factor must be able to report, and removing it would make
    a gap indistinguishable from a metric nobody computes.
    """
    invalid = {
        (issue.symbol, issue.metric, issue.report_period)
        for issue in report.issues
        if issue.status is DataStatus.INVALID
    }
    return tuple(
        item
        for item in observations
        if (item.symbol, item.metric, item.report_period) not in invalid
    )


def _issue(
    rule: str,
    status: DataStatus,
    observation: FinancialObservation,
    message: str,
) -> FinancialQualityIssue:
    return FinancialQualityIssue(
        rule=rule,
        status=status,
        severity=SEVERITY_BY_RULE[rule],
        message=message,
        symbol=observation.symbol,
        metric=observation.metric,
        report_period=observation.report_period,
    )
