from __future__ import annotations

from types import SimpleNamespace, TracebackType
from typing import Any, Self

from astock_lens.ai import jev
from astock_lens.ai.jev import FailureCategory


class _FakeChoice:
    def __init__(self, *, instructions: str, criteria: dict[str, str]) -> None:
        self.instructions = instructions
        self.criteria = criteria


class _FakeAnswer:
    choice = "missing_evidence"
    confidence = 0.91

    def __init__(self) -> None:
        self.probabilities = {
            "implementation_bug": 0.03,
            "test_bug": 0.01,
            "missing_evidence": 0.91,
            "environment": 0.01,
            "flaky": 0.01,
            "uncertain": 0.03,
        }


class _FakeResponse:
    model = "jev-test"
    request_id = "req-test-1"

    def __init__(self) -> None:
        self.choices = {"failure_type": _FakeAnswer()}
        self.usage = SimpleNamespace(input_tokens=123, output_tokens=0)


class _FakeClient:
    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        self.received_state: dict[str, Any] | None = None
        self.received_questions: dict[str, Any] | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def system_one(
        self, *, state: dict[str, Any], questions: dict[str, Any]
    ) -> _FakeResponse:
        self.received_state = state
        self.received_questions = questions
        return _FakeResponse()


class _FakeSDK:
    Choice = _FakeChoice
    TypeSafeClient = _FakeClient


def test_classify_test_failure_returns_choice_and_metadata(monkeypatch: Any) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(jev, "_load_typesafe_sdk", lambda: _FakeSDK)

    result = jev.classify_test_failure(
        {
            "test_name": "test_candidate_requires_market_evidence",
            "assertion": "expected missing evidence to block publication",
            "traceback": "AssertionError",
        }
    )

    assert result.available is True
    assert result.category is FailureCategory.MISSING_EVIDENCE
    assert result.confidence == 0.91
    assert result.probabilities["missing_evidence"] == 0.91
    assert result.model == "jev-test"
    assert result.input_tokens == 123
    assert result.output_tokens == 0
    assert result.request_id == "req-test-1"
    assert result.error is None


def test_missing_api_key_fails_gracefully(monkeypatch: Any) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    result = jev.classify_test_failure({"test_name": "test_x"})

    assert result.available is False
    assert result.category is FailureCategory.UNCERTAIN
    assert result.confidence == 0.0
    assert result.probabilities == {}
    assert result.error == "未设置 TYPESAFE_API_KEY"


def test_sdk_error_fails_gracefully(monkeypatch: Any) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    def _raise() -> Any:
        raise ModuleNotFoundError("typesafe_sdk")

    monkeypatch.setattr(jev, "_load_typesafe_sdk", _raise)

    result = jev.classify_test_failure({"test_name": "test_x"})

    assert result.available is False
    assert result.category is FailureCategory.UNCERTAIN
    assert result.error is not None
    assert result.error.startswith("ModuleNotFoundError:")


def test_unknown_choice_is_not_silently_accepted() -> None:
    answer = SimpleNamespace(
        choice="made_up_category",
        confidence=0.99,
        probabilities={"made_up_category": 0.99},
    )
    response = SimpleNamespace(
        choices={"failure_type": answer},
        model="jev-test",
        usage=SimpleNamespace(input_tokens=1, output_tokens=0),
    )

    result = jev._convert_response(response)

    assert result.available is False
    assert result.category is FailureCategory.UNCERTAIN
    assert result.error == "TypeSafe 返回了未知分类: made_up_category"


def test_to_dict_has_stable_json_shape() -> None:
    result = jev.FailureTriage(
        available=True,
        category=FailureCategory.IMPLEMENTATION_BUG,
        confidence=0.88,
        probabilities={"implementation_bug": 0.88},
        model="jev-test",
        input_tokens=10,
        output_tokens=0,
        request_id="req-1",
    )

    assert result.to_dict() == {
        "available": True,
        "category": "implementation_bug",
        "confidence": 0.88,
        "probabilities": {"implementation_bug": 0.88},
        "model": "jev-test",
        "usage": {"input_tokens": 10, "output_tokens": 0},
        "request_id": "req-1",
        "error": None,
    }
