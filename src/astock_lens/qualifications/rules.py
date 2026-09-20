"""Factor-based absolute qualification rules and strict loader.

``FactorThreshold`` / ``QualificationRuleConfig`` / ``QualificationConfigInvalid``
由 ``astock_lens.qualifications.config`` 提供（fail-closed，见该模块）。本模块保留
``FactorThresholdRule``（读取 ``QualificationContext`` 完整因子证据的评估逻辑）与严格
加载器 ``load_qualification_rule``，并重新导出配置类型，以保持既有导入路径稳定。

依赖方向单向：``rules → config``，不存在循环导入。
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from astock_lens.domain.enums import DataStatus
from astock_lens.qualifications.config import (
    FactorThreshold,
    QualificationConfigInvalid,
    QualificationRuleConfig,
)
from astock_lens.qualifications.models import (
    AbsoluteQualificationVerdict,
    QualificationContext,
)

_THRESHOLD_KEYS: frozenset[str] = frozenset({"min", "max"})


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


def load_qualification_rule(
    path: Path,
    *,
    expected_strategy_id: str | None = None,
    known_factor_names: frozenset[str] | None = None,
) -> FactorThresholdRule:
    """从 YAML 文件严格加载一条 ``FactorThresholdRule``。

    - 文件缺失 → ``FileNotFoundError``（保留"未配置"语义）；
    - YAML 根 / ``thresholds`` / 单条 threshold 非映射 → ``QualificationConfigInvalid``；
    - 缺 ``strategy_id`` / ``version`` 键，或值为非字符串标量（含 YAML 空值 ``null``），
      或 strip 后为空 → ``QualificationConfigInvalid``；
    - 单条 threshold 出现 ``min`` / ``max`` 之外的键 → ``QualificationConfigInvalid``
      （键名拼错会让边界被静默丢弃，属 fail-open）；
    - 空阈值、无边界、非有限值、``min > max`` → ``QualificationConfigInvalid``；
    - ``expected_strategy_id`` 与配置不符 → ``QualificationConfigInvalid``；
    - ``known_factor_names`` 非空差集 → ``QualificationConfigInvalid``。
    """
    if not path.is_file():
        raise FileNotFoundError(f"Qualification rule file not found: {path}")

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise QualificationConfigInvalid(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise QualificationConfigInvalid(
            f"Invalid YAML content in {path}: expected a mapping"
        )

    if "strategy_id" not in raw or "version" not in raw:
        raise QualificationConfigInvalid(
            f"Invalid qualification rule in {path}: strategy_id and version are required"
        )

    strategy_id_raw = raw["strategy_id"]
    version_raw = raw["version"]
    if not isinstance(strategy_id_raw, str):
        raise QualificationConfigInvalid(
            f"Invalid strategy_id in {path}: expected a string, "
            f"got {type(strategy_id_raw).__name__}"
        )
    if not isinstance(version_raw, str):
        raise QualificationConfigInvalid(
            f"Invalid version in {path}: expected a string, "
            f"got {type(version_raw).__name__}"
        )
    if not strategy_id_raw.strip():
        raise QualificationConfigInvalid(
            f"Invalid strategy_id in {path}: cannot be blank"
        )
    if not version_raw.strip():
        raise QualificationConfigInvalid(f"Invalid version in {path}: cannot be blank")

    thresholds_raw = raw.get("thresholds")
    if not isinstance(thresholds_raw, Mapping):
        raise QualificationConfigInvalid(
            f"Invalid thresholds in {path}: expected a mapping"
        )

    thresholds: dict[str, FactorThreshold] = {}
    for factor_name, bounds in thresholds_raw.items():
        if not isinstance(bounds, Mapping):
            raise QualificationConfigInvalid(
                f"Invalid threshold for factor '{factor_name}' in {path}: "
                "expected a mapping with min and/or max"
            )
        unknown_keys = set(bounds) - _THRESHOLD_KEYS
        if unknown_keys:
            raise QualificationConfigInvalid(
                f"Unknown threshold key(s) for factor '{factor_name}' in {path}: "
                f"{sorted(str(key) for key in unknown_keys)}"
            )
        try:
            thresholds[str(factor_name)] = FactorThreshold(
                min=bounds.get("min"),
                max=bounds.get("max"),
            )
        except ValidationError as exc:
            raise QualificationConfigInvalid(
                f"Invalid threshold for factor '{factor_name}' in {path}: {exc}"
            ) from exc

    try:
        config = QualificationRuleConfig(
            strategy_id=strategy_id_raw.strip(),
            version=version_raw.strip(),
            description=str(raw.get("description") or ""),
            thresholds=thresholds,
        )
    except ValidationError as exc:
        raise QualificationConfigInvalid(
            f"Invalid qualification rule in {path}: {exc}"
        ) from exc

    if expected_strategy_id is not None and config.strategy_id != expected_strategy_id:
        raise QualificationConfigInvalid(
            f"strategy_id mismatch in {path}: expected '{expected_strategy_id}', "
            f"got '{config.strategy_id}'"
        )

    if known_factor_names is not None:
        unknown = set(config.thresholds) - known_factor_names
        if unknown:
            raise QualificationConfigInvalid(
                f"Unknown factor(s) in {path}: {sorted(unknown)}"
            )

    return FactorThresholdRule(
        strategy_id=config.strategy_id,
        version=config.version,
        thresholds=config.thresholds,
        description=config.description,
    )


__all__ = ["FactorThreshold", "FactorThresholdRule", "load_qualification_rule"]
