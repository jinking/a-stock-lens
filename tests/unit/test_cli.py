"""CLI tests.

The rule these tests pin down: the CLI is a first-class surface. A scan can be
driven from cron or an agent with no Web UI, and it must fail loudly rather
than print a reassuring summary for a run that did nothing.
"""

import json
from pathlib import Path

from click.testing import Result
from typer.testing import CliRunner

from astock_lens.cli.app import app

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
DAY = "2026-09-04"


def _invoke(local_tmp: Path, *args: str) -> Result:
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_CSV_ROOT": str(CSV_ROOT),
            "ASTOCK_SNAPSHOT_ROOT": str(local_tmp),
        },
    )


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "scan" in result.stdout


def test_factors_compute_prints_one_document_per_symbol(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "factors", "compute", "--as-of", DAY)

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    assert len(lines) == 4
    payloads = [json.loads(line) for line in lines]
    assert {payload["symbol"] for payload in payloads} == {
        "600000.SH",
        "000001.SZ",
        "600519.SH",
        "601398.SH",
    }


def test_scan_reports_candidates_and_writes_a_snapshot(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "scan", "--as-of", DAY)

    assert result.exit_code == 0
    assert "candidates: 2" in result.stdout
    assert "600000.SH -> IGNORE" in result.stdout
    assert (local_tmp / "CANDIDATE" / "2026-09-04.json").is_file()


def test_scan_rejects_a_malformed_date(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "scan", "--as-of", "not-a-date")

    assert result.exit_code != 0
    assert "YYYY-MM-DD" in result.output
