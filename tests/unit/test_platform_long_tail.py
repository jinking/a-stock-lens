"""平台长尾（领域模型契约、Jev 分诊工具）。

本文件由 Task 12「文件合并」把以下 2 个同域小文件整体搬入：
    - tests/unit/test_domain_models.py（5 例）
    - tests/unit/test_jev_triage.py（5 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace, TracebackType
from typing import Any, Self

import pytest
from pydantic import ValidationError

from astock_lens.ai import jev
from astock_lens.ai.jev import FailureCategory
from astock_lens.domain.enums import (
    ACTIVE_WATCHLIST_STATES,
    RESERVED_WATCHLIST_STATES,
    DataStatus,
    ErrorSeverity,
    WatchlistState,
)
from astock_lens.domain.models import FinancialObservation

# ===========================================================================
# 来源：tests/unit/test_domain_models.py（5 例）
# ===========================================================================


def test_financial_observation_rejects_future_availability() -> None:
    with pytest.raises(ValidationError):
        FinancialObservation(
            symbol="000001.SZ",
            metric="roe",
            value=10.0,
            report_period=date(2026, 6, 30),
            announce_date=date(2026, 8, 20),
            available_at=datetime(2026, 8, 20, tzinfo=UTC),
            as_of=datetime(2026, 8, 19, tzinfo=UTC),
            source="fixture",
        )


def test_architecture_enums_are_explicit() -> None:
    assert {item.value for item in DataStatus} == {
        "VALUE",
        "NULL",
        "STALE",
        "INVALID",
        "SOURCE_ERROR",
        "NOT_APPLICABLE",
    }
    assert {item.value for item in ErrorSeverity} == {"P0", "P1", "P2", "P3"}
    assert WatchlistState.DEEP_RESEARCH.value == "DEEP_RESEARCH"


def test_missing_financial_value_stays_none() -> None:
    observation = FinancialObservation(
        symbol="000001.SZ",
        metric="roe",
        value=None,
        report_period=date(2026, 6, 30),
        announce_date=date(2026, 8, 20),
        available_at=datetime(2026, 8, 20, tzinfo=UTC),
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        source="fixture",
    )

    assert observation.value is None


def test_naive_timestamps_are_rejected() -> None:
    """Naive timestamps must fail instead of comparing on an implicit offset."""
    with pytest.raises(ValidationError):
        FinancialObservation(
            symbol="000001.SZ",
            metric="roe",
            value=10.0,
            report_period=date(2026, 6, 30),
            announce_date=date(2026, 8, 20),
            # Naive on purpose: these two lines are the subject of the test.
            available_at=datetime(2026, 8, 20),  # noqa: DTZ001
            as_of=datetime(2026, 9, 1),  # noqa: DTZ001
            source="fixture",
        )


def test_watchlist_states_keep_active_and_reserved_apart() -> None:
    assert ACTIVE_WATCHLIST_STATES == {
        WatchlistState.DISCOVERED,
        WatchlistState.WATCH,
        WatchlistState.DEEP_RESEARCH,
        WatchlistState.TRACK_SIGNAL,
    }
    assert RESERVED_WATCHLIST_STATES == {
        WatchlistState.READY,
        WatchlistState.HOLDING,
        WatchlistState.EXITED,
        WatchlistState.ARCHIVED,
    }
    assert ACTIVE_WATCHLIST_STATES | RESERVED_WATCHLIST_STATES == set(WatchlistState)


# ===========================================================================
# 来源：tests/unit/test_jev_triage.py（5 例）
# ===========================================================================


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
