"""The daily scan, wired end to end.

One callable drives the chain the architecture names:

    NORMALIZE → BUILD_UNIVERSE → COMPUTE_FACTORS → RUN_STRATEGIES
        → BUILD_CANDIDATES → snapshots

Ordering inside the pipeline is load-bearing. Factors are computed for every
symbol that has bars, because the Universe's liquidity rule consumes the
`avg_amount_20d` factor — recomputing turnover inside the Universe would
create a second definition of the same quantity. Only symbols the Universe
admitted then enter the strategy, so an excluded symbol can never be scored
behind its back, and the cross-sectional percentiles rank exactly the
population a reader was told the strategy considers.

Every stage writes its snapshot, so a run leaves an auditable trail even where
it produced nothing.
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.models import Candidate
from astock_lens.candidates.routing import route_next_action
from astock_lens.data.contracts import FetchRequest, NormalizedDataset
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.quality.gate import (
    DailyBarQualityGate,
    QualityReport,
    valid_bars,
)
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.domain.enums import SnapshotKind
from astock_lens.domain.models import DomainRecord, SecurityProfile, SnapshotLineage
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorContext, FactorResult
from astock_lens.factors.registry import build_registry
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import StrategyContext, StrategyResult
from astock_lens.strategies.momentum import MomentumScanner
from astock_lens.universe.builder import LIQUIDITY_FACTOR, UniverseBuilder
from astock_lens.universe.config import UniverseConfig
from astock_lens.universe.models import UniverseSnapshot

DEFAULT_DATASET = "daily_bars"
DEFAULT_SECURITIES_DATASET = "securities"


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
    gated, securities, report, factor_results = _prepare(
        csv_root,
        as_of=as_of,
        dataset=dataset,
        securities_dataset=securities_dataset,
        factor_configs=factor_configs,
    )

    universe = UniverseBuilder(universe_config).build(
        securities,
        as_of=as_of,
        bars=gated.daily_bars,
        liquidity=_liquidity(factor_results),
    )

    path = store.write(SnapshotKind.UNIVERSE, as_of, (universe,))
    return UniverseBuildResult(
        as_of=as_of,
        quality_report=report,
        universe=universe,
        universe_snapshot_path=path,
        factor_results=tuple(factor_results),
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
    gated, securities, report, factor_results = _prepare(
        csv_root,
        as_of=as_of,
        dataset=dataset,
        securities_dataset=securities_dataset,
        factor_configs=factor_configs,
    )

    universe = UniverseBuilder(universe_config).build(
        securities,
        as_of=as_of,
        bars=gated.daily_bars,
        liquidity=_liquidity(factor_results),
    )

    # Only admitted symbols are scored: the cross-section is the population
    # the Universe says the strategy considers, no more and no less.
    registry = build_registry(factor_configs)
    factors = [registry.get(name) for name in registry.names()]
    scanner = MomentumScanner(strategy_config)
    builder = CandidateBuilder()
    lineage = SnapshotLineage(
        universe_snapshot=universe.snapshot_id,
        factor_version=",".join(
            sorted({factor.metadata.version for factor in factors})
        ),
        strategy_version=strategy_config.version,
    )

    contexts = [
        StrategyContext(
            symbol=symbol,
            as_of=as_of,
            factors=_results_for(factor_results, symbol),
        )
        for symbol in universe.included
    ]
    strategy_results = scanner.score_cross_section(contexts)

    candidates = [
        builder.build(
            result.symbol,
            as_of=as_of,
            strategy_results=(result,),
            lineage=lineage,
            next_action=route_next_action(result),
        )
        for result in strategy_results
        if result.eligible
    ]

    universe_path = store.write(SnapshotKind.UNIVERSE, as_of, (universe,))
    factor_path = store.write(SnapshotKind.FACTOR, as_of, factor_results)
    strategy_path = store.write(SnapshotKind.STRATEGY, as_of, strategy_results)
    candidate_path = store.write(SnapshotKind.CANDIDATE, as_of, candidates)

    return DailyScanResult(
        as_of=as_of,
        quality_report=report,
        universe=universe,
        universe_snapshot_path=universe_path,
        factor_snapshot_path=factor_path,
        strategy_snapshot_path=strategy_path,
        candidate_snapshot_path=candidate_path,
        factor_results=tuple(factor_results),
        strategy_results=tuple(strategy_results),
        candidates=tuple(candidates),
    )


def _prepare(
    csv_root: Path,
    *,
    as_of: datetime,
    dataset: str,
    securities_dataset: str,
    factor_configs: Sequence[FactorConfig],
) -> tuple[
    NormalizedDataset,
    tuple[SecurityProfile, ...],
    QualityReport,
    list[FactorResult],
]:
    """Fetch, normalize, gate, and measure — the stages every caller shares."""
    provider = LocalCsvProvider(csv_root)
    raw_bars = provider.fetch(FetchRequest(dataset=dataset, as_of=as_of))
    raw_securities = provider.fetch(
        FetchRequest(dataset=securities_dataset, as_of=as_of)
    )

    normalized_bars = CsvDailyBarNormalizer().normalize(raw_bars, as_of=as_of)
    securities = CsvSecurityNormalizer().normalize(raw_securities, as_of=as_of)
    report = DailyBarQualityGate().check(normalized_bars)

    # Only bars the gate did not flag reach the factor engine. The report
    # still records what was set aside, so the removal stays visible.
    gated = NormalizedDataset(
        dataset=normalized_bars.dataset,
        as_of=normalized_bars.as_of,
        daily_bars=valid_bars(normalized_bars, report),
        parse_failures=normalized_bars.parse_failures,
    )

    registry = build_registry(factor_configs)
    # The registry fixes the order once, so every symbol is measured by the
    # same factors in the same sequence.
    factors = [registry.get(name) for name in registry.names()]

    factor_results: list[FactorResult] = []
    for symbol in _symbols(gated):
        factor_results.extend(
            factor.compute(FactorContext(symbol=symbol, as_of=as_of, dataset=gated))
            for factor in factors
        )

    return gated, securities.securities, report, factor_results


def _liquidity(
    factor_results: Sequence[FactorResult],
) -> dict[str, FactorResult]:
    """One liquidity measure per symbol, from the factors already computed."""
    return {
        result.symbol: result
        for result in factor_results
        if result.factor == LIQUIDITY_FACTOR
    }


def _results_for(
    factor_results: Sequence[FactorResult], symbol: str
) -> tuple[FactorResult, ...]:
    return tuple(result for result in factor_results if result.symbol == symbol)


def _symbols(dataset: NormalizedDataset) -> tuple[str, ...]:
    """Return the dataset's symbols in a stable order."""
    return tuple(sorted({bar.symbol for bar in dataset.daily_bars}))
