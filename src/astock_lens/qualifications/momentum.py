"""Momentum strategy qualifier compatibility import."""

from astock_lens.qualifications.common import ConfiguredQualifier
from astock_lens.qualifications.contracts import AbsoluteQualificationRule


class MomentumQualifier(ConfiguredQualifier):
    """Compatibility wrapper for the momentum strategy qualifier."""

    def __init__(
        self,
        *,
        absolute_rule: AbsoluteQualificationRule,
        qualification_version: str,
    ) -> None:
        super().__init__(
            strategy_id="momentum",
            absolute_rule=absolute_rule,
            qualification_version=qualification_version,
        )
