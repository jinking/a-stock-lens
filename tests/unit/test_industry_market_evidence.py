"""Industry market evidence unit tests.

Auditable industry evidence tests:
- Strict rejection when SW1 is requested but only SW2 exists (no relabeling);
- Strict fail-closed when benchmark or membership is missing;
- Exact calculation of industry 20d return and excess return.
"""

from datetime import UTC, datetime

import pytest

from astock_lens.data.industry import IndustryMembership
from astock_lens.market.industry import (
    IndustryEvidence,
    IndustryEvidenceUnavailable,
    build_industry_evidence,
)

AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def _membership(
    symbol: str,
    industry_id: str = "pt001",
    name: str = "股份制银行Ⅱ",
) -> IndustryMembership:
    return IndustryMembership(
        symbol=symbol,
        industry_id=industry_id,
        industry_name=name,
        as_of=AS_OF,
        provider="westock-cli",
    )


def test_sw1_requested_raises_industry_evidence_unavailable() -> None:
    # 规范来源仅有申万二级（SW2），请求 SW1 必须抛出 IndustryEvidenceUnavailable，绝不伪标
    membership = _membership("600036.SH")

    with pytest.raises(IndustryEvidenceUnavailable) as exc_info:
        build_industry_evidence(
            symbol="600036.SH",
            membership=membership,
            all_memberships=(membership,),
            member_returns_20d={"600036.SH": 0.05},
            benchmark_return_20d=0.02,
            requested_level="SW1",
            as_of=AS_OF,
        )

    assert "SW1 hierarchy unavailable" in str(exc_info.value)
    assert "SW2 is supported" in str(exc_info.value)


def test_exact_industry_excess_calculation() -> None:
    # 行业内 3 只标的，20d 收益率分别为 0.04, 0.06, 0.08 -> 行业均值 0.06
    # 基准 20d 收益率 = 0.02
    # 行业超额收益率 = 0.06 - 0.02 = 0.04
    m1 = _membership("600036.SH")
    m2 = _membership("601998.SH")
    m3 = _membership("600000.SH")

    evidence = build_industry_evidence(
        symbol="600036.SH",
        membership=m1,
        all_memberships=(m1, m2, m3),
        member_returns_20d={
            "600036.SH": 0.04,
            "601998.SH": 0.06,
            "600000.SH": 0.08,
        },
        benchmark_return_20d=0.02,
        requested_level="SW2",
        as_of=AS_OF,
    )

    assert isinstance(evidence, IndustryEvidence)
    assert evidence.symbol == "600036.SH"
    assert evidence.industry_id == "pt001"
    assert evidence.industry_level == "SW2"
    assert evidence.industry_return_20d == pytest.approx(0.06)
    assert evidence.benchmark_return_20d == pytest.approx(0.02)
    assert evidence.industry_excess_return_20d == pytest.approx(0.04)
    assert evidence.member_count == 3
    assert evidence.as_of == AS_OF


def test_missing_benchmark_raises_industry_evidence_unavailable() -> None:
    m = _membership("600036.SH")
    with pytest.raises(IndustryEvidenceUnavailable) as exc_info:
        build_industry_evidence(
            symbol="600036.SH",
            membership=m,
            all_memberships=(m,),
            member_returns_20d={"600036.SH": 0.05},
            benchmark_return_20d=None,
            requested_level="SW2",
            as_of=AS_OF,
        )

    assert "Benchmark return is missing" in str(exc_info.value)


def test_unmapped_symbol_raises_industry_evidence_unavailable() -> None:
    with pytest.raises(IndustryEvidenceUnavailable) as exc_info:
        build_industry_evidence(
            symbol="600036.SH",
            membership=None,
            all_memberships=(),
            member_returns_20d={},
            benchmark_return_20d=0.02,
            requested_level="SW2",
            as_of=AS_OF,
        )

    assert "No industry membership" in str(exc_info.value)


def test_no_valid_member_returns_raises_industry_evidence_unavailable() -> None:
    m = _membership("600036.SH")
    with pytest.raises(IndustryEvidenceUnavailable) as exc_info:
        build_industry_evidence(
            symbol="600036.SH",
            membership=m,
            all_memberships=(m,),
            member_returns_20d={},
            benchmark_return_20d=0.02,
            requested_level="SW2",
            as_of=AS_OF,
        )

    assert "No valid 20d returns found" in str(exc_info.value)
