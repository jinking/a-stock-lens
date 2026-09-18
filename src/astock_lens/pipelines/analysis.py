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
from astock_lens.universe.builder import LIQUIDITY_FACTOR
from astock_lens.universe.config import UniverseConfig
from astock_lens.universe.models import UniverseExclusion
from astock_lens.universe.prefilter import prefilter_listing


class ResearchUniverseState(DomainRecord):
    """Which symbols the research population holds, and what kept the rest out.

    Two counts are kept apart on purpose: the listing prefilter (what listing
    metadata alone allows) and the research universe (what the approved
    Universe rules admit once the liquidity measure exists). Collapsing them
    would hide where a symbol was dropped.
    """

    as_of: datetime
    listing_prefilter_symbols: tuple[str, ...]
    research_symbols: tuple[str, ...]
    excluded: tuple[UniverseExclusion, ...] = ()


def compute_research_universe(
    *,
    csv_root: Path,
    as_of: datetime,
    universe_config: UniverseConfig,
    factor_configs: Sequence[FactorConfig],
    dataset: str = DEFAULT_DATASET,
    securities_dataset: str = DEFAULT_SECURITIES_DATASET,
) -> ResearchUniverseState:
    """Materialize the research population before anything expensive happens.

    Only the liquidity factor is computed here. The research population decides
    *which* symbols are worth measuring, so computing the other 23 factors first
    would spend the run's most expensive work on symbols that may never enter
    the research population at all.

    `dataset` / `securities_dataset` are the same knobs the rest of the pipeline
    exposes, so a caller can point this at whatever the daily run would read.
    """
    outcome = normalize_stage(
        csv_root=csv_root,
        as_of=as_of,
        dataset=dataset,
        securities_dataset=securities_dataset,
    )
    prefiltered = prefilter_listing(
        outcome.securities, config=universe_config, as_of=as_of
    )

    liquidity_configs = tuple(
        config for config in factor_configs if config.name == LIQUIDITY_FACTOR
    )
    if not liquidity_configs:
        raise ValueError(
            f"the research universe needs the {LIQUIDITY_FACTOR} factor "
            "configuration: the Universe's liquidity rule consumes it"
        )
    liquidity_results = factor_stage(
        outcome=outcome, factor_configs=liquidity_configs, as_of=as_of
    )
    snapshot = universe_stage(
        outcome=outcome,
        factor_results=liquidity_results,
        config=universe_config,
        as_of=as_of,
    )
    return ResearchUniverseState(
        as_of=as_of,
        listing_prefilter_symbols=prefiltered.included,
        research_symbols=snapshot.included,
        excluded=snapshot.exclusions,
    )


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


def run_research_analysis(
    *,
    csv_root: Path,
    as_of: datetime,
    universe_config: UniverseConfig,
    factor_configs: Sequence[FactorConfig],
    scanners: Sequence[RegisteredStrategy],
    dataset: str = DEFAULT_DATASET,
    securities_dataset: str = DEFAULT_SECURITIES_DATASET,
) -> tuple[ResearchUniverseState, AnalysisState]:
    """Run the canonical chain on the Research Universe, and only on it.

    Same stages as `run_analysis` — nothing is reimplemented — but the expensive
    part is narrowed in the one place it matters: the 24 factors are computed
    for the research population, not for every symbol that happens to have a
    bar. Calibration and the production scan must rank the same population, so
    they must also be able to *compute* on the same population.

    Returns both the population decision and the analysis it produced, because
    a calibration report has to show the population it was computed on.
    """
    state = compute_research_universe(
        csv_root=csv_root,
        as_of=as_of,
        universe_config=universe_config,
        factor_configs=factor_configs,
        dataset=dataset,
        securities_dataset=securities_dataset,
    )
    outcome = normalize_stage(
        csv_root=csv_root,
        as_of=as_of,
        dataset=dataset,
        securities_dataset=securities_dataset,
    )
    research = set(state.research_symbols)
    narrowed = outcome.bars.model_copy(
        update={
            "daily_bars": tuple(
                bar for bar in outcome.bars.daily_bars if bar.symbol in research
            ),
            "observations": tuple(
                row for row in outcome.bars.observations if row.symbol in research
            ),
            "valuations": tuple(
                row for row in outcome.bars.valuations if row.symbol in research
            ),
        }
    )
    narrowed_outcome = outcome.model_copy(update={"bars": narrowed, "securities": ()})

    factor_results = factor_stage(
        outcome=narrowed_outcome, factor_configs=factor_configs, as_of=as_of
    )
    universe = universe_stage(
        outcome=outcome,
        factor_results=factor_results,
        config=universe_config,
        as_of=as_of,
    )
    strategy_results = strategy_stage(
        scanners=scanners,
        universe=universe,
        factor_results=factor_results,
        as_of=as_of,
    )
    return state, AnalysisState(
        as_of=as_of,
        outcome=outcome,
        universe=universe,
        factor_results=factor_results,
        strategy_results=strategy_results,
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
