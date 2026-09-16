"""Job run persistence.

One file per day, one entry per stage. Recording a stage again for the same
date replaces its entry in place, so re-running a single stage leaves exactly
one verdict behind — and the stage keeps the position it had in the run, which
is what makes the manifest readable as an execution order.

DuckDB is the design's storage for job state (`ARCHITECTURE.md` §14); like the
snapshot store, this module ships a standard-library JSON implementation as the
default so the default environment stays dependency-free. A DuckDB
implementation can replace it behind this protocol without touching a caller.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

from astock_lens.jobs.models import JobRun


class JobStore(Protocol):
    """Persistence boundary for stage runs."""

    def record(self, run: JobRun) -> Path:
        """Store one run, replacing any earlier run of the same stage and date."""
        ...

    def runs(self, as_of: datetime) -> tuple[JobRun, ...]:
        """Return the runs recorded for one date, in the order they were run."""
        ...


class JsonJobStore:
    """Write one JSON file per day, holding that day's stage runs."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def record(self, run: JobRun) -> Path:
        """Write one run, keeping a replaced run in its original position."""
        runs = list(self.runs(run.as_of))
        for index, existing in enumerate(runs):
            if existing.job_type is run.job_type:
                runs[index] = run
                break
        else:
            runs.append(run)

        path = self.path_for(run.as_of)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "as_of": run.as_of.isoformat(),
            "runs": [item.model_dump(mode="json") for item in runs],
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return path

    def runs(self, as_of: datetime) -> tuple[JobRun, ...]:
        """Read one day's runs; an absent file means no stage ran that day.

        A malformed file raises instead of reading as "nothing ran": those two
        facts are different, and conflating them would hide a corrupted
        manifest behind an empty one.
        """
        path = self.path_for(as_of)
        if not path.is_file():
            return ()

        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(  # noqa: TRY004 - the file's shape, not a caller's type
                f"job manifest is not a mapping: {path}"
            )
        runs = payload.get("runs")
        if not isinstance(runs, list):
            raise ValueError(  # noqa: TRY004 - the file's shape, not a caller's type
                f"job manifest carries no runs list: {path}"
            )
        return tuple(JobRun.model_validate(item) for item in runs)

    def path_for(self, as_of: datetime) -> Path:
        """Return the file a date's runs occupy."""
        return self._root / f"{as_of.date().isoformat()}.json"
