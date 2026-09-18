"""行业成员映射。

行业分类是校准报告的第 9 项证据（行业分布与集中度），也是 `astock calibrate
candidates --industry-map` 的输入。它必须可审计：目录从哪来、每只标的属于哪个
板块、以及当同一只标的落在多个板块时**拒绝**而不是挑一个。

fixture 是真机响应的逐字副本（`tests/fixtures/westock/sector_*.md`）：
目录来自 `sector ranking --kind industry`，成员来自 `sector constituent <代码>`。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astock_lens.cli.app import app
from astock_lens.data.industry import (
    IndustryCatalogEntry,
    IndustryMembership,
    IndustryMembershipAmbiguous,
    build_industry_map,
)
from astock_lens.data.normalize.industry import (
    IndustryConstituentError,
    normalize_constituents,
    parse_sector_catalog,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "westock"
AS_OF = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)

CATALOG_FIXTURE = FIXTURES / "sector_catalog_industry_head.md"
CONSTITUENT_FIXTURE = FIXTURES / "sector_constituent_pt01801783.md"


def _constituent_fixture() -> str:
    return CONSTITUENT_FIXTURE.read_text(encoding="utf-8")


def test_the_catalog_yields_stable_codes_and_names() -> None:
    entries = parse_sector_catalog(CATALOG_FIXTURE.read_text(encoding="utf-8"))

    assert isinstance(entries[0], IndustryCatalogEntry)
    assert entries[0].industry_id == "pt01801995"
    assert entries[0].industry_name == "电视广播Ⅱ"
    assert all(entry.industry_id.startswith("pt") for entry in entries)


def test_constituents_become_memberships_with_canonical_symbols() -> None:
    memberships = normalize_constituents(
        _constituent_fixture(),
        industry_id="pt01801783",
        industry_name="股份制银行Ⅱ",
        as_of=AS_OF,
        provider="westock-cli",
    )

    assert all(isinstance(item, IndustryMembership) for item in memberships)
    symbols = [item.symbol for item in memberships]
    assert "600015.SH" in symbols, "the CLI's sh600015 must become canonical"
    assert "000001.SZ" in symbols, "the CLI's sz000001 must become canonical"
    assert symbols == sorted(symbols), "the order must be deterministic"
    assert {item.industry_id for item in memberships} == {"pt01801783"}
    assert {item.industry_name for item in memberships} == {"股份制银行Ⅱ"}
    assert all(item.as_of == AS_OF for item in memberships)
    assert all(item.provider == "westock-cli" for item in memberships)


def test_a_constituent_table_for_another_industry_is_refused() -> None:
    """The title names the industry; a mismatch means the wrong answer arrived."""
    with pytest.raises(IndustryConstituentError, match="股份制银行"):
        normalize_constituents(
            _constituent_fixture(),
            industry_id="pt01801783",
            industry_name="饮料制造",
            as_of=AS_OF,
            provider="westock-cli",
        )


def test_an_unparseable_code_fails_loudly() -> None:
    broken = (
        "📈 申万二级行业成分股-股份制银行Ⅱ [申万二级行业] (1 只)\n"
        "| code | name |\n| --- | --- |\n| xx600015 | 华夏银行 |\n"
    )

    with pytest.raises(IndustryConstituentError, match="xx600015"):
        normalize_constituents(
            broken,
            industry_id="pt01801783",
            industry_name="股份制银行Ⅱ",
            as_of=AS_OF,
            provider="westock-cli",
        )


def test_repeated_rows_dedupe_deterministically() -> None:
    doubled = (
        "📈 申万二级行业成分股-股份制银行Ⅱ [申万二级行业] (2 只)\n"
        "| code | name |\n| --- | --- |\n"
        "| sz000001 | 平安银行 |\n| sh600015 | 华夏银行 |\n| sz000001 | 平安银行 |\n"
    )

    memberships = normalize_constituents(
        doubled,
        industry_id="pt01801783",
        industry_name="股份制银行Ⅱ",
        as_of=AS_OF,
        provider="westock-cli",
    )

    assert [item.symbol for item in memberships] == ["000001.SZ", "600015.SH"]


def _membership(symbol: str, industry_id: str, name: str) -> IndustryMembership:
    return IndustryMembership(
        symbol=symbol,
        industry_id=industry_id,
        industry_name=name,
        as_of=AS_OF,
        provider="westock-cli",
    )


def test_the_map_is_symbol_to_industry_and_point_in_time() -> None:
    stale = IndustryMembership(
        symbol="600519.SH",
        industry_id="pt01801724",
        industry_name="白酒Ⅱ",
        as_of=datetime(2026, 9, 19, 15, 0, tzinfo=UTC),
        provider="westock-cli",
    )
    memberships = [
        _membership("000001.SZ", "pt01801783", "股份制银行Ⅱ"),
        stale,
    ]

    mapping = build_industry_map(memberships, as_of=AS_OF)

    assert mapping == {"000001.SZ": "股份制银行Ⅱ"}, (
        "a membership dated after the as-of must not be visible"
    )


def test_two_industries_for_one_symbol_is_refused_not_resolved() -> None:
    """计划红线：没有明确主行业语义时不许"先到先得"。"""
    memberships = [
        _membership("000001.SZ", "pt01801783", "股份制银行Ⅱ"),
        _membership("000001.SZ", "pt01801999", "金融科技"),
    ]

    with pytest.raises(IndustryMembershipAmbiguous) as error:
        build_industry_map(memberships, as_of=AS_OF)

    assert "BLOCKED_PRIMARY_INDUSTRY_SEMANTICS" in str(error.value)
    assert "000001.SZ" in str(error.value)


def test_the_same_industry_twice_is_not_an_ambiguity() -> None:
    memberships = [
        _membership("000001.SZ", "pt01801783", "股份制银行Ⅱ"),
        _membership("000001.SZ", "pt01801783", "股份制银行Ⅱ"),
    ]

    assert build_industry_map(memberships, as_of=AS_OF) == {"000001.SZ": "股份制银行Ⅱ"}


def test_export_map_writes_exactly_symbol_and_industry(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """校准命令只认 `symbol,industry` 两列，多一列都会让它读错。"""
    csv_root = local_tmp / "csv"
    landing = csv_root / "westock" / "industry"
    landing.mkdir(parents=True)
    (landing / "2026-09-18.csv").write_text(
        "symbol,industry_id,industry_name,as_of,provider,source_ref\n"
        "600015.SH,pt01801783,股份制银行Ⅱ,2026-09-18T15:00:00+08:00,"
        "westock-cli,华夏银行\n"
        "000001.SZ,pt01801783,股份制银行Ⅱ,2026-09-18T15:00:00+08:00,"
        "westock-cli,平安银行\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(csv_root))
    output = local_tmp / "map.csv"

    result = CliRunner().invoke(
        app,
        [
            "industry",
            "export-map",
            "--as-of",
            "2026-09-18",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.read_text(encoding="utf-8").splitlines() == [
        "symbol,industry",
        "000001.SZ,股份制银行Ⅱ",
        "600015.SH,股份制银行Ⅱ",
    ]
