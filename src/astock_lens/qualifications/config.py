"""严格失败关闭的生产资格规则配置加载。

设计目标（见 2026-09-20 资格正确性加固规格 §5）：生产资格规则必须 fail-closed。
任何"空阈值自动通过""畸形条目静默跳过""缺键静默兜底"的行为都必须被拒绝，
并以 ``QualificationConfigInvalid`` 响亮失败，而不是降级为"未配置"。

文件缺失仍是另一条语义：``load_qualification_rule`` 抛 ``FileNotFoundError``，
由 ``load_canonical_qualifiers`` 翻译为 ``QualificationRuleNotConfigured``（= BLOCKED），
从而让 daily 区分"未配置 → BLOCKED"与"配置损坏 → FAILED loudly"。
"""

import math
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import yaml
from pydantic import ValidationError, model_validator

from astock_lens.domain.models import DomainRecord

if TYPE_CHECKING:
    # 仅供类型检查：运行时在 loader 内延迟导入以打破 config ↔ rules 循环依赖。
    from astock_lens.qualifications.rules import FactorThresholdRule


class QualificationConfigInvalid(ValueError):
    """Raised when a qualification rule configuration file is malformed or unsafe."""


class FactorThreshold(DomainRecord):
    """单个因子的资格阈值区间 ``[min, max]``。

    必须至少给出一侧边界；两侧边界都必须是有限数；``min`` 不得大于 ``max``。
    这样"无边界"不可能被解释成"无条件通过"。
    """

    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> Self:
        if self.min is None and self.max is None:
            raise ValueError("threshold requires min and/or max")
        for value in (self.min, self.max):
            if value is not None and not math.isfinite(value):
                raise ValueError("threshold bounds must be finite")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("threshold min cannot exceed max")
        return self


class QualificationRuleConfig(DomainRecord):
    """一份严格的生产资格规则配置。"""

    strategy_id: str
    version: str
    description: str = ""
    thresholds: dict[str, FactorThreshold]

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        if not self.strategy_id.strip():
            raise ValueError("strategy_id cannot be blank")
        if not self.version.strip():
            raise ValueError("version cannot be blank")
        if not self.thresholds:
            raise ValueError("thresholds cannot be empty")
        return self


def load_qualification_rule(
    path: Path,
    *,
    expected_strategy_id: str | None = None,
    known_factor_names: frozenset[str] | None = None,
) -> "FactorThresholdRule":
    """从 YAML 文件严格加载一条 ``FactorThresholdRule``。

    - 文件缺失 → ``FileNotFoundError``（保留"未配置"语义）；
    - YAML 根 / ``thresholds`` / 单条 threshold 非映射 → ``QualificationConfigInvalid``；
    - 缺 ``strategy_id`` / ``version`` 键，或 strip 后为空 → ``QualificationConfigInvalid``；
    - 空阈值、无边界、非有限值、``min > max`` → ``QualificationConfigInvalid``；
    - ``expected_strategy_id`` 与配置不符 → ``QualificationConfigInvalid``；
    - ``known_factor_names`` 非空差集 → ``QualificationConfigInvalid``。
    """
    # 延迟导入以避免 config ↔ rules 的模块级循环依赖。
    from astock_lens.qualifications.rules import FactorThresholdRule

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
            strategy_id=str(raw["strategy_id"]).strip(),
            version=str(raw["version"]).strip(),
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
