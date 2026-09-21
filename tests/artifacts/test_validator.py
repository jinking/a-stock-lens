"""Independent tests for the upgraded artifact validator.

Confirms that the validator enforces candidate qualification and policy integrity
WITHOUT importing any production code from astock_lens.
"""

from datetime import UTC, datetime

from artifacts.validator import (
    ArtifactFinding,
    validate_snapshot,
    validate_snapshot_set,
)

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _factor_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "symbol": "600000.SH",
        "factor": "ret_20d",
        "as_of": AS_OF.isoformat(),
        "status": "VALUE",
        "factor_version": "v1",
        "lineage": {"factor_version": "v1"},
    }
    record.update(overrides)
    return record


def _strategy_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "symbol": "600000.SH",
        "strategy_id": "momentum",
        "as_of": AS_OF.isoformat(),
        "eligible": True,
        "score": 80.0,
        "rank_percentile": 0.95,
        "lineage": {"strategy_version": "v1"},
        "factor_snapshot": [
            {
                "factor": "ret_20d",
                "factor_version": "v1",
            }
        ],
    }
    record.update(overrides)
    return record


def _candidate_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "symbol": "600000.SH",
        "as_of": AS_OF.isoformat(),
        "next_action": "WATCH",
        "primary_strategy_id": "momentum",
        "reasons": (),
        "risks": (),
        "candidate_policy_version": "v1",
        "strategy_qualifications": [
            {
                "symbol": "600000.SH",
                "strategy_id": "momentum",
                "qualified": True,
                "rank_percentile": 0.95,
                "percentile_floor": 0.90,
                "as_of": AS_OF.isoformat(),
                "lineage": {"qualification_version": "v1"},
            }
        ],
        "market_validation": None,
        "signal": None,
        "lineage": {
            "strategy_version": "v1",
            "qualification_version": "v1",
            "candidate_policy_version": "v1",
            "regime_version": "v1",
            "market_validation_version": "v1",
            "signal_version": "v1",
            "universe_snapshot": "2026-09-04:abc",
        },
        "strategy_results": [_strategy_record()],
    }
    record.update(overrides)
    return record


def _checks(findings: tuple[ArtifactFinding, ...]) -> list[str]:
    return [finding.check for finding in findings]


def test_candidate_missing_required_keys_reported() -> None:
    rec = _candidate_record()
    del rec["strategy_qualifications"]
    del rec["candidate_policy_version"]

    findings = validate_snapshot("CANDIDATE", [rec], as_of=AS_OF)
    assert "required_keys" in _checks(findings)


def test_candidate_without_any_qualified_strategy_fails() -> None:
    unqualified = {
        "symbol": "600000.SH",
        "strategy_id": "momentum",
        "qualified": False,
        "percentile_floor": 0.90,
        "as_of": AS_OF.isoformat(),
        "lineage": {"qualification_version": "v1"},
    }
    rec = _candidate_record(strategy_qualifications=[unqualified])
    findings = validate_snapshot("CANDIDATE", [rec], as_of=AS_OF)

    assert "candidate_qualifications" in _checks(findings)
    assert any("no qualified" in f.observed for f in findings)


def test_candidate_qualified_strategy_lacking_matching_strategy_result_fails() -> None:
    rec = _candidate_record(strategy_results=[])
    findings = validate_snapshot("CANDIDATE", [rec], as_of=AS_OF)

    assert "candidate_qualifications" in _checks(findings)
    assert any("has no matching cited strategy_result" in f.observed for f in findings)


def test_candidate_with_contradicted_market_validation_fails() -> None:
    rec = _candidate_record(market_validation="CONTRADICTED")
    findings = validate_snapshot("CANDIDATE", [rec], as_of=AS_OF)

    assert "market_validation_veto" in _checks(findings)


def test_candidate_with_empty_version_fails() -> None:
    rec = _candidate_record(candidate_policy_version="")
    findings = validate_snapshot("CANDIDATE", [rec], as_of=AS_OF)
    assert "empty_version" in _checks(findings)

    rec2 = _candidate_record(
        lineage={
            "strategy_version": "v1",
            "qualification_version": "",
            "candidate_policy_version": "v1",
        }
    )
    findings2 = validate_snapshot("CANDIDATE", [rec2], as_of=AS_OF)
    assert "empty_version" in _checks(findings2)


def test_candidate_duplicate_symbol_reported() -> None:
    rec1 = _candidate_record(symbol="600000.SH")
    rec2 = _candidate_record(symbol="600000.SH")

    findings = validate_snapshot("CANDIDATE", [rec1, rec2], as_of=AS_OF)
    assert "unique_symbols" in _checks(findings)


def test_candidate_count_exceeding_fifty_fails() -> None:
    recs = [_candidate_record(symbol=f"{i:06d}.SH") for i in range(51)]
    findings = validate_snapshot("CANDIDATE", recs, as_of=AS_OF)
    assert "candidate_count" in _checks(findings)


def test_clean_candidate_snapshot_passes_validation() -> None:
    findings = validate_snapshot("CANDIDATE", [_candidate_record()], as_of=AS_OF)
    assert findings == ()


def test_candidate_cross_snapshot_validation() -> None:
    cand = _candidate_record()
    strat = _strategy_record()
    factor = _factor_record()

    # Clean set passes
    findings = validate_snapshot_set(
        factor_records=[factor],
        strategy_records=[strat],
        candidate_records=[cand],
        as_of=AS_OF,
    )
    assert findings == ()

    # If qualified strategy is missing from STRATEGY snapshot
    findings_missing_strat = validate_snapshot_set(
        factor_records=[factor],
        strategy_records=[],
        candidate_records=[cand],
        as_of=AS_OF,
    )
    assert "cross_snapshot" in _checks(findings_missing_strat)

    # If cited factor is missing from FACTOR snapshot
    findings_missing_factor = validate_snapshot_set(
        factor_records=[],
        strategy_records=[strat],
        candidate_records=[cand],
        as_of=AS_OF,
    )
    assert "cross_snapshot" in _checks(findings_missing_factor)
