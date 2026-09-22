"""Tests for deterministic production industry loader (Task 4)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.cli.app import _latest_industry_file, _production_industry_map
from astock_lens.data.industry import IndustryMembershipAmbiguous


def _write_industry_csv(
    dir_path: Path, filename: str, rows: list[tuple[str, str, str, str]]
) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / filename
    lines = ["symbol,industry_id,industry_name,as_of,provider,source_ref\n"]
    for sym, ind_id, ind_name, as_of_str in rows:
        lines.append(f"{sym},{ind_id},{ind_name},{as_of_str},westock-cli,\n")
    file_path.write_text("".join(lines), encoding="utf-8")
    return file_path


def test_step1_exact_date(tmp_path: Path) -> None:
    """Step 1: When an exact-date industry file exists, it must be selected."""
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-09-01.csv",
        [("000001.SZ", "sw2_bank", "银行", "2026-09-01T15:00:00+00:00")],
    )
    _write_industry_csv(
        industry_dir,
        "2026-09-02.csv",
        [
            ("000001.SZ", "sw2_bank", "银行", "2026-09-02T15:00:00+00:00"),
            ("000002.SZ", "sw2_realestate", "房地产", "2026-09-02T15:00:00+00:00"),
        ],
    )

    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    selected = _latest_industry_file(day, root=tmp_path)
    assert selected == industry_dir / "2026-09-02.csv"

    mapping = _production_industry_map(day, root=tmp_path)
    assert mapping["000001.SZ"] == "银行"
    assert mapping["000002.SZ"] == "房地产"


def test_step2_latest_prior_date(tmp_path: Path) -> None:
    """Step 2: When no exact-date file exists, latest prior date must be chosen."""
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-08-30.csv",
        [("000001.SZ", "sw2_bank", "银行", "2026-08-30T15:00:00+00:00")],
    )
    _write_industry_csv(
        industry_dir,
        "2026-09-01.csv",
        [
            ("000001.SZ", "sw2_bank", "银行", "2026-09-01T15:00:00+00:00"),
            ("600519.SH", "sw2_liquor", "白酒", "2026-09-01T15:00:00+00:00"),
        ],
    )

    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    selected = _latest_industry_file(day, root=tmp_path)
    assert selected == industry_dir / "2026-09-01.csv"

    mapping = _production_industry_map(day, root=tmp_path)
    assert mapping["000001.SZ"] == "银行"
    assert mapping["600519.SH"] == "白酒"


def test_step3_future_date_exclusion(tmp_path: Path) -> None:
    """Step 3: Files dated after target as_of date must be strictly excluded."""
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-09-01.csv",
        [("000001.SZ", "sw2_bank", "银行", "2026-09-01T15:00:00+00:00")],
    )
    _write_industry_csv(
        industry_dir,
        "2026-09-03.csv",
        [("000001.SZ", "sw2_bank", "银行新版", "2026-09-03T15:00:00+00:00")],
    )

    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    selected = _latest_industry_file(day, root=tmp_path)
    assert selected == industry_dir / "2026-09-01.csv"


def test_step4_no_data_raises_file_not_found(tmp_path: Path) -> None:
    """Step 4: When no eligible files exist, FileNotFoundError must be raised."""
    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

    # Empty directory
    with pytest.raises(
        FileNotFoundError,
        match="No eligible industry file found in .* for date 2026-09-02",
    ):
        _latest_industry_file(day, root=tmp_path)

    # Directory with only future files
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-09-05.csv",
        [("000001.SZ", "sw2_bank", "银行", "2026-09-05T15:00:00+00:00")],
    )
    with pytest.raises(
        FileNotFoundError,
        match="No eligible industry file found in .* for date 2026-09-02",
    ):
        _latest_industry_file(day, root=tmp_path)

    with pytest.raises(
        FileNotFoundError,
        match="No eligible industry file found in .* for date 2026-09-02",
    ):
        _production_industry_map(day, root=tmp_path)


def test_ambiguous_membership_fails_closed(tmp_path: Path) -> None:
    """Step 5: Ambiguous membership (same symbol in different industries) raises IndustryMembershipAmbiguous."""
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-09-02.csv",
        [
            ("000001.SZ", "sw2_bank", "银行", "2026-09-02T15:00:00+00:00"),
            ("000001.SZ", "sw2_realestate", "房地产", "2026-09-02T15:00:00+00:00"),
        ],
    )

    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    with pytest.raises(IndustryMembershipAmbiguous):
        _production_industry_map(day, root=tmp_path)


def test_ignores_non_iso_date_csv(tmp_path: Path) -> None:
    """Non-ISO-date CSV files (e.g. metadata.csv) are ignored safely."""
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-09-01.csv",
        [("000001.SZ", "sw2_bank", "银行", "2026-09-01T15:00:00+00:00")],
    )
    (industry_dir / "latest.csv").write_text("dummy", encoding="utf-8")
    (industry_dir / "README.md").write_text("docs", encoding="utf-8")

    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    selected = _latest_industry_file(day, root=tmp_path)
    assert selected == industry_dir / "2026-09-01.csv"


def test_includes_supplemental_industry_memberships(tmp_path: Path) -> None:
    """Step 5: Supplements from configuration are loaded and merged."""
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-09-02.csv",
        [("000001.SZ", "sw2_bank", "银行", "2026-09-02T15:00:00+00:00")],
    )

    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    mapping = _production_industry_map(day, root=tmp_path)
    assert mapping["000001.SZ"] == "银行"
    # 000592.SZ is defined in configs/industry_supplement.yaml as 林业Ⅱ
    assert mapping.get("000592.SZ") == "林业Ⅱ"
