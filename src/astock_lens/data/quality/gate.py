"""Data Quality Gate for canonical daily bars.

The gate **reports** validity; it never repairs it and never removes a bar from
the dataset it was handed. Callers decide what to do with the verdict through
`valid_bars()`, which keeps the judgement visible in the report even after the
bad bars have been set aside.

Every rule below is traceable to `docs/ARCHITECTURE.md` §4.4. No ratio-based
escalation, no "extreme value" heuristic, and no threshold is invented here —
a value is either objectively impossible or it is passed through untouched.
"""

from collections import Counter
from datetime import date, datetime

from astock_lens.data.contracts import NormalizedDataset
from astock_lens.domain.enums import DataStatus, ErrorSeverity
from astock_lens.domain.models import DailyBar, DomainRecord

# Per-record findings are P2 ("non-critical missing data; continue with a
# warning"): one bad bar must never block a whole-market scan. A dataset that
# yields nothing at all is P1 ("key dataset unavailable; block or degrade the
# related module").
SEVERITY_BY_RULE: dict[str, ErrorSeverity] = {
    "close_missing": ErrorSeverity.P2,
    "close_not_positive": ErrorSeverity.P2,
    "volume_negative": ErrorSeverity.P2,
    "duplicate_primary_key": ErrorSeverity.P2,
    "dataset_empty": ErrorSeverity.P1,
}

BLOCKING_SEVERITIES: frozenset[ErrorSeverity] = frozenset(
    {ErrorSeverity.P0, ErrorSeverity.P1}
)


class QualityIssue(DomainRecord):
    """One rule violation, with enough context to act on it."""

    rule: str
    status: DataStatus
    severity: ErrorSeverity
    message: str
    symbol: str | None = None
    trade_date: date | None = None


class QualityReport(DomainRecord):
    """The gate's verdict for one dataset at one point in time."""

    dataset: str
    as_of: datetime
    checked: int
    accepted: int
    rules_version: str
    issues: tuple[QualityIssue, ...] = ()

    def blocking(self) -> tuple[QualityIssue, ...]:
        """Return the findings that must stop or degrade the current scan."""
        return tuple(
            issue for issue in self.issues if issue.severity in BLOCKING_SEVERITIES
        )


class DailyBarQualityGate:
    """Apply the documented validity rules to canonical daily bars."""

    def __init__(self, rules_version: str = "v1") -> None:
        self._rules_version = rules_version

    def check(self, dataset: NormalizedDataset) -> QualityReport:
        """Report every violation without touching the input."""
        bars = dataset.daily_bars

        if not bars:
            return QualityReport(
                dataset=dataset.dataset,
                as_of=dataset.as_of,
                checked=0,
                accepted=0,
                rules_version=self._rules_version,
                issues=(
                    QualityIssue(
                        rule="dataset_empty",
                        status=DataStatus.SOURCE_ERROR,
                        severity=SEVERITY_BY_RULE["dataset_empty"],
                        message=(
                            "the dataset yielded no bars, so nothing downstream "
                            "can be computed for it"
                        ),
                    ),
                ),
            )

        key_counts = Counter((bar.symbol, bar.trade_date) for bar in bars)
        issues: list[QualityIssue] = []
        flagged: set[int] = set()

        for index, bar in enumerate(bars):
            if bar.close is None:
                issues.append(
                    _issue(
                        "close_missing",
                        bar,
                        "close is absent, so the bar carries no valid market data",
                    )
                )
                flagged.add(index)
            elif bar.close <= 0:
                issues.append(
                    _issue(
                        "close_not_positive",
                        bar,
                        f"close must be positive, found {bar.close}",
                    )
                )
                flagged.add(index)

            if bar.volume is not None and bar.volume < 0:
                issues.append(
                    _issue(
                        "volume_negative",
                        bar,
                        f"volume must not be negative, found {bar.volume}",
                    )
                )
                flagged.add(index)

            if key_counts[(bar.symbol, bar.trade_date)] > 1:
                issues.append(
                    _issue(
                        "duplicate_primary_key",
                        bar,
                        "the (symbol, trade_date) key appears more than once",
                    )
                )
                flagged.add(index)

        return QualityReport(
            dataset=dataset.dataset,
            as_of=dataset.as_of,
            checked=len(bars),
            accepted=len(bars) - len(flagged),
            rules_version=self._rules_version,
            issues=tuple(issues),
        )


def valid_bars(
    dataset: NormalizedDataset, report: QualityReport
) -> tuple[DailyBar, ...]:
    """Return the bars the report did not flag as invalid.

    Keyed on `(symbol, trade_date)`, so a duplicated pair is dropped together
    rather than leaving an arbitrary survivor.
    """
    invalid_keys = {
        (issue.symbol, issue.trade_date)
        for issue in report.issues
        if issue.status is DataStatus.INVALID
        and issue.symbol is not None
        and issue.trade_date is not None
    }
    return tuple(
        bar
        for bar in dataset.daily_bars
        if (bar.symbol, bar.trade_date) not in invalid_keys
    )


def _issue(rule: str, bar: DailyBar, message: str) -> QualityIssue:
    return QualityIssue(
        rule=rule,
        status=DataStatus.INVALID,
        severity=SEVERITY_BY_RULE[rule],
        message=message,
        symbol=bar.symbol,
        trade_date=bar.trade_date,
    )
