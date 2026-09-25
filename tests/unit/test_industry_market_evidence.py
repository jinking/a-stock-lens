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


def _sw1_requested_kwargs() -> dict[str, object]:
    """第 1 行的输入：请求 SW1；原用例的 `membership = _membership(...)` 逐字保留。"""
    membership = _membership("600036.SH")
    return {
        "symbol": "600036.SH",
        "membership": membership,
        "all_memberships": (membership,),
        "member_returns_20d": {"600036.SH": 0.05},
        "benchmark_return_20d": 0.02,
        "requested_level": "SW1",
        "as_of": AS_OF,
    }


def _missing_benchmark_kwargs() -> dict[str, object]:
    """第 2 行的输入：基准收益率缺失；原用例的 `m = _membership(...)` 逐字保留。"""
    m = _membership("600036.SH")
    return {
        "symbol": "600036.SH",
        "membership": m,
        "all_memberships": (m,),
        "member_returns_20d": {"600036.SH": 0.05},
        "benchmark_return_20d": None,
        "requested_level": "SW2",
        "as_of": AS_OF,
    }


def _unmapped_symbol_kwargs() -> dict[str, object]:
    """第 3 行的输入：标的不在行业成员表内。"""
    return {
        "symbol": "600036.SH",
        "membership": None,
        "all_memberships": (),
        "member_returns_20d": {},
        "benchmark_return_20d": 0.02,
        "requested_level": "SW2",
        "as_of": AS_OF,
    }


def _no_valid_member_returns_kwargs() -> dict[str, object]:
    """第 4 行的输入：成员表非空但没有有效的 20d 收益。"""
    m = _membership("600036.SH")
    return {
        "symbol": "600036.SH",
        "membership": m,
        "all_memberships": (m,),
        "member_returns_20d": {},
        "benchmark_return_20d": 0.02,
        "requested_level": "SW2",
        "as_of": AS_OF,
    }


# 「行业证据必须显式失败」四行：行序与原用例一致，label 即原测试名；
# 列 = label, payload, expected_fragments：
#   - `payload` 为零参可调用，返回 `build_industry_evidence` 的关键字参数
#     （原用例的就地绑定原样保留在对应函数体内）；
#   - `expected_fragments` 逐字取自原 `assert "<片段>" in str(exc_info.value)`，
#     比对方式同为 `in`。
INDUSTRY_EVIDENCE_REJECTION_CASES = (
    # test_sw1_requested_raises_industry_evidence_unavailable:
    #   规范来源仅有申万二级（SW2），请求 SW1 必须抛出 IndustryEvidenceUnavailable，绝不伪标
    (
        "test_sw1_requested_raises_industry_evidence_unavailable",
        _sw1_requested_kwargs,
        ("SW1 hierarchy unavailable", "SW2 is supported"),
    ),
    # test_missing_benchmark_raises_industry_evidence_unavailable
    (
        "test_missing_benchmark_raises_industry_evidence_unavailable",
        _missing_benchmark_kwargs,
        ("Benchmark return is missing",),
    ),
    # test_unmapped_symbol_raises_industry_evidence_unavailable
    (
        "test_unmapped_symbol_raises_industry_evidence_unavailable",
        _unmapped_symbol_kwargs,
        ("No industry membership",),
    ),
    # test_no_valid_member_returns_raises_industry_evidence_unavailable
    (
        "test_no_valid_member_returns_raises_industry_evidence_unavailable",
        _no_valid_member_returns_kwargs,
        ("No valid 20d returns found",),
    ),
)


def test_industry_evidence_unavailable_rejections() -> None:
    """四种缺失/越级请求各自抛出 IndustryEvidenceUnavailable，消息点名原因。

    原 4 条「raises_industry_evidence_unavailable」用例逐条成行；循环只收集，
    断言在表外一次完成，失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, payload, expected_fragments in INDUSTRY_EVIDENCE_REJECTION_CASES:
        arguments = payload()
        try:
            build_industry_evidence(**arguments)
        except IndustryEvidenceUnavailable as exc:
            message = str(exc)
            for fragment in expected_fragments:
                if fragment not in message:
                    wrong.append(
                        f"{label}: 错误信息缺少 {fragment!r}，实际 {message!r}"
                    )
        else:
            wrong.append(f"{label}: 未抛出 IndustryEvidenceUnavailable")
    assert not wrong, "行业证据未显式失败:\n" + "\n".join(wrong)


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
