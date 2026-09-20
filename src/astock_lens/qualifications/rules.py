"""Factor-based absolute qualification rules.

``FactorThreshold`` 与严格加载器 ``load_qualification_rule`` 现由
``astock_lens.qualifications.config`` 提供（fail-closed，见该模块）；本模块保留
``FactorThresholdRule``（读取 ``QualificationContext`` 完整因子证据的评估逻辑），
并重新导出配置类型，以保持既有导入路径稳定。
"""

from collections.abc import Mapping

from astock_lens.domain.enums import DataStatus
from astock_lens.qualifications.config import (
    FactorThreshold,
    load_qualification_rule,
)
from astock_lens.qualifications.models import (
    AbsoluteQualificationVerdict,
    QualificationContext,
)


class FactorThresholdRule:
    """Strategy-specific absolute quality rule evaluating factors against configured bounds."""

    def __init__(
        self,
        *,
        strategy_id: str,
        version: str,
        thresholds: Mapping[str, FactorThreshold],
        description: str = "",
    ) -> None:
        self.strategy_id = strategy_id
        self.version = version
        self.thresholds = dict(thresholds)
        self.description = description

    def evaluate(self, context: QualificationContext) -> AbsoluteQualificationVerdict:
        """Evaluate the symbol's full factor evidence against all configured thresholds.

        证据来自 ``context.factors``（该股票的完整 FactorResult 集合），而不仅是
        策略评分快照。缺失因子、``raw_value is None`` 或非 ``DataStatus.VALUE``
        一律记为 risk 并导致失败关闭。
        """
        factor_map = {f.factor: f for f in context.factors}
        reasons: list[str] = []
        risks: list[str] = []

        for factor_name, threshold in self.thresholds.items():
            factor_res = factor_map.get(factor_name)
            if factor_res is None or factor_res.raw_value is None:
                risks.append(f"factor '{factor_name}' is missing")
                continue
            if factor_res.status != DataStatus.VALUE:
                risks.append(
                    f"factor '{factor_name}' has non-value status: {factor_res.status.value}"
                )
                continue

            val = factor_res.raw_value
            failed_bound = False
            if threshold.min is not None and val < threshold.min:
                risks.append(
                    f"factor '{factor_name}' value {val:.4f} is below minimum {threshold.min:.4f}"
                )
                failed_bound = True
            if threshold.max is not None and val > threshold.max:
                risks.append(
                    f"factor '{factor_name}' value {val:.4f} exceeds maximum {threshold.max:.4f}"
                )
                failed_bound = True

            if not failed_bound:
                reasons.append(
                    f"factor '{factor_name}' passed threshold [{threshold.min}, {threshold.max}]"
                )

        passed = len(risks) == 0
        return AbsoluteQualificationVerdict(
            passed=passed,
            reasons=tuple(reasons),
            risks=tuple(risks),
        )


__all__ = ["FactorThreshold", "FactorThresholdRule", "load_qualification_rule"]
