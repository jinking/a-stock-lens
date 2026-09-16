"""Data Quality Gate tests.

The gate reports; it never repairs. Every rule here traces to
`docs/ARCHITECTURE.md` §4.4, and invalid bars stay in the dataset so the
verdict is visible instead of being filtered away silently.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from astock_lens.data.contracts import FetchRequest, NormalizedDataset
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.quality.gate import DailyBarQualityGate, valid_bars
from astock_lens.domain.enums import DataStatus, ErrorSeverity

CSV_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _normalize(dataset: str) -> NormalizedDataset:
    raw = LocalCsvProvider(CSV_ROOT).fetch(FetchRequest(dataset=dataset, as_of=AS_OF))
    return CsvDailyBarNormalizer().normalize(raw, as_of=AS_OF)


def _rules(normalized: NormalizedDataset) -> dict[str, int]:
    report = DailyBarQualityGate().check(normalized)
    counts: dict[str, int] = {}
    for issue in report.issues:
        counts[issue.rule] = counts.get(issue.rule, 0) + 1
    return counts


def test_clean_dataset_passes_with_no_issues() -> None:
    normalized = _normalize("daily_bars")

    report = DailyBarQualityGate().check(normalized)

    assert report.issues == ()
    assert report.checked == 85
    assert report.accepted == 85


def test_each_documented_rule_fires_on_the_dirty_fixture() -> None:
    """Every rule in the §4.4 table is reachable from one fixture file."""
    counts = _rules(_normalize("dirty_bars"))

    assert counts["close_missing"] == 2
    assert counts["close_not_positive"] == 1
    assert counts["volume_negative"] == 1
    assert counts["duplicate_primary_key"] == 2


def test_invalid_findings_are_p2_and_do_not_block_a_scan() -> None:
    report = DailyBarQualityGate().check(_normalize("dirty_bars"))

    invalid = [issue for issue in report.issues if issue.status is DataStatus.INVALID]

    assert invalid
    assert all(issue.severity is ErrorSeverity.P2 for issue in invalid)
    assert report.blocking() == ()


def test_empty_dataset_is_a_blocking_p1() -> None:
    raw = LocalCsvProvider(CSV_ROOT).fetch(
        FetchRequest(dataset="does_not_exist", as_of=AS_OF)
    )
    normalized = CsvDailyBarNormalizer().normalize(raw, as_of=AS_OF)

    report = DailyBarQualityGate().check(normalized)

    assert report.checked == 0
    assert [issue.rule for issue in report.blocking()] == ["dataset_empty"]
    assert report.blocking()[0].status is DataStatus.SOURCE_ERROR
    assert report.blocking()[0].severity is ErrorSeverity.P1


def test_valid_bars_excludes_only_the_flagged_ones() -> None:
    normalized = _normalize("dirty_bars")
    report = DailyBarQualityGate().check(normalized)

    survivors = valid_bars(normalized, report)

    assert [(bar.symbol, bar.trade_date) for bar in survivors] == [
        ("600000.SH", date(2026, 9, 3))
    ]


def test_gate_does_not_mutate_its_input() -> None:
    normalized = _normalize("dirty_bars")
    before = normalized.daily_bars

    DailyBarQualityGate().check(normalized)

    assert normalized.daily_bars == before
    assert len(normalized.daily_bars) == 7
