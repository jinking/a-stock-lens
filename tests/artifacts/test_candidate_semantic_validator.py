"""Independent candidate semantic validator tests.

Pins the 5 new independent validation checks from spec §20.2 / Plan A Task 7:
1. primary_strategy_id exists and matches top qualified strategy (wrong-primary must fail).
2. Signal strategy_id matches primary_strategy_id (mismatch must fail).
3. Market Validation strategy_id matches primary_strategy_id (mismatch must fail).
4. Candidate lineage must carry complete versions (regime, market_validation, signal, etc.).
5. Valid candidate passes with 0 findings.

Contracts:
- Must NOT import production code (not astock_lens, not pydantic models).
"""

from datetime import UTC, datetime

from artifacts.validator import (
    validate_snapshot,
)

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _candidate_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "symbol": "600000.SH",
        "as_of": AS_OF.isoformat(),
        "next_action": "WATCH",
        "primary_strategy_id": "momentum",
        "candidate_policy_version": "v1",
        "strategy_qualifications": [
            {
                "symbol": "600000.SH",
                "strategy_id": "momentum",
                "qualified": True,
                "rank_percentile": 0.98,
                "percentile_floor": 0.90,
                "as_of": AS_OF.isoformat(),
                "lineage": {"qualification_version": "v1"},
            },
            {
                "symbol": "600000.SH",
                "strategy_id": "value",
                "qualified": True,
                "rank_percentile": 0.92,
                "percentile_floor": 0.90,
                "as_of": AS_OF.isoformat(),
                "lineage": {"qualification_version": "v1"},
            },
        ],
        "strategy_results": [
            {
                "symbol": "600000.SH",
                "strategy_id": "momentum",
                "strategy_version": "v1",
                "as_of": AS_OF.isoformat(),
                "score": 95.0,
                "rank_percentile": 0.98,
                "lineage": {"strategy_version": "v1"},
            },
            {
                "symbol": "600000.SH",
                "strategy_id": "value",
                "strategy_version": "v1",
                "as_of": AS_OF.isoformat(),
                "score": 88.0,
                "rank_percentile": 0.92,
                "lineage": {"strategy_version": "v1"},
            },
        ],
        "market_validation": "CONFIRMED",
        "signal": "BREAKOUT",
        "market_validation_strategy_id": "momentum",
        "signal_strategy_id": "momentum",
        "lineage": {
            "universe_snapshot": "2026-09-04:abc",
            "factor_version": "v1",
            "strategy_version": "v1",
            "qualification_version": "v1",
            "candidate_policy_version": "v1",
            "regime_version": "v1",
            "market_validation_version": "v1",
            "signal_version": "v1",
        },
    }
    record.update(overrides)
    return record


# 八行「坏记录必须命中指定 check」：行序与原用例一致，label 即原测试名，
# 原 docstring 逐字保留为行注释；第 4 行（缺血缘版本）另带 observed 片段列。
# 列 = label, overrides, expected_check, expected_observed：
#   - `overrides` 逐字取自原 `_candidate_record(**overrides)` 调用；
#   - `expected_observed=None` 表示该行原本不断言 observed（不新增断言），
#     非 None 时比对方式与原断言同为逐片段 `in`。
CANDIDATE_CHECK_CASES: tuple[
    tuple[str, dict[str, object], str, tuple[str, ...] | None], ...
] = (
    # test_wrong_primary_strategy_artifact_fails:
    #   Step 1: 当 primary_strategy_id 与最高分位合格策略不一致时，校验器必须报错。
    #   momentum percentile 0.98 > value 0.92，但 primary 写成了 value
    (
        "test_wrong_primary_strategy_artifact_fails",
        {"primary_strategy_id": "value"},
        "candidate_primary_strategy",
        None,
    ),
    # test_signal_strategy_mismatch_fails:
    #   Step 2: 当 signal 的 strategy_id 与 candidate 的 primary_strategy_id 不一致时报错。
    (
        "test_signal_strategy_mismatch_fails",
        {"signal_strategy_id": "growth"},
        "signal_strategy_match",
        None,
    ),
    # test_market_validation_strategy_mismatch_fails:
    #   Step 3: 当 market validation 的 strategy_id 与 primary_strategy_id 不一致时报错。
    (
        "test_market_validation_strategy_mismatch_fails",
        {"market_validation_strategy_id": "value"},
        "market_validation_strategy_match",
        None,
    ),
    # test_missing_lineage_version_fails:
    #   Step 4: 当 lineage 缺少市场验证或信号版本时，empty_version 必须捕获。
    (
        "test_missing_lineage_version_fails",
        {
            "lineage": {
                "universe_snapshot": "2026-09-04:abc",
                "factor_version": "v1",
                "strategy_version": "v1",
                "qualification_version": "v1",
                "candidate_policy_version": "v1",
                "regime_version": "v1",
                # 故意缺失 market_validation_version 与 signal_version
            }
        },
        "empty_version",
        ("market_validation_version", "signal_version"),
    ),
    # test_breakdown_signal_in_candidate_fails_independent_validation:
    #   Task 8: 独立校验器复算决策 D1，任何含有 BREAKDOWN 破位信号的候选产物必须报错。
    (
        "test_breakdown_signal_in_candidate_fails_independent_validation",
        {"signal": "BREAKDOWN"},
        "signal_veto",
        None,
    ),
    # test_trend_weaken_wrong_action_fails_independent_validation:
    #   Task 8: 独立校验器复算决策 E1，含有 TREND_WEAKEN 信号的候选动作必须为 WATCH。
    (
        "test_trend_weaken_wrong_action_fails_independent_validation",
        {"signal": "TREND_WEAKEN", "next_action": "DEEP_RESEARCH"},
        "signal_action",
        None,
    ),
    # test_trend_weaken_missing_warning_fails_independent_validation:
    #   Task 8: 独立校验器复算决策 E1，含有 TREND_WEAKEN 信号的候选必须在 risks 中携带走弱预警。
    (
        "test_trend_weaken_missing_warning_fails_independent_validation",
        {"signal": "TREND_WEAKEN", "risks": []},
        "signal_risk_warning",
        None,
    ),
    # test_liquidity_veto_violation_in_candidate_fails_independent_validation:
    #   Task 8: 独立校验器独立复算 5D 流动性底线，若引用均成交额击穿 1 亿警戒线必须报错。
    (
        "test_liquidity_veto_violation_in_candidate_fails_independent_validation",
        {
            "strategy_results": [
                {
                    "symbol": "600000.SH",
                    "strategy_id": "momentum",
                    "strategy_version": "v1",
                    "as_of": AS_OF.isoformat(),
                    "score": 95.0,
                    "rank_percentile": 0.98,
                    "factor_snapshot": [
                        {
                            "symbol": "600000.SH",
                            "factor": "avg_amount_20d",
                            "raw_value": 80_000_000.0,  # 0.8亿 < 1.0亿
                        }
                    ],
                }
            ]
        },
        "market_validation_liquidity_veto",
        None,
    ),
)


def test_every_bad_candidate_record_hits_its_expected_check() -> None:
    """原 8 条独立校验用例收表：每条坏记录命中指定 check，缺版本行另断言 observed 片段。"""
    wrong = []
    for label, overrides, expected_check, expected_observed in CANDIDATE_CHECK_CASES:
        bad_record = _candidate_record(**overrides)
        findings = validate_snapshot("CANDIDATE", [bad_record], as_of=AS_OF)
        checks = [f.check for f in findings]
        if expected_check not in checks:
            wrong.append(f"{label}: 未命中 {expected_check!r}，实际 {checks!r}")
            continue
        if expected_observed is not None:
            observed = " ".join(
                f.observed for f in findings if f.check == expected_check
            )
            for fragment in expected_observed:
                if fragment not in observed:
                    wrong.append(
                        f"{label}: observed 缺少 {fragment!r}，实际 {observed!r}"
                    )
    assert not wrong, "独立校验未按预期命中:\n" + "\n".join(wrong)


def test_valid_candidate_semantic_artifact_passes() -> None:
    """正确装配语义与血缘的 Candidate 快照必须 0 finding 通过。"""
    good_record = _candidate_record()
    findings = validate_snapshot("CANDIDATE", [good_record], as_of=AS_OF)
    assert findings == ()
