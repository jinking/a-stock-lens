"""唯一分析执行链（Canonical Analysis Flow）。

本模块是"从原始数据到策略结果"的**唯一**业务实现：

    NORMALIZE → COMPUTE_FACTORS → BUILD_UNIVERSE → RUN_STRATEGIES

`astock daily`（正式运行）与 CLI 的只读命令都走这里，所以同一天、同一份数据
不会因为入口不同而算出两套结果。之前 first slice 与 daily scan 各有一套组装
逻辑，两个入口的因子集合、Universe 规则、Scanner 数量都可以不同——"同一个
项目里有两个真相"正是本阶段要消灭的东西。

边界写在这里，不写在文档里：

- `run_analysis()` **只计算**：不写正式 Snapshot，不写 Job Manifest，不碰
  Watchlist。正式快照的唯一写入者是 `astock daily`。
- 它不重新实现任何计算：Normalize、Factor、Universe、Strategy 全部调用
  `astock_lens.pipelines.stages` 里同一组 stage 函数。
- 它不做 Candidate 判定：资格规则尚未批准，组装发生在 pipeline 的
  Candidate 阶段。
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from astock_lens.domain.models import DomainRecord
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines.stages import (
    DEFAULT_DATASET,
    DEFAULT_SECURITIES_DATASET,
    NormalizeOutcome,
    factor_stage,
    normalize_stage,
    strategy_stage,
    universe_stage,
)
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.registry import RegisteredStrategy
from astock_lens.universe.config import UniverseConfig
from astock_lens.universe.models import UniverseSnapshot

__all__ = ["AnalysisState", "FactorState", "compute_factor_state", "run_analysis"]


class AnalysisState(DomainRecord):
    """一次分析链算出的全部中间结果，按数据流方向排列。

    每个字段都是上游 stage 的真实产出：没有产出就说没有，不留占位值。
    """

    as_of: datetime
    outcome: NormalizeOutcome
    universe: UniverseSnapshot
    factor_results: tuple[FactorResult, ...] = ()
    strategy_results: tuple[StrategyResult, ...] = ()


class FactorState(DomainRecord):
    """分析链的前半段：归一化结果，以及它产生的每一个因子观测。

    `factors compute` 只需要这一段。把它单独拿出来，是为了让"只算因子"这条
    命令不必为了省一次策略计算而自己拼一套 normalize/factor 调用——那样又会
    多出一个真相。
    """

    as_of: datetime
    outcome: NormalizeOutcome
    factor_results: tuple[FactorResult, ...] = ()


def compute_factor_state(
    *,
    csv_root: Path,
    as_of: datetime,
    factor_configs: Sequence[FactorConfig],
    dataset: str = DEFAULT_DATASET,
    securities_dataset: str = DEFAULT_SECURITIES_DATASET,
) -> FactorState:
    """Normalize and measure, then stop. Nothing is persisted."""
    outcome = normalize_stage(
        csv_root=csv_root,
        as_of=as_of,
        dataset=dataset,
        securities_dataset=securities_dataset,
    )
    return FactorState(
        as_of=as_of,
        outcome=outcome,
        factor_results=factor_stage(
            outcome=outcome,
            factor_configs=factor_configs,
            as_of=as_of,
        ),
    )


def run_analysis(
    *,
    csv_root: Path,
    as_of: datetime,
    universe_config: UniverseConfig,
    factor_configs: Sequence[FactorConfig],
    scanners: Sequence[RegisteredStrategy],
    dataset: str = DEFAULT_DATASET,
    securities_dataset: str = DEFAULT_SECURITIES_DATASET,
) -> AnalysisState:
    """Run the canonical chain once for one point in time.

    Configuration is passed in rather than discovered, so a caller can see
    exactly which thresholds, factor windows and scanner versions a run used.
    Factors are computed before the Universe because the liquidity rule
    consumes the `avg_amount_20d` factor — the reviewed deviation recorded in
    `docs/REVIEW_NOTES.md`, not an accident.
    """
    measured = compute_factor_state(
        csv_root=csv_root,
        as_of=as_of,
        factor_configs=factor_configs,
        dataset=dataset,
        securities_dataset=securities_dataset,
    )
    universe = universe_stage(
        outcome=measured.outcome,
        factor_results=measured.factor_results,
        config=universe_config,
        as_of=as_of,
    )
    strategy_results = strategy_stage(
        scanners=scanners,
        universe=universe,
        factor_results=measured.factor_results,
        as_of=as_of,
    )

    return AnalysisState(
        as_of=as_of,
        outcome=measured.outcome,
        universe=universe,
        factor_results=measured.factor_results,
        strategy_results=strategy_results,
    )
