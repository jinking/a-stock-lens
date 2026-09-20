"""Factor-based absolute qualification rules and loaders."""

from collections.abc import Mapping
from pathlib import Path

import yaml

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord
from astock_lens.qualifications.models import (
    AbsoluteQualificationVerdict,
    QualificationContext,
)


class FactorThreshold(DomainRecord):
    """Threshold range [min, max] for a specific factor."""

    min: float | None = None
    max: float | None = None


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


def load_qualification_rule(path: Path) -> FactorThresholdRule:
    """Load a FactorThresholdRule from a YAML configuration file."""
    if not path.is_file():
        raise FileNotFoundError(f"Qualification rule file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(
            f"Invalid YAML content in {path}: expected a dictionary mapping"
        )

    strategy_id = str(raw.get("strategy_id", path.stem))
    version = str(raw.get("version", "v1"))
    description = str(raw.get("description", ""))

    thresholds_raw = raw.get("thresholds", {})
    if not isinstance(thresholds_raw, dict):
        raise TypeError(f"Invalid thresholds in {path}: expected a dictionary")

    thresholds: dict[str, FactorThreshold] = {}
    for factor_name, bounds in thresholds_raw.items():
        if not isinstance(bounds, dict):
            continue
        min_val = (
            float(bounds["min"])
            if "min" in bounds and bounds["min"] is not None
            else None
        )
        max_val = (
            float(bounds["max"])
            if "max" in bounds and bounds["max"] is not None
            else None
        )
        thresholds[factor_name] = FactorThreshold(min=min_val, max=max_val)

    return FactorThresholdRule(
        strategy_id=strategy_id,
        version=version,
        thresholds=thresholds,
        description=description,
    )
