"""严格失败关闭的生产资格规则配置模型。

设计目标（见 2026-09-20 资格正确性加固规格 §5）：生产资格规则必须 fail-closed。
任何"空阈值自动通过""畸形条目静默跳过""缺键静默兜底"的行为都必须被拒绝，
并以 ``QualificationConfigInvalid`` 响亮失败，而不是降级为"未配置"。

本模块只承载纯配置类型；严格加载器 ``load_qualification_rule`` 位于
``astock_lens.qualifications.rules``，从而保持依赖单向 ``rules → config``。
"""

import math
from typing import Self

from pydantic import model_validator

from astock_lens.domain.models import DomainRecord


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
