"""Normalizing the securities master file.

Identity fields decide whether a symbol can be considered at all, so an
unreadable exchange, listing date, or board flag rejects the whole row instead
of yielding a profile with a guessed field. That is the same rule the daily-bar
normalizer applies to an unreadable symbol or trade date.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import (
    FetchRequest,
    NormalizedDataset,
    RawDataset,
    RawPayload,
)
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SecurityProfile

CSV_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)

SECURITY_COLUMNS = (
    "symbol",
    "name",
    "exchange",
    "list_date",
    "is_st",
    "is_delisting_board",
    "suspended_trading_days",
)

DEFAULTS = {
    "symbol": "600000.SH",
    "name": "浦发银行",
    "exchange": "SSE",
    "list_date": "1999-11-10",
    "is_st": "false",
    "is_delisting_board": "false",
    "suspended_trading_days": "0",
}


def _row(**overrides: str) -> list[str]:
    """A complete, valid row, with named cells replaced for one test."""
    cells = {**DEFAULTS, **overrides}
    return [cells[column] for column in SECURITY_COLUMNS]


def _raw(rows: list[list[str]]) -> RawDataset:
    """One raw securities payload, shaped exactly like the provider's."""
    return RawDataset(
        provider="test",
        dataset="securities",
        fetched_at=AS_OF,
        provider_version="v1",
        status=DataStatus.VALUE,
        row_count=len(rows),
        payload=RawPayload(
            columns=SECURITY_COLUMNS,
            rows=tuple(tuple(row) for row in rows),
        ),
    )


def _normalize(rows: list[list[str]]) -> NormalizedDataset:
    return CsvSecurityNormalizer().normalize(_raw(rows), as_of=AS_OF)


def _fixture_profiles() -> tuple[SecurityProfile, ...]:
    """The profiles produced from the committed securities fixture."""
    raw = LocalCsvProvider(CSV_ROOT).fetch(
        FetchRequest(dataset="securities", as_of=AS_OF)
    )
    return CsvSecurityNormalizer().normalize(raw, as_of=AS_OF).securities


def test_every_row_of_the_fixture_becomes_a_profile() -> None:
    profiles = _fixture_profiles()

    assert len(profiles) == 12
    assert len({profile.symbol for profile in profiles}) == 12


def test_flags_are_parsed_as_booleans() -> None:
    profiles = {profile.symbol: profile for profile in _fixture_profiles()}

    assert profiles["000002.SZ"].is_st is True
    assert profiles["600000.SH"].is_st is False
    assert profiles["000003.SZ"].is_delisting_board is True
    assert profiles["600000.SH"].is_delisting_board is False


def test_listing_date_and_suspension_count_are_typed() -> None:
    profiles = {profile.symbol: profile for profile in _fixture_profiles()}

    assert profiles["600000.SH"].list_date.isoformat() == "1999-11-10"
    assert profiles["000006.SZ"].suspended_trading_days == 400
    assert profiles["600000.SH"].suspended_trading_days == 0


REJECTED_ROW_CASES = (
    # test_an_unreadable_listing_date_rejects_the_row:
    #   A profile without an identity date cannot be aged, so it is not emitted.
    (
        "test_an_unreadable_listing_date_rejects_the_row",
        {"list_date": "not-a-date"},
        "list_date",
    ),
    # test_an_unreadable_flag_rejects_the_row:
    #   `is_st` absent means status unknown; that is not the same as "not ST".
    (
        "test_an_unreadable_flag_rejects_the_row",
        {"is_st": ""},
        "is_st",
    ),
    # test_a_missing_exchange_rejects_the_row
    (
        "test_a_missing_exchange_rejects_the_row",
        {"exchange": ""},
        "exchange",
    ),
    # test_an_unreadable_suspension_count_rejects_the_row
    (
        "test_an_unreadable_suspension_count_rejects_the_row",
        {"suspended_trading_days": "long ago"},
        "suspended_trading_days",
    ),
)


def test_unreadable_identity_cells_reject_the_row() -> None:
    """测试 4 类不可读身份字段各自整行被拒且点名列（原 4 条拒绝用例收表）。"""
    wrong = []
    for label, overrides, expected_column in REJECTED_ROW_CASES:
        normalized = _normalize([_row(**overrides)])
        if normalized.securities != ():
            wrong.append(f"{label}: 期望不产出 profile，实际 {normalized.securities!r}")
        columns = [failure.column for failure in normalized.parse_failures]
        if columns != [expected_column]:
            wrong.append(
                f"{label}: parse_failures 列得到 {columns!r}，"
                f"期望 [{expected_column!r}]"
            )
    assert not wrong, "不可读身份字段未按预期拒行:\n" + "\n".join(wrong)


def test_an_absent_suspension_count_is_missing_not_rejected() -> None:
    """A source that does not report suspension days yields `None`.

    Empty is an absence: it must not become 0 (a factual claim that the stock
    is trading), and it must not reject the row, because every identity field
    the row *does* carry is readable. Unreadable text still rejects — see the
    test above.
    """
    normalized = _normalize([_row(suspended_trading_days="")])

    assert len(normalized.securities) == 1
    assert normalized.securities[0].suspended_trading_days is None
    assert normalized.parse_failures == ()


def test_a_rejected_row_does_not_discard_its_neighbours() -> None:
    normalized = _normalize(
        [
            _row(symbol="600000.SH"),
            _row(symbol="000002.SZ", list_date="not-a-date"),
            _row(symbol="600519.SH"),
        ]
    )

    assert [profile.symbol for profile in normalized.securities] == [
        "600000.SH",
        "600519.SH",
    ]


def test_a_naive_as_of_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        CsvSecurityNormalizer().normalize(
            _raw([_row()]),
            as_of=datetime(2026, 9, 4, 15, 0),  # noqa: DTZ001
        )


def test_an_empty_payload_yields_no_profiles_and_no_failures() -> None:
    normalized = _normalize([])

    assert normalized.securities == ()
    assert normalized.parse_failures == ()
