"""独立 Trade Gate JSON Artifact Validator；不得导入 astock_lens。"""

import json
from pathlib import Path
from typing import Any


def validate_evaluation(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not document.get("id") or not document.get("intent_id"):
        errors.append("evaluation IDs are required")
    if document.get("decision") not in {"PASS", "WAIT", "NO_TRADE"}:
        errors.append("invalid decision")
    score = document.get("weighted_score")
    if not isinstance(score, (int, float)) or not 0 <= score <= 100:
        errors.append("weighted_score must be within 0..100")
    dimensions = document.get("dimension_scores", [])
    if abs(sum(item.get("score", 0) for item in dimensions) - (score or 0)) > 1e-6:
        errors.append("dimension scores do not sum to weighted score")
    vetoes = document.get("vetoes", [])
    if document.get("decision") == "PASS" and any(
        v.get("active") and v.get("severity") == "HARD" for v in vetoes
    ):
        errors.append("PASS cannot contain active hard veto")
    if document.get("decision") == "WAIT" and not document.get("reentry_triggers"):
        errors.append("WAIT requires reentry triggers")
    for key in ("profile_version", "rule_set_version"):
        if not document.get(key):
            errors.append(f"{key} is required")
    text = json.dumps(document, ensure_ascii=False).upper()
    if '"BUY"' in text:
        errors.append("BUY is forbidden")
    for key in ("evaluated_at",):
        value = document.get(key)
        if not isinstance(value, str) or not any(c in value for c in ("+", "Z")):
            errors.append(f"{key} must include timezone offset")
    return errors


def validate_file(path: Path) -> list[str]:
    return validate_evaluation(json.loads(path.read_text(encoding="utf-8")))
