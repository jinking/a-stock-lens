"""使用 JSON-over-stdin 外部命令进行两阶段审计。"""

import json
import os
import shlex
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

from astock_lens.domain.enums import TradeProfile
from astock_lens.trade_gate.models import (
    DimensionJudgement,
    IndependentAssessment,
    ThesisAuditResult,
)

COMMAND_ENV = "ASTOCK_TRADE_AUDIT_CMD"


class TradeAuditNotConfigured(RuntimeError):
    """未配置外部审计命令。"""


class TradeAuditInvocationError(RuntimeError):
    """外部命令失败或输出不符合契约。"""


def adjusted_ratio(judgement: DimensionJudgement) -> float:
    return judgement.score_ratio * (0.5 + 0.5 * judgement.confidence)


@dataclass(frozen=True)
class CliThesisAuditAdapter:
    command: str
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.command.strip():
            raise TradeAuditNotConfigured(f"set {COMMAND_ENV}")

    @classmethod
    def from_environment(cls) -> "CliThesisAuditAdapter":
        command = os.environ.get(COMMAND_ENV, "")
        if not command.strip():
            raise TradeAuditNotConfigured(f"set {COMMAND_ENV}")
        return cls(command)

    def independent_assessment(
        self, *, profile: TradeProfile, facts: Mapping[str, object]
    ) -> IndependentAssessment:
        payload = self._invoke(
            {
                "action": "independent_assessment",
                "profile": profile.value,
                "facts": dict(facts),
            }
        )
        return IndependentAssessment.model_validate(payload)

    def audit_thesis(
        self,
        *,
        profile: TradeProfile,
        facts: Mapping[str, object],
        independent: IndependentAssessment,
        user_thesis: str,
    ) -> ThesisAuditResult:
        payload = self._invoke(
            {
                "action": "thesis_audit",
                "profile": profile.value,
                "facts": dict(facts),
                "independent": independent.model_dump(mode="json"),
                "user_thesis": user_thesis,
            }
        )
        return ThesisAuditResult.model_validate(payload)

    def _invoke(self, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            result = subprocess.run(
                shlex.split(self.command),
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TradeAuditInvocationError(str(exc)) from exc
        if result.returncode != 0:
            raise TradeAuditInvocationError(
                f"audit command exited {result.returncode}: {result.stderr.strip()}"
            )
        try:
            parsed: object = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise TradeAuditInvocationError("audit command did not print JSON") from exc
        if not isinstance(parsed, dict):
            raise TradeAuditInvocationError(
                "audit command output must be a JSON object"
            )
        return parsed
