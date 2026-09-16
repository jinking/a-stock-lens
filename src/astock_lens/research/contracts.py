"""Deep research adapter contract.

The adapter is a typed boundary. `a-share-deep-research` is never imported as a
Python dependency and remains a separate repository.
"""

from typing import Protocol

from astock_lens.research.models import (
    ResearchJob,
    ResearchJobStatus,
    ResearchRequest,
    ResearchSummary,
)


class DeepResearchAdapter(Protocol):
    """Integration boundary for deep company research."""

    def submit(self, request: ResearchRequest) -> ResearchJob:
        """Submit a research request and return the created job."""
        ...

    def status(self, job_id: str) -> ResearchJobStatus:
        """Report the current status of a submitted job."""
        ...

    def result(self, job_id: str) -> ResearchSummary:
        """Return the stored summary for a finished job.

        The adapter never fabricates a success result for an unfinished job.
        """
        ...
