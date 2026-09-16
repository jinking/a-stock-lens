"""Deep research request and result records."""

from datetime import datetime

from astock_lens.domain.models import DomainRecord


class ResearchRequest(DomainRecord):
    """A standard research request handed to a deep research adapter."""

    symbol: str
    as_of: datetime
    thesis: str | None = None
    key_questions: tuple[str, ...] = ()
    risk_conditions: tuple[str, ...] = ()
    waiting_for: tuple[str, ...] = ()


class ResearchJob(DomainRecord):
    """A submitted research job."""

    job_id: str
    symbol: str
    submitted_at: datetime


class ResearchJobStatus(DomainRecord):
    """Observed status of a research job.

    `state` is passed through from the adapter unchanged: job states belong to
    `a-share-deep-research`, and A-Stock Lens must not invent a vocabulary for a
    system it only integrates with.
    """

    job_id: str
    state: str
    observed_at: datetime
    is_terminal: bool = False
    message: str | None = None


class ResearchSummary(DomainRecord):
    """Stored outcome of a research job.

    A-Stock Lens keeps only the summary and a reference to the artifact. The
    full report and its evidence stay owned by `a-share-deep-research`.
    """

    job_id: str
    symbol: str
    completed_at: datetime
    summary: str
    artifact_reference: str
