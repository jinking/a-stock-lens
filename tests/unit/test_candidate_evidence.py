"""CandidateEvidence 与 CandidateSelection 领域模型测试。"""

import re
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.policy import CandidateEvidence, CandidateSelection
from astock_lens.domain.enums import MarketValidation, NextAction, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _qualification(
    symbol: str,
    strategy_id: str = "value",
    *,
    qualified: bool = True,
    percentile: float = 0.95,
    version: str = "qual-v1",
) -> StrategyQualification:
    return StrategyQualification(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version=version,
        qualified=qualified,
        percentile_pass=percentile >= 0.90,
        absolute_pass=qualified,
        rank_percentile=percentile,
    )


def _result(
    symbol: str,
    strategy_id: str = "value",
    score: float = 80.0,
    percentile: float = 0.95,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
        rank_percentile=percentile,
    )


def test_candidate_evidence_valid_construction() -> None:
    ev = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(_result("600000.SH"),),
        strategy_qualifications=(_qualification("600000.SH"),),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    assert ev.symbol == "600000.SH"
    assert len(ev.strategy_results) == 1
    assert len(ev.strategy_qualifications) == 1
    assert ev.market_validation == MarketValidation.CONFIRMED
    assert ev.signal == Signal.NO_SIGNAL


# 「非法构造必须被拒」三行：行序与原用例一致，label 即原测试名；
# 列 = label, payload, expected：
#   - `payload` 逐行保留原 `CandidateEvidence(...)` 的关键字参数；
#   - `expected` 逐字取自原 `pytest.raises(..., match=...)` 的消息片段，
#     比对方式与原断言同为 `re.search`。
CANDIDATE_EVIDENCE_REJECTION_CASES = (
    # test_candidate_evidence_rejects_mismatched_result_symbol
    (
        "test_candidate_evidence_rejects_mismatched_result_symbol",
        {
            "symbol": "600000.SH",
            "strategy_results": (_result("600001.SH"),),
            "strategy_qualifications": (_qualification("600000.SH"),),
            "market_validation": MarketValidation.CONFIRMED,
            "signal": Signal.NO_SIGNAL,
        },
        "symbol",
    ),
    # test_candidate_evidence_rejects_mismatched_qualification_symbol
    (
        "test_candidate_evidence_rejects_mismatched_qualification_symbol",
        {
            "symbol": "600000.SH",
            "strategy_results": (_result("600000.SH"),),
            "strategy_qualifications": (_qualification("600001.SH"),),
            "market_validation": MarketValidation.CONFIRMED,
            "signal": Signal.NO_SIGNAL,
        },
        "symbol",
    ),
    # test_candidate_evidence_requires_at_least_one_qualified_qualification
    (
        "test_candidate_evidence_requires_at_least_one_qualified_qualification",
        {
            "symbol": "600000.SH",
            "strategy_results": (_result("600000.SH"),),
            "strategy_qualifications": (_qualification("600000.SH", qualified=False),),
            "market_validation": MarketValidation.CONFIRMED,
            "signal": Signal.NO_SIGNAL,
        },
        "qualified",
    ),
)


def test_candidate_evidence_rejects_invalid_constructions() -> None:
    """三种非法构造各自以 ValueError 拒绝，消息须匹配原 `match=` 片段。

    原 3 条「rejects / requires」用例逐条成行；循环只收集，断言在表外一次完成，
    失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, payload, expected in CANDIDATE_EVIDENCE_REJECTION_CASES:
        try:
            CandidateEvidence(**payload)
        except ValueError as exc:
            if re.search(expected, str(exc)) is None:
                wrong.append(
                    f"{label}: 错误消息中找不到 {expected!r}，实际 {str(exc)!r}"
                )
        else:
            wrong.append(f"{label}: 未抛出 ValueError")
    assert not wrong, "CandidateEvidence 未拒绝非法构造:\n" + "\n".join(wrong)


def test_candidate_evidence_allows_none_for_market_and_signal_representation() -> None:
    ev = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(_result("600000.SH"),),
        strategy_qualifications=(_qualification("600000.SH"),),
        market_validation=None,
        signal=None,
    )
    assert ev.market_validation is None
    assert ev.signal is None


def test_candidate_selection_immutability_and_fields() -> None:
    sel = CandidateSelection(
        symbol="600000.SH",
        policy_version="v1",
        reasons=("value top 5%",),
    )
    assert sel.symbol == "600000.SH"
    assert sel.policy_version == "v1"
    assert sel.reasons == ("value top 5%",)
    with pytest.raises(ValidationError):
        sel.symbol = "600001.SH"  # type: ignore[misc]


def test_candidate_builder_assembles_from_selection_and_evidence() -> None:
    sym = "600000.SH"
    res_val = _result(sym, strategy_id="value", percentile=0.98)
    res_gro = _result(sym, strategy_id="growth", percentile=0.85)  # not qualified
    q_val = _qualification(
        sym, strategy_id="value", qualified=True, percentile=0.98, version="qual-val-1"
    )
    q_gro = _qualification(
        sym,
        strategy_id="growth",
        qualified=False,
        percentile=0.85,
        version="qual-gro-1",
    )

    ev = CandidateEvidence(
        symbol=sym,
        strategy_results=(res_val, res_gro),
        strategy_qualifications=(q_val, q_gro),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    sel = CandidateSelection(
        symbol=sym,
        policy_version="policy-v1",
        reasons=("selected by representative policy",),
    )
    lineage = SnapshotLineage(
        universe_snapshot="2026-09-04:abc",
        factor_version="f1",
        strategy_version="v1",
    )

    candidate = CandidateBuilder().build(
        evidence=ev,
        selection=sel,
        as_of=AS_OF,
        lineage=lineage,
    )

    assert candidate.symbol == sym
    assert candidate.next_action is NextAction.WATCH
    assert candidate.candidate_policy_version == "policy-v1"
    assert candidate.market_validation == MarketValidation.CONFIRMED
    assert candidate.signal == Signal.NO_SIGNAL
    # Only retains qualified strategy results and qualifications
    assert len(candidate.strategy_results) == 1
    assert candidate.strategy_results[0].strategy_id == "value"
    assert len(candidate.strategy_qualifications) == 1
    assert candidate.strategy_qualifications[0].strategy_id == "value"
    # Lineage carries qualification_version and candidate_policy_version
    assert candidate.lineage.qualification_version == "qual-val-1"
    assert candidate.lineage.candidate_policy_version == "policy-v1"


def test_candidate_builder_rejects_symbol_mismatch() -> None:
    ev = CandidateEvidence(
        symbol="600000.SH",
        strategy_results=(_result("600000.SH"),),
        strategy_qualifications=(_qualification("600000.SH"),),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.NO_SIGNAL,
    )
    sel = CandidateSelection(symbol="600001.SH", policy_version="v1")
    with pytest.raises(ValueError, match="Symbol mismatch"):
        CandidateBuilder().build(
            evidence=ev,
            selection=sel,
            as_of=AS_OF,
            lineage=SnapshotLineage(),
        )
