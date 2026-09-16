"""End-to-end test for the first vertical slice.

This is the test that makes the slice a slice: one call drives

    CSV → RawDataset → NormalizedDataset → QualityReport → FactorResult
        → StrategyResult → Candidate → snapshot

and the assertions below are the invariants the design cares about, not the
internal shape of any one module.
"""

from datetime import UTC, datetime
from pathlib import Path

from astock_lens.data.snapshots.store import JsonSnapshotStore, SnapshotStore
from astock_lens.domain.enums import DataStatus, NextAction, SnapshotKind
from astock_lens.factors.config import load_factor_config
from astock_lens.pipelines.first_slice import FirstSliceResult, run_first_slice
from astock_lens.strategies.config import load_strategy_config

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
FACTOR_CONFIG = ROOT / "configs" / "factors" / "avg_amount_20d.yaml"
STRATEGY_CONFIG = ROOT / "configs" / "strategies" / "momentum.yaml"


def _run(local_tmp: Path) -> FirstSliceResult:
    return run_first_slice(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        factor_config=load_factor_config(FACTOR_CONFIG),
        strategy_config=load_strategy_config(STRATEGY_CONFIG),
        store=JsonSnapshotStore(local_tmp),
    )


def test_only_symbols_with_a_complete_window_become_candidates(
    local_tmp: Path,
) -> None:
    result = _run(local_tmp)

    assert {candidate.symbol for candidate in result.candidates} == {
        "600000.SH",
        "600519.SH",
    }


def test_every_factor_result_carries_version_and_as_of(local_tmp: Path) -> None:
    result = _run(local_tmp)

    assert result.factor_results
    for factor_result in result.factor_results:
        assert factor_result.factor_version
        assert factor_result.as_of == AS_OF
        assert factor_result.lineage.factor_version == factor_result.factor_version


def test_short_history_is_null_rather_than_a_number(local_tmp: Path) -> None:
    result = _run(local_tmp)
    by_symbol = {item.symbol: item for item in result.factor_results}

    assert by_symbol["000001.SZ"].status is DataStatus.NULL
    assert by_symbol["000001.SZ"].raw_value is None
    assert by_symbol["601398.SH"].status is DataStatus.NULL
    assert by_symbol["601398.SH"].raw_value is None


def test_a_missing_input_never_became_zero(local_tmp: Path) -> None:
    """600519.SH and 601398.SH both have a blank amount in the fixture."""
    result = _run(local_tmp)
    by_symbol = {item.symbol: item for item in result.factor_results}

    for symbol in ("600519.SH", "601398.SH"):
        item = by_symbol[symbol]
        assert item.raw_value != 0
    assert by_symbol["601398.SH"].raw_value is None


def test_quality_report_covers_the_whole_dataset(local_tmp: Path) -> None:
    result = _run(local_tmp)

    assert result.quality_report.checked == 85
    assert result.quality_report.accepted == 85
    assert result.quality_report.blocking() == ()


def test_candidates_are_research_objects(local_tmp: Path) -> None:
    result = _run(local_tmp)

    assert result.candidates
    for candidate in result.candidates:
        assert candidate.next_action in set(NextAction)
        assert candidate.next_action is NextAction.IGNORE
        assert candidate.market_validation is None
        assert candidate.signal is None
        assert candidate.as_of == AS_OF


def test_snapshots_round_trip_through_the_store(local_tmp: Path) -> None:
    result = _run(local_tmp)
    store: SnapshotStore = JsonSnapshotStore(local_tmp)

    factor_records = store.read(SnapshotKind.FACTOR, AS_OF)
    candidate_records = store.read(SnapshotKind.CANDIDATE, AS_OF)

    assert len(factor_records) == len(result.factor_results)
    assert len(candidate_records) == len(result.candidates)
    assert {record["symbol"] for record in candidate_records} == {
        "600000.SH",
        "600519.SH",
    }


def test_reported_snapshot_paths_are_the_ones_written(local_tmp: Path) -> None:
    result = _run(local_tmp)

    assert result.factor_snapshot_path.is_file()
    assert result.candidate_snapshot_path.is_file()
    assert result.factor_snapshot_path == (local_tmp / "FACTOR" / "2026-09-04.json")
