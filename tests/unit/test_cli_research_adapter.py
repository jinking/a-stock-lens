"""CLI deep research adapter tests.

`spec §14` keeps `a-share-deep-research` behind an adapter, and
`ARCHITECTURE.md` §13.2 forbids the Python-level dependency. The rule that
matters here is that the boundary is honest: job states are passed through
unchanged because they belong to the other system, and a command that fails
produces an error — never a fabricated job, status or summary.
"""

import shlex
import sys
from datetime import UTC, datetime

import pytest

from astock_lens.research.adapters.cli import (
    COMMAND_ENV,
    CliDeepResearchAdapter,
    DeepResearchInvocationError,
    DeepResearchNotConfigured,
    resolve_adapter,
)
from astock_lens.research.models import ResearchJob, ResearchJobStatus, ResearchSummary

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)

RESPONDER = """
import json, sys

payload = json.load(sys.stdin)
action = payload["action"]

if action == "submit":
    print(json.dumps({
        "job_id": "job-1",
        "symbol": payload["request"]["symbol"],
        "submitted_at": "2026-09-04T15:05:00+00:00",
    }))
elif action == "status":
    print(json.dumps({
        "job_id": payload["job_id"],
        "state": "InProgress",
        "observed_at": "2026-09-04T15:06:00+00:00",
        "is_terminal": False,
    }))
else:
    print(json.dumps({
        "job_id": payload["job_id"],
        "symbol": "600519.SH",
        "completed_at": "2026-09-04T16:00:00+00:00",
        "summary": "channel inventory still rebuilding",
        "artifact_reference": "reports/600519.SH.md",
    }))
"""


def _command(script: str) -> str:
    return shlex.join([sys.executable, "-c", script])


def _adapter(script: str = RESPONDER) -> CliDeepResearchAdapter:
    return CliDeepResearchAdapter(command=_command(script))


def test_submit_returns_the_job_the_command_reported() -> None:
    from astock_lens.research.models import ResearchRequest

    job = _adapter().submit(ResearchRequest(symbol="600519.SH", as_of=AS_OF))

    assert isinstance(job, ResearchJob)
    assert job.job_id == "job-1"
    assert job.symbol == "600519.SH"
    assert job.submitted_at == datetime(2026, 9, 4, 15, 5, tzinfo=UTC)


def test_the_request_travels_to_the_command_unchanged() -> None:
    echo = _command(
        "import json,sys;"
        "p=json.load(sys.stdin);"
        "r=p['request'];"
        "print(json.dumps({'job_id': r['thesis'], 'symbol': r['symbol'],"
        " 'submitted_at': '2026-09-04T15:05:00+00:00'}))"
    )
    from astock_lens.research.models import ResearchRequest

    job = CliDeepResearchAdapter(command=echo).submit(
        ResearchRequest(symbol="600519.SH", as_of=AS_OF, thesis="brand moat")
    )

    assert job.job_id == "brand moat"


def test_status_passes_the_state_through_unchanged() -> None:
    status = _adapter().status("job-1")

    assert isinstance(status, ResearchJobStatus)
    # `InProgress` is the other system's vocabulary, not ours to rename.
    assert status.state == "InProgress"
    assert status.is_terminal is False
    assert status.job_id == "job-1"


def test_result_returns_the_summary_and_the_artifact_reference() -> None:
    summary = _adapter().result("job-1")

    assert isinstance(summary, ResearchSummary)
    assert summary.summary == "channel inventory still rebuilding"
    assert summary.artifact_reference == "reports/600519.SH.md"
    assert summary.completed_at == datetime(2026, 9, 4, 16, 0, tzinfo=UTC)


def test_an_unconfigured_command_is_refused_by_name() -> None:
    with pytest.raises(DeepResearchNotConfigured):
        CliDeepResearchAdapter(command="")

    with pytest.raises(DeepResearchNotConfigured):
        resolve_adapter(None, environ={})


def test_the_command_is_read_from_the_environment() -> None:
    adapter = resolve_adapter(None, environ={COMMAND_ENV: _command(RESPONDER)})

    assert adapter.status("job-1").state == "InProgress"


def test_a_failing_command_reports_the_failure_instead_of_a_result() -> None:
    failing = _command("import sys; sys.stderr.write('no token'); sys.exit(3)")

    with pytest.raises(DeepResearchInvocationError) as raised:
        CliDeepResearchAdapter(command=failing).status("job-1")

    assert "3" in str(raised.value)
    assert "no token" in str(raised.value)


def test_unreadable_output_is_refused_instead_of_guessed() -> None:
    noisy = _command("print('not json at all')")

    with pytest.raises(DeepResearchInvocationError, match="JSON"):
        CliDeepResearchAdapter(command=noisy).status("job-1")


def test_an_incomplete_payload_is_refused() -> None:
    partial = _command("import json; print(json.dumps({'job_id': 'job-1'}))")

    with pytest.raises(Exception, match="state"):
        CliDeepResearchAdapter(command=partial).status("job-1")
