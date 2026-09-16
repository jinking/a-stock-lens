"""CLI deep research adapter.

V1 integrates with `a-share-deep-research` through a command rather than an
import, which is what keeps the two repositories independent
(`ARCHITECTURE.md` §13.2). The command is supplied through
`ASTOCK_DEEP_RESEARCH_CMD`; the exact call shape belongs to the integrating
system, so it is an implementation boundary here, not a product rule.

The protocol is one JSON document in, one JSON document out:

    {"action": "submit", "request": {...}}  → a ResearchJob payload
    {"action": "status", "job_id": "..."}   → a ResearchJobStatus payload
    {"action": "result", "job_id": "..."}   → a ResearchSummary payload

Nothing here invents an outcome. A command that fails, times out, or prints
something unreadable raises: `ResearchJobStatus.state` stays whatever the other
system called it, and an unfinished job never turns into a summary.
"""

import json
import os
import shlex
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

from astock_lens.research.models import (
    ResearchJob,
    ResearchJobStatus,
    ResearchRequest,
    ResearchSummary,
)

COMMAND_ENV = "ASTOCK_DEEP_RESEARCH_CMD"

# A research job can legitimately run for a long time; this bound exists so a
# hung command fails visibly rather than blocking the CLI forever.
DEFAULT_TIMEOUT_SECONDS = 300.0


class DeepResearchNotConfigured(RuntimeError):
    """No deep research command is configured."""


class DeepResearchInvocationError(RuntimeError):
    """The configured command failed, timed out, or printed something unusable."""


@dataclass(frozen=True)
class CliDeepResearchAdapter:
    """Submit and poll research jobs through an external command."""

    command: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """Refuse an unconfigured adapter where it is built, not where it fails."""
        if not self.command.strip():
            raise DeepResearchNotConfigured(
                f"no deep research command configured; set {COMMAND_ENV}"
            )

    def submit(self, request: ResearchRequest) -> ResearchJob:
        """Submit a research request and return the created job."""
        payload = self._invoke(
            {"action": "submit", "request": request.model_dump(mode="json")}
        )
        return ResearchJob.model_validate(payload)

    def status(self, job_id: str) -> ResearchJobStatus:
        """Report the current status of a submitted job."""
        payload = self._invoke({"action": "status", "job_id": job_id})
        return ResearchJobStatus.model_validate(payload)

    def result(self, job_id: str) -> ResearchSummary:
        """Return the stored summary for a finished job."""
        payload = self._invoke({"action": "result", "job_id": job_id})
        return ResearchSummary.model_validate(payload)

    def _invoke(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        """Run the command once and return the JSON document it printed."""
        try:
            completed = subprocess.run(
                shlex.split(self.command),
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise DeepResearchInvocationError(
                f"deep research command timed out after {self.timeout_seconds}s"
            ) from error
        except OSError as error:
            raise DeepResearchInvocationError(
                f"deep research command could not be started: {error}"
            ) from error

        if completed.returncode != 0:
            detail = completed.stderr.strip() or "(no stderr)"
            raise DeepResearchInvocationError(
                f"deep research command exited {completed.returncode}: {detail}"
            )

        try:
            parsed: object = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise DeepResearchInvocationError(
                "deep research command did not print a JSON document: "
                f"{completed.stdout.strip() or '(empty stdout)'}"
            ) from error

        if not isinstance(parsed, dict):
            raise DeepResearchInvocationError(
                "deep research command printed JSON that is not an object"
            )
        return parsed


def resolve_adapter(
    command: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> CliDeepResearchAdapter:
    """Return the configured adapter, or refuse by name when none is set."""
    source = os.environ if environ is None else environ
    configured = command if command is not None else source.get(COMMAND_ENV, "")
    if not configured.strip():
        raise DeepResearchNotConfigured(
            f"no deep research command configured; set {COMMAND_ENV} to the "
            "command that submits a ResearchRequest and prints a job as JSON"
        )
    return CliDeepResearchAdapter(command=configured)
