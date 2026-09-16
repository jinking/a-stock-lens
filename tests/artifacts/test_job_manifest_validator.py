"""The independent check on the job manifest.

`spec §15` requires a job state per stage, and an operator reads that manifest
to see what a daily run actually did. This module judges it with the same rule
as the rest of `tests/artifacts`: it shares no code with the pipeline, so a
systematic mistake in the pipeline cannot hide from it.

Corrupted manifests are fed in first — an unrun stage, a duplicate verdict, a
`BLOCKED` stage with no explanation, a timestamp from the wrong day — so the
checks are seen failing before they are trusted passing.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from artifacts.validator import ArtifactFinding, validate_job_manifest
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.factors.config import load_factor_config
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines.daily import run_daily
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LONG_DATASET = "daily_bars_long"

STAGES = (
    "SYNC_DATA",
    "NORMALIZE",
    "BUILD_UNIVERSE",
    "COMPUTE_FACTORS",
    "RUN_STRATEGIES",
    "DETECT_REGIME",
    "MARKET_VALIDATE",
    "RUN_SIGNALS",
    "BUILD_CANDIDATES",
    "UPDATE_WATCHLIST",
    "GENERATE_DAILY_SNAPSHOT",
)

# The stages that cannot run yet, and so are legitimately blocked.
BLOCKED_STAGES = {"DETECT_REGIME", "MARKET_VALIDATE", "RUN_SIGNALS"}


def _record(stage: str) -> dict[str, object]:
    if stage in BLOCKED_STAGES:
        return {
            "job_type": stage,
            "as_of": AS_OF.isoformat(),
            "status": "BLOCKED",
            "started_at": AS_OF.isoformat(),
            "finished_at": AS_OF.isoformat(),
            "error": "no detector exists for this stage yet",
        }
    return {
        "job_type": stage,
        "as_of": AS_OF.isoformat(),
        "status": "SUCCEEDED",
        "started_at": AS_OF.isoformat(),
        "finished_at": (AS_OF + timedelta(seconds=1)).isoformat(),
        "rows_in": 11,
        "rows_out": 11,
    }


def _manifest(stage: str = "NORMALIZE", **overrides: object) -> list[dict[str, object]]:
    """One run per design stage, with `overrides` applied to one of them."""
    records = [_record(name) for name in STAGES]
    for record in records:
        if record["job_type"] == stage:
            record.update(overrides)
    return records


def _checks(findings: tuple[ArtifactFinding, ...]) -> list[str]:
    return [finding.check for finding in findings]


def test_a_clean_manifest_produces_no_findings() -> None:
    assert validate_job_manifest(_manifest(), as_of=AS_OF) == ()


def test_an_empty_manifest_is_a_finding() -> None:
    assert "manifest_stages" in _checks(validate_job_manifest([], as_of=AS_OF))


def test_a_stage_with_no_recorded_run_is_reported() -> None:
    records = [item for item in _manifest() if item["job_type"] != "RUN_SIGNALS"]

    findings = validate_job_manifest(records, as_of=AS_OF)

    assert "manifest_stages" in _checks(findings)
    assert any("RUN_SIGNALS" in finding.observed for finding in findings)


def test_a_duplicated_verdict_is_reported() -> None:
    findings = validate_job_manifest([*_manifest(), _record("NORMALIZE")], as_of=AS_OF)

    assert "duplicate_stage" in _checks(findings)


def test_a_blocked_stage_without_a_reason_is_reported() -> None:
    findings = validate_job_manifest(
        _manifest("DETECT_REGIME", error=None), as_of=AS_OF
    )

    assert "job_status" in _checks(findings)


def test_a_successful_stage_carrying_an_error_is_reported() -> None:
    findings = validate_job_manifest(_manifest(error="leftover"), as_of=AS_OF)

    assert "job_status" in _checks(findings)


def test_a_terminal_stage_without_a_finish_time_is_reported() -> None:
    findings = validate_job_manifest(_manifest(finished_at=None), as_of=AS_OF)

    assert "job_status" in _checks(findings)


def test_a_finish_before_the_start_is_reported() -> None:
    """A job may finish after `as_of` — that is when the pipeline runs. What
    cannot happen is finishing before it started."""
    findings = validate_job_manifest(
        _manifest(
            finished_at=AS_OF.isoformat(), started_at="2026-09-04T16:00:00+00:00"
        ),
        as_of=AS_OF,
    )

    assert "timestamp" in _checks(findings)


def test_a_stage_outside_the_design_is_reported() -> None:
    invented = _record("NORMALIZE") | {"job_type": "INVENT_SOMETHING"}

    findings = validate_job_manifest([*_manifest(), invented], as_of=AS_OF)

    assert "known_stage" in _checks(findings)


def test_a_manifest_for_another_date_is_reported() -> None:
    findings = validate_job_manifest(
        _manifest(as_of="2026-09-05T15:00:00+00:00"), as_of=AS_OF
    )

    assert "timestamp" in _checks(findings)


def test_the_manifest_a_daily_run_writes_validates_cleanly(local_tmp: Path) -> None:
    run_daily(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=load_universe_config(CONFIGS / "universe.yaml"),
        factor_configs=tuple(
            load_factor_config(path)
            for path in sorted((CONFIGS / "factors").glob("*.yaml"))
        ),
        scanners=load_scanners(CONFIGS / "strategies"),
        strategy_directory=CONFIGS / "strategies",
        store=JsonSnapshotStore(local_tmp / "snapshots"),
        job_store=JsonJobStore(local_tmp / "jobs"),
        dataset=LONG_DATASET,
    )

    manifest = JsonJobStore(local_tmp / "jobs").runs(AS_OF)
    records = [run.model_dump(mode="json") for run in manifest]

    assert validate_job_manifest(records, as_of=AS_OF) == ()
