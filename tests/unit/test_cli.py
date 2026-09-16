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

# The short fixture carries 25 bars: enough for a 20-day window, not enough for
# the 60-day or 52-week momentum factors. The scan therefore runs against the
# long fixture, and the factor listing runs against the short one to keep its
# expected output small.
SHORT_DATASET = "daily_bars"
LONG_DATASET = "daily_bars_long"

SHORT_SYMBOLS = {"600000.SH", "000001.SZ", "600519.SH", "601398.SH"}
FACTOR_NAMES = {path.stem for path in (ROOT / "configs" / "factors").glob("*.yaml")}


def _invoke(local_tmp: Path, *args: str, dataset: str = SHORT_DATASET) -> Result:
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_CSV_ROOT": str(CSV_ROOT),
            "ASTOCK_SNAPSHOT_ROOT": str(local_tmp),
            "ASTOCK_DATASET": dataset,
        },
    )


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "scan" in result.stdout


def test_doctor_reports_the_factor_set_and_its_weights() -> None:
    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "factors:" in result.stdout
    assert "weights:" in result.stdout


def test_factors_compute_prints_one_document_per_symbol_and_factor(
    local_tmp: Path,
) -> None:
    result = _invoke(local_tmp, "factors", "compute", "--as-of", DAY)

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    payloads = [json.loads(line) for line in lines]

    assert {payload["symbol"] for payload in payloads} == SHORT_SYMBOLS
    assert {payload["factor"] for payload in payloads} == FACTOR_NAMES
    assert len(lines) == len(SHORT_SYMBOLS) * len(FACTOR_NAMES)


def test_scan_reports_ranked_candidates_and_writes_every_snapshot(
    local_tmp: Path,
) -> None:
    """The daily scan: 7 symbols survive the Universe, all carry scores."""
    result = _invoke(local_tmp, "scan", "--as-of", DAY, dataset=LONG_DATASET)

    assert result.exit_code == 0
    assert "candidates: 7" in result.stdout
    # Ranking top: fastest riser, scored, watched.
    assert "300750.SZ -> WATCH (score 95.24)" in result.stdout
    for kind in ("UNIVERSE", "FACTOR", "STRATEGY", "CANDIDATE"):
        assert (local_tmp / kind / "2026-09-04.json").is_file(), kind


def test_scan_reports_every_candidate_with_a_score(local_tmp: Path) -> None:
    """Cross-sectional scoring means every candidate line carries a number;
    a bare symbol with no score would mean the scan ranked nothing."""
    result = _invoke(local_tmp, "scan", "--as-of", DAY, dataset=LONG_DATASET)

    candidate_lines = [
        line
        for line in result.stdout.splitlines()
        if line.strip().startswith(("6", "0", "3", "8", "9"))
    ]
    assert candidate_lines
    assert all("score" in line for line in candidate_lines)


def test_universe_build_reports_the_verdicts_and_writes_the_snapshot(
    local_tmp: Path,
) -> None:
    result = _invoke(
        local_tmp, "universe", "build", "--as-of", DAY, dataset=LONG_DATASET
    )

    assert result.exit_code == 0
    assert "included: 7" in result.stdout
    assert "ST: 1" in result.stdout
    assert "LONG_SUSPENSION" in result.stdout
    assert (local_tmp / "UNIVERSE" / "2026-09-04.json").is_file()


def test_scan_rejects_a_malformed_date(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "scan", "--as-of", "not-a-date")

    assert result.exit_code != 0
    assert "YYYY-MM-DD" in result.output
