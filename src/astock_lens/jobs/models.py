"""Job run records.

`docs/ARCHITECTURE.md` §17 requires every pipeline stage to be a job that
records what it did: `job_type`, `as_of`, timing, `status`, rows in/out and any
error. That record is what makes a stage independently restartable — a reader
can tell which stages ran for a date, which did not, and why.

`JobStatus` belongs to the implementation rather than to `domain/enums.py`: the
design names the field but enumerates no vocabulary for it, and the vocabularies
the design *does* enumerate stay in `domain`. The same reasoning the Universe
rules use applies here.
"""

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from astock_lens.domain.enums import JobStage
from astock_lens.domain.models import DomainRecord


class JobStatus(StrEnum):
    """How a stage run ended.

    - `RUNNING`: started and not finished, so no verdict exists yet;
    - `SUCCEEDED`: finished and produced a result;
    - `FAILED`: raised; the pipeline stops because later stages consume it;
    - `BLOCKED`: cannot run at all, because a decision it needs is not
      available (a deferred threshold, a missing detector);
    - `SKIPPED`: deliberately not run by the caller for this date.
    """

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.BLOCKED,
        JobStatus.SKIPPED,
    }
)

# Statuses that assert something went wrong, and so must carry the reason.
PROBLEM_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.FAILED, JobStatus.BLOCKED}
)


class StageOutcome(DomainRecord):
    """What a stage reports back to the pipeline.

    Counts stay optional: a stage that counted nothing reports `None` rather
    than a fabricated zero, and a stage with no row concept reports `None`
    rather than pretending one applies.
    """

    rows_in: int | None = None
    rows_out: int | None = None
    note: str | None = None


class JobRun(DomainRecord):
    """One stage execution for one point in time."""

    job_type: JobStage
    as_of: datetime
    status: JobStatus
    started_at: datetime
    finished_at: datetime | None = None
    rows_in: int | None = None
    rows_out: int | None = None
    error: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _status_matches_the_evidence(self) -> Self:
        """Refuse a verdict that contradicts its own fields."""
        if self.status is JobStatus.RUNNING:
            if self.finished_at is not None:
                raise ValueError(
                    "a RUNNING job has not finished, so it must not record finished_at"
                )
        elif self.finished_at is None:
            raise ValueError(
                f"a {self.status} job must record when it finished_at (or stay RUNNING)"
            )

        if self.status in PROBLEM_JOB_STATUSES:
            if self.error is None or not self.error.strip():
                raise ValueError(
                    f"a {self.status.value.lower()} job must record why: an "
                    "unexplained blocked or failed stage is not a report"
                )
        elif self.error is not None:
            raise ValueError(
                f"a {self.status} job must not carry an error; use note for "
                "non-fatal context"
            )
        return self
