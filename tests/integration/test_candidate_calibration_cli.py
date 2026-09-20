"""Integration tests for the candidate calibration CLI command.

Pins down:
- The command executes canonical non-persistent analysis chain;
- Generates deterministic JSON and Markdown reports with the calibration warning;
- Guarantees zero production mutation across snapshot, watchlist, and job roots;
- Fails loudly on invalid or corrupt industry maps.
"""

from pathlib import Path

from typer.testing import CliRunner

from astock_lens.calibration.candidate_report import CALIBRATION_WARNING
from astock_lens.cli.app import app

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
DAY = "2026-09-04"
LONG_DATASET = "daily_bars_long"

SYMBOLS = [
    "600000.SH",
    "000001.SZ",
    "600519.SH",
    "601398.SH",
    "300750.SZ",
    "002594.SZ",
    "601899.SH",
]


def _write_industry_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    content = "symbol,industry\n" + "\n".join(f"{s},{i}" for s, i in rows) + "\n"
    path.write_text(content, encoding="utf-8")


def test_calibrate_cli_help() -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["calibrate", "--help"])
    assert res.exit_code == 0
    assert "candidates" in res.stdout

    res2 = runner.invoke(app, ["calibrate", "candidates", "--help"])
    assert res2.exit_code == 0
    assert "--as-of" in res2.stdout
    assert "--industry-map" in res2.stdout
    assert "--output-dir" in res2.stdout


def test_calibrate_candidates_generates_reports_without_production_mutation(
    tmp_path: Path,
) -> None:
    # 1. Arrange sentinels in production-like directories
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    output_dir = tmp_path / "calibration_out"

    snapshot_root.mkdir(parents=True)
    watchlist_root.mkdir(parents=True)
    job_root.mkdir(parents=True)

    snapshot_sentinel = snapshot_root / "SENTINEL.txt"
    snapshot_sentinel.write_text("snapshot untouched", encoding="utf-8")
    watchlist_sentinel = watchlist_root / "SENTINEL.txt"
    watchlist_sentinel.write_text("watchlist untouched", encoding="utf-8")
    job_sentinel = job_root / "SENTINEL.txt"
    job_sentinel.write_text("job untouched", encoding="utf-8")

    # 2. Arrange valid industry mapping
    industry_csv = tmp_path / "industry.csv"
    _write_industry_csv(
        industry_csv,
        [
            ("600000.SH", "银行"),
            ("000001.SZ", "银行"),
            ("600519.SH", "饮料"),
            ("601398.SH", "银行"),
            ("300750.SZ", "电力设备"),
            ("002594.SZ", "汽车"),
            ("601899.SH", "有色金属"),
        ],
    )

    # 3. Act: invoke CLI
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "candidates",
            "--as-of",
            DAY,
            "--industry-map",
            str(industry_csv),
            "--output-dir",
            str(output_dir),
        ],
        env={
            "ASTOCK_CSV_ROOT": str(CSV_ROOT),
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_WATCHLIST_ROOT": str(watchlist_root),
            "ASTOCK_JOB_ROOT": str(job_root),
            "ASTOCK_DATASET": LONG_DATASET,
        },
    )

    assert result.exit_code == 0, result.output
    assert "Calibration report written" in result.stdout

    # 4. Assert: output artifacts created
    json_path = output_dir / f"{DAY}-candidate-calibration.json"
    md_path = output_dir / f"{DAY}-candidate-calibration.md"
    assert json_path.is_file()
    assert md_path.is_file()

    json_content = json_path.read_text(encoding="utf-8")
    md_content = md_path.read_text(encoding="utf-8")
    assert CALIBRATION_WARNING in json_content
    assert CALIBRATION_WARNING in md_content

    # 5. Assert: production sentinels untouched and no new files in production roots
    assert list(snapshot_root.iterdir()) == [snapshot_sentinel]
    assert list(watchlist_root.iterdir()) == [watchlist_sentinel]
    assert list(job_root.iterdir()) == [job_sentinel]
    assert snapshot_sentinel.read_text(encoding="utf-8") == "snapshot untouched"
    assert watchlist_sentinel.read_text(encoding="utf-8") == "watchlist untouched"
    assert job_sentinel.read_text(encoding="utf-8") == "job untouched"


def test_calibrate_candidates_fails_on_missing_industry_file(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "candidates",
            "--as-of",
            DAY,
            "--industry-map",
            str(tmp_path / "nonexistent.csv"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        env={"ASTOCK_CSV_ROOT": str(CSV_ROOT)},
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_calibrate_candidates_fails_on_duplicate_symbol_in_industry_csv(
    tmp_path: Path,
) -> None:
    industry_csv = tmp_path / "duplicate_industry.csv"
    _write_industry_csv(
        industry_csv,
        [
            ("600000.SH", "银行"),
            ("600000.SH", "非银金融"),
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "candidates",
            "--as-of",
            DAY,
            "--industry-map",
            str(industry_csv),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        env={"ASTOCK_CSV_ROOT": str(CSV_ROOT)},
    )
    assert result.exit_code != 0
    assert "duplicate symbol" in result.output.lower()


def test_calibrate_candidates_fails_on_missing_header_in_industry_csv(
    tmp_path: Path,
) -> None:
    industry_csv = tmp_path / "bad_header.csv"
    industry_csv.write_text("code,sector\n600000.SH,银行\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "candidates",
            "--as-of",
            DAY,
            "--industry-map",
            str(industry_csv),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        env={"ASTOCK_CSV_ROOT": str(CSV_ROOT)},
    )
    assert result.exit_code != 0
    assert "columns" in result.output.lower()


def test_calibrate_candidates_canonical_merges_supplement(tmp_path: Path) -> None:
    import json
    import shutil

    # 1. Arrange csv root with securities and bars from fixtures
    csv_root = tmp_path / "csv"
    csv_root.mkdir(parents=True)
    shutil.copy(CSV_ROOT / "securities.csv", csv_root / "securities.csv")
    shutil.copy(CSV_ROOT / "daily_bars_long.csv", csv_root / "daily_bars_long.csv")

    # 2. Canonical industry file has 5 of the 6 universe symbols (missing 900948.SH)
    industry_dir = csv_root / "westock" / "industry"
    industry_dir.mkdir(parents=True)
    canonical_csv = industry_dir / f"{DAY}.csv"
    canonical_csv.write_text(
        "symbol,industry_id,industry_name,as_of,provider,source_ref\n"
        "600000.SH,pt01,银行,2026-09-04T15:00:00+08:00,westock-cli,\n"
        "000001.SZ,pt01,银行,2026-09-04T15:00:00+08:00,westock-cli,\n"
        "600519.SH,pt02,饮料,2026-09-04T15:00:00+08:00,westock-cli,\n"
        "300750.SZ,pt03,电力设备,2026-09-04T15:00:00+08:00,westock-cli,\n"
        "000006.SZ,pt04,房地产,2026-09-04T15:00:00+08:00,westock-cli,\n",
        encoding="utf-8",
    )

    # 3. Supplemental config supplies 900948.SH
    supplement_yaml = tmp_path / "supplement.yaml"
    supplement_yaml.write_text(
        "supplements:\n"
        "  - symbol: 900948.SH\n"
        "    industry_id: sw2_coal\n"
        "    industry_name: 煤炭开采\n"
        "    provider: sws-official\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "candidates",
            "--as-of",
            DAY,
            "--output-dir",
            str(output_dir),
        ],
        env={
            "ASTOCK_CSV_ROOT": str(csv_root),
            "ASTOCK_DATASET": LONG_DATASET,
            "ASTOCK_INDUSTRY_SUPPLEMENT_PATH": str(supplement_yaml),
        },
    )
    assert result.exit_code == 0, result.output
    report = json.loads(
        (output_dir / f"{DAY}-candidate-calibration.json").read_text(encoding="utf-8")
    )
    assert report["industry_evidence"]["origin"] == "canonical"
    assert report["industry_coverage"]["ratio"] == 1.0
    assert len(report["industry_coverage"]["missing_symbols"]) == 0
    assert (
        report["industry_coverage"]["known_count"]
        == report["industry_coverage"]["total_count"]
    )
