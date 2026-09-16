"""The daily scan, wired end to end.

Two callables drive the chain the architecture names, built out of the same
stage functions so the CLI, `astock daily` and the tests share one
implementation:

    NORMALIZE → COMPUTE_FACTORS → BUILD_UNIVERSE → RUN_STRATEGIES
        → BUILD_CANDIDATES → snapshots

Ordering inside the pipeline is load-bearing. Factors are computed for every
symbol that has bars, because the Universe's liquidity rule consumes the
`avg_amount_20d` factor — recomputing turnover inside the Universe would
create a second definition of the same quantity. Only symbols the Universe
admitted then enter the strategy, so an excluded symbol can never be scored
behind its back, and the cross-sectional percentiles rank exactly the
population a reader was told the strategy considers.

Every stage writes its snapshot, so a run leaves an auditable trail even where
it produced nothing. `run_daily_scan` stops at the candidate snapshot; the
design's remaining stages live in `astock_lens.pipelines.daily`, which records
a job run for each one.
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from astock_lens.candidates.models import Candidate
from astock_lens.data.quality.gate import QualityReport
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.domain.enums import SnapshotKind
from astock_lens.domain.models import DomainRecord
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines.stages import (
    DEFAULT_DATASET,
    DEFAULT_SECURITIES_DATASET,
    candidate_stage,
    factor_stage,
    lineage_for,
    normalize_stage,
    strategy_stage,
    universe_stage,
)
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.momentum import MomentumScanner
from astock_lens.strategies.registry import RegisteredStrategy
from astock_lens.universe.config import UniverseConfig
from astock_lens.universe.models import UniverseSnapshot

__all__ = [
    "DEFAULT_DATASET",
    "DEFAULT_SECURITIES_DATASET",
    "DailyScanResult",
    "UniverseBuildResult",
    "build_universe",
    "run_daily_scan",
]


class UniverseBuildResult(DomainRecord):
    """The Universe stage on its own, plus where its snapshot landed."""

    as_of: datetime
    quality_report: QualityReport
    universe: UniverseSnapshot
    universe_snapshot_path: Path
    factor_results: tuple[FactorResult, ...] = ()


class DailyScanResult(DomainRecord):
    """Everything one scan produced, plus where its snapshots landed."""

    as_of: datetime
    quality_report: QualityReport
    universe: UniverseSnapshot
    universe_snapshot_path: Path
    factor_snapshot_path: Path
    strategy_snapshot_path: Path
    candidate_snapshot_path: Path
    factor_results: tuple[FactorResult, ...] = ()
    strategy_results: tuple[StrategyResult, ...] = ()
    candidates: tuple[Candidate, ...] = ()


def build_universe(
    *,
    csv_root: Path,
    as_of: datetime,
    universe_config: UniverseConfig,
    factor_configs: Sequence[FactorConfig],
    store: SnapshotStore,
    dataset: str = DEFAULT_DATASET,
    securities_dataset: str = DEFAULT_SECURITIES_DATASET,
) -> UniverseBuildResult:
    """Normalize, measure, and apply the Universe rules for one point in time."""
    outcome = normalize_stage(
        csv_root=csv_root,
        as_of=as_of,
        dataset=dataset,
        securities_dataset=securities_dataset,
    )
    factor_results = factor_stage(
        outcome=outcome, factor_configs=factor_configs, as_of=as_of
    )
    universe = universe_stage(
        outcome=outcome,
        factor_results=factor_results,
        config=universe_config,
        as_of=as_of,
    )

    path = store.write(SnapshotKind.UNIVERSE, as_of, (universe,))
    return UniverseBuildResult(
        as_of=as_of,
        quality_report=outcome.quality_report,
        universe=universe,
        universe_snapshot_path=path,
        factor_results=factor_results,
    )


def run_daily_scan(
    *,
    csv_root: Path,
    as_of: datetime,
    universe_config: UniverseConfig,
    factor_configs: Sequence[FactorConfig],
    strategy_config: StrategyConfig,
    store: SnapshotStore,
    dataset: str = DEFAULT_DATASET,
    securities_dataset: str = DEFAULT_SECURITIES_DATASET,
) -> DailyScanResult:
    """Run the whole daily chain once for one point in time.

    Configuration is passed in rather than loaded here, so a caller can see
    exactly which thresholds, factor windows, and strategy version a run used.
    """
    outcome = normalize_stage(
        csv_root=csv_root,
        as_of=as_of,
        dataset=dataset,
        securities_dataset=securities_dataset,
    )
    factor_results = factor_stage(
        outcome=outcome, factor_configs=factor_configs, as_of=as_of
    )
    universe = universe_stage(
        outcome=outcome,
        factor_results=factor_results,
        config=universe_config,
        as_of=as_of,
    )

    # Only admitted symbols are scored: the cross-section is the population
    # the Universe says the strategy considers, no more and no less.
    scanners = (
        RegisteredStrategy(
            config=strategy_config, plugin=MomentumScanner(strategy_config)
        ),
    )
    strategy_results = strategy_stage(
        scanners=scanners,
        universe=universe,
        factor_results=factor_results,
        as_of=as_of,
    )
    candidates = candidate_stage(
        strategy_results=strategy_results,
        lineage=lineage_for(
            universe=universe, factor_configs=factor_configs, scanners=scanners
        ),
        as_of=as_of,
    )

    universe_path = store.write(SnapshotKind.UNIVERSE, as_of, (universe,))
    factor_path = store.write(SnapshotKind.FACTOR, as_of, factor_results)
    strategy_path = store.write(SnapshotKind.STRATEGY, as_of, strategy_results)
    candidate_path = store.write(SnapshotKind.CANDIDATE, as_of, candidates)

    return DailyScanResult(
        as_of=as_of,
        quality_report=outcome.quality_report,
        universe=universe,
        universe_snapshot_path=universe_path,
        factor_snapshot_path=factor_path,
        strategy_snapshot_path=strategy_path,
        candidate_snapshot_path=candidate_path,
        factor_results=factor_results,
        strategy_results=strategy_results,
        candidates=candidates,
    )
