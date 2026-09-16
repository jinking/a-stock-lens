"""Job run tests.

`docs/ARCHITECTURE.md` §17 requires every pipeline stage to be a job with a
recorded run: type, as_of, timing, status, rows in/out, and an error. Two rules
follow from that and are pinned down here.

First, a status that asserts a problem must carry the reason — a `FAILED` run
with no error, or a `SUCCEEDED` run carrying one, is a contradiction rather
than a report. Second, one stage runs once per day: recording it again replaces
the row instead of appending a second verdict for the same work.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from astock_lens.domain.enums import JobStage
from astock_lens.jobs.models import JobRun, JobStatus
from astock_lens.jobs.store import JsonJobStore

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
STARTED = AS_OF + timedelta(minutes=1)
FINISHED = STARTED + timedelta(seconds=30)


def _finished(status: JobStatus = JobStatus.SUCCEEDED, **overrides: object) -> JobRun:
    payload: dict[str, object] = {
        "job_type": JobStage.COMPUTE_FACTORS,
        "as_of": AS_OF,
        "status": status,
        "started_at": STARTED,
        "finished_at": FINISHED,
        "rows_in": 7,
        "rows_out": 28,
    }
    payload.update(overrides)
    return JobRun.model_validate(payload)


def test_write_then_read_round_trips_a_run(local_tmp: Path) -> None:
    store = JsonJobStore(local_tmp)
    store.record(_finished())

    runs = store.runs(AS_OF)

    assert len(runs) == 1
    run = runs[0]
    assert run.job_type is JobStage.COMPUTE_FACTORS
    assert run.status is JobStatus.SUCCEEDED
    assert run.started_at == STARTED
    assert run.finished_at == FINISHED
    assert run.rows_in == 7
    assert run.rows_out == 28


def test_runs_for_an_unwritten_date_are_empty(local_tmp: Path) -> None:
    assert JsonJobStore(local_tmp).runs(AS_OF) == ()


def test_one_stage_has_one_verdict_per_day(local_tmp: Path) -> None:
    store = JsonJobStore(local_tmp)
    store.record(_finished())
    store.record(_finished(rows_out=99))

    runs = store.runs(AS_OF)

    assert len(runs) == 1
    assert runs[0].rows_out == 99


def test_stages_keep_their_recorded_order(local_tmp: Path) -> None:
    store = JsonJobStore(local_tmp)
    store.record(_finished(job_type=JobStage.NORMALIZE))
    store.record(_finished(job_type=JobStage.COMPUTE_FACTORS))
    store.record(_finished(job_type=JobStage.NORMALIZE, rows_out=1))

    assert [run.job_type for run in store.runs(AS_OF)] == [
        JobStage.NORMALIZE,
        JobStage.COMPUTE_FACTORS,
    ]


def test_the_store_names_one_file_per_day(local_tmp: Path) -> None:
    path = JsonJobStore(local_tmp).record(_finished())

    assert path == local_tmp / "2026-09-04.json"
    assert path.is_file()


def test_a_blocked_run_must_say_why() -> None:
    with pytest.raises(ValueError, match="blocked"):
        _finished(JobStatus.BLOCKED)


def test_a_failed_run_must_say_why() -> None:
    with pytest.raises(ValueError, match="failed"):
        _finished(JobStatus.FAILED)


def test_a_successful_run_cannot_carry_an_error() -> None:
    with pytest.raises(ValueError, match="error"):
        _finished(error="something went wrong")


def test_a_terminal_run_records_when_it_finished() -> None:
    with pytest.raises(ValueError, match="finished_at"):
        _finished(finished_at=None)


def test_a_running_stage_has_not_finished_yet() -> None:
    run = JobRun(
        job_type=JobStage.SYNC_DATA,
        as_of=AS_OF,
        status=JobStatus.RUNNING,
        started_at=STARTED,
    )

    assert run.finished_at is None

    with pytest.raises(ValueError, match="RUNNING"):
        JobRun(
            job_type=JobStage.SYNC_DATA,
            as_of=AS_OF,
            status=JobStatus.RUNNING,
            started_at=STARTED,
            finished_at=FINISHED,
        )


def test_rows_stay_absent_rather_than_zero_when_a_stage_counts_nothing() -> None:
    """A stage with no row count reports `None`, never a fabricated 0."""
    run = _finished(rows_in=None, rows_out=None)

    assert run.rows_in is None
    assert run.rows_out is None


def test_a_run_carries_a_non_fatal_note_when_a_stage_reports_one() -> None:
    run = _finished(note="6 scanners have no implementation yet")

    assert run.note == "6 scanners have no implementation yet"
