"""股票发现查询层领域模型。"""

from typing import Self

from pydantic import model_validator

from astock_lens.domain.models import DomainRecord


class StrategyScreenQuery(DomainRecord):
    """策略股票筛选查询参数。"""

    strategy_id: str
    limit: int = 20
    eligible_only: bool = True
    min_percentile: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """校验查询参数边界。"""
        if self.limit <= 0:
            raise ValueError(f"limit must be positive, got {self.limit}")
        if self.min_percentile is not None and not (0.0 <= self.min_percentile <= 1.0):
            raise ValueError(
                f"min_percentile must be between 0.0 and 1.0, got {self.min_percentile}"
            )
        return self


class StrategyScreenItem(DomainRecord):
    """单个标的的策略筛选结果项。"""

    rank: int
    symbol: str
    strategy_id: str
    strategy_version: str
    score: float | None
    rank_percentile: float | None
    confidence: float | None
    eligible: bool
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


class StrategyCoverage(DomainRecord):
    """策略在当前快照中的覆盖度统计。"""

    strategy_id: str
    total_count: int
    eligible_count: int
    scored_count: int
    ranked_count: int


class StrategyScreenResult(DomainRecord):
    """策略股票筛选的完整查询结果。"""

    strategy_id: str
    coverage: StrategyCoverage
    items: tuple[StrategyScreenItem, ...]


class QualifiedScreenQuery(DomainRecord):
    """双门槛合格股票发现查询参数。"""

    strategy_id: str
    limit: int = 20

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """校验查询参数边界。"""
        if self.limit <= 0:
            raise ValueError(f"limit must be positive, got {self.limit}")
        return self


class QualifiedCoverage(DomainRecord):
    """合格判定在应用 limit 之前对全量结果的覆盖度统计。

    - ``strategy_eligible_count``：eligible 为 True 的结果条数；
    - ``ranked_count``：rank_percentile 非 None 的结果条数；
    - ``percentile_pass_count`` / ``absolute_pass_count`` / ``qualified_count``：
      对参与判定（eligible 且已排名）的结果调用 qualifier 后按对应字段统计。
    """

    strategy_id: str
    strategy_eligible_count: int
    ranked_count: int
    percentile_pass_count: int
    absolute_pass_count: int
    qualified_count: int


class QualifiedScreenItem(DomainRecord):
    """单个双门槛通过（qualified）标的的发现结果项。"""

    rank: int
    symbol: str
    strategy_id: str
    strategy_version: str
    qualification_version: str
    score: float | None
    rank_percentile: float
    reasons: tuple[str, ...]
    risks: tuple[str, ...]


class QualifiedScreenResult(DomainRecord):
    """双门槛合格股票发现的完整查询结果。

    ``items`` 只包含 qualified == True 的结果；零合格时必须通过 ``warnings``
    给出确定性的数据健康提示，绝不静默返回空结果。
    """

    strategy_id: str
    coverage: QualifiedCoverage
    items: tuple[QualifiedScreenItem, ...]
    warnings: tuple[str, ...] = ()


class StockProfileUniverse(DomainRecord):
    """股票池准入与剔除规则状态。"""

    included: bool
    exclusion_rules: tuple[str, ...] = ()


class StockProfileResponse(DomainRecord):
    """单股全景研究画像响应契约。"""

    as_of: str
    symbol: str
    universe: StockProfileUniverse
    factors: tuple[dict[str, object], ...] = ()
    strategies: tuple[dict[str, object], ...] = ()
    candidate_status: str
    candidate: dict[str, object] | None = None
    watchlist: dict[str, object] | None = None
