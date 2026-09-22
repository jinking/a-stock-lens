from tests.artifacts.trade_gate_validator import validate_evaluation


def test_validator_rejects_pass_with_hard_veto() -> None:
    errors = validate_evaluation(
        {
            "id": "e",
            "intent_id": "i",
            "decision": "PASS",
            "weighted_score": 80,
            "dimension_scores": [{"score": 80}],
            "vetoes": [{"active": True, "severity": "HARD"}],
            "profile_version": "v1",
            "rule_set_version": "v1",
            "evaluated_at": "2026-09-22T10:00:00+08:00",
        }
    )
    assert "PASS cannot contain active hard veto" in errors
