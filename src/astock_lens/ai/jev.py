"""Jev / TypeSafe System One 的测试失败分类封装。

本模块只做“有限类别判断”，不修改测试、不修改业务代码，也不参与 Candidate
发布等业务决策。TypeSafe 不可用时返回 ``available=False``，调用方可以安全地
回退给 Codex / 人工分析。
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class FailureCategory(StrEnum):
    """Jev 允许返回的测试失败类别。"""

    IMPLEMENTATION_BUG = "implementation_bug"
    TEST_BUG = "test_bug"
    MISSING_EVIDENCE = "missing_evidence"
    ENVIRONMENT = "environment"
    FLAKY = "flaky"
    UNCERTAIN = "uncertain"


FAILURE_CRITERIA: dict[str, str] = {
    FailureCategory.IMPLEMENTATION_BUG.value: (
        "生产实现的行为最可能不正确；测试本身与依赖环境没有明显证据表明是主因。"
    ),
    FailureCategory.TEST_BUG.value: (
        "测试期望、fixture、mock、测试准备步骤或测试本身最可能已过时或不正确。"
    ),
    FailureCategory.MISSING_EVIDENCE.value: (
        "失败主要由必要的数据、市场证据、上下文字段或业务证据缺失/不完整导致；"
        "不得把缺失证据解释成 0、False 或 NEUTRAL。"
    ),
    FailureCategory.ENVIRONMENT.value: (
        "失败最可能来自依赖、配置、文件系统、权限、网络、外部服务或运行时环境。"
    ),
    FailureCategory.FLAKY.value: (
        "失败看起来具有非确定性、时序竞争、偶发超时或间歇性特征。"
    ),
    FailureCategory.UNCERTAIN.value: (
        "当前证据不足、互相冲突，或无法可靠归入其他类别。"
    ),
}


@dataclass(frozen=True, slots=True)
class FailureTriage:
    """一次 Jev 分类结果。"""

    available: bool
    category: FailureCategory
    confidence: float
    probabilities: dict[str, float]
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为适合 CLI / JSON 报告使用的字典。"""

        return {
            "available": self.available,
            "category": self.category.value,
            "confidence": self.confidence,
            "probabilities": dict(self.probabilities),
            "model": self.model,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            },
            "request_id": self.request_id,
            "error": self.error,
        }


def _unavailable(error: str) -> FailureTriage:
    return FailureTriage(
        available=False,
        category=FailureCategory.UNCERTAIN,
        confidence=0.0,
        probabilities={},
        error=error,
    )


def _load_typesafe_sdk() -> Any:
    """延迟加载 SDK，使普通项目代码与离线单测不强依赖 TypeSafe。"""

    return importlib.import_module("typesafe_sdk")


def _safe_request_id(response: Any) -> str | None:
    try:
        value = response.request_id
    except Exception:  # noqa: BLE001 - 元数据缺失不应让 triage 失败
        return None
    return str(value) if value else None


def _convert_response(response: Any) -> FailureTriage:
    answer = response.choices.get("failure_type")
    if answer is None:
        return _unavailable("TypeSafe 响应中缺少 failure_type ChoiceAnswer")

    raw_choice = str(answer.choice)
    try:
        category = FailureCategory(raw_choice)
    except ValueError:
        return _unavailable(f"TypeSafe 返回了未知分类: {raw_choice}")

    probabilities = {
        str(key): float(value) for key, value in dict(answer.probabilities).items()
    }
    confidence = float(answer.confidence)

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
    output_tokens = getattr(usage, "output_tokens", None) if usage is not None else None

    return FailureTriage(
        available=True,
        category=category,
        confidence=confidence,
        probabilities=probabilities,
        model=str(getattr(response, "model", "")) or None,
        input_tokens=int(input_tokens) if input_tokens is not None else None,
        output_tokens=int(output_tokens) if output_tokens is not None else None,
        request_id=_safe_request_id(response),
    )


def classify_test_failure(
    state: dict[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> FailureTriage:
    """使用 Jev 对一个 pytest 失败做有限类别分类。

    Parameters
    ----------
    state:
        结构化失败信息。建议至少包含 ``test_name``、``traceback``、``assertion``，
        以及必要的相关文件/上下文摘要。
    timeout_seconds:
        TypeSafe HTTP 调用超时。超时或 API 不可用时返回 ``available=False``。

    Notes
    -----
    - 本函数绝不修改业务状态。
    - 缺失 ``TYPESAFE_API_KEY`` 时不会抛错，而是返回 unavailable。
    - 任何 API/网络/响应解析异常都转换成 unavailable，便于 Agent 回退到自身分析。
    """

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        return _unavailable("未设置 TYPESAFE_API_KEY")

    try:
        sdk = _load_typesafe_sdk()
        with sdk.TypeSafeClient(timeout=timeout_seconds) as client:
            response = client.system_one(
                state=state,
                questions={
                    "failure_type": sdk.Choice(
                        instructions=(
                            "请仅依据给定证据判断 pytest 失败最可能的根因类别。"
                            "不要提出修复方案，不要改变业务规则。证据不足时必须选择 uncertain。"
                        ),
                        criteria=FAILURE_CRITERIA,
                    )
                },
            )
        return _convert_response(response)
    except Exception as exc:  # noqa: BLE001 - POC 必须保证 Jev 故障不会打断 pytest/Codex 流程
        return _unavailable(f"{type(exc).__name__}: {exc}")
