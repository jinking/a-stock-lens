"""Growth strategy qualification."""

from astock_lens.qualifications.common import build_qualification
from astock_lens.qualifications.contracts import AbsoluteQualificationRule
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult


class GrowthQualifier:
    """Qualifier for the growth strategy."""

    strategy_id: str = "growth"

    def __init__(
        self,
        *,
        absolute_rule: AbsoluteQualificationRule,
        qualification_version: str,
    ) -> None:
        self.absolute_rule = absolute_rule
        self.qualification_version = qualification_version

    def qualify(self, result: StrategyResult) -> StrategyQualification:
        return build_qualification(
            result=result,
            expected_strategy_id=self.strategy_id,
            qualification_version=self.qualification_version,
            absolute_rule=self.absolute_rule,
        )
