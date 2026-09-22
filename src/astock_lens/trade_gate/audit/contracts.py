"""Thesis Audit 的隔离契约。"""

from collections.abc import Mapping
from typing import Protocol

from astock_lens.domain.enums import TradeProfile
from astock_lens.trade_gate.models import IndependentAssessment, ThesisAuditResult


class ThesisAuditAdapter(Protocol):
    def independent_assessment(
        self, *, profile: TradeProfile, facts: Mapping[str, object]
    ) -> IndependentAssessment: ...
    def audit_thesis(
        self,
        *,
        profile: TradeProfile,
        facts: Mapping[str, object],
        independent: IndependentAssessment,
        user_thesis: str,
    ) -> ThesisAuditResult: ...
