"""The daily pipeline's stages, one callable each.

`spec §15` names the stages and requires each one to be independently
restartable. Splitting them here gives the `daily` pipeline something it can
time, count and record per stage, and gives a test or an operator a way to run
one stage without pretending to run the rest.

Ordering inside a run is load-bearing: factors are computed before the
Universe, because the Universe's liquidity rule consumes the `avg_amount_20d`
factor. Recomputing turnover inside the Universe would create a second
definition of the same quantity, so the design's listed order is deviated from
deliberately and the deviation is recorded in `docs/REVIEW_NOTES.md`.
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.models import Candidate
from astock_lens.candidates.routing import route_candidate_actions
from astock_lens.data.contracts import (
    FetchRequest,
    NormalizedDataset,
    RawDataset,
)
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.quality.gate import (
    DailyBarQualityGate,
    QualityReport,
    valid_bars,
)
from astock_lens.domain.models import DomainRecord, SecurityProfile, SnapshotLineage
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorContext, FactorResult
from astock_lens.factors.registry import build_registry
from astock_lens.strategies.contracts import StrategyContext, StrategyResult
from astock_lens.strategies.registry import RegisteredStrategy
from astock_lens.universe.builder import LIQUIDITY_FACTOR, UniverseBuilder
from astock_lens.universe.config import UniverseConfig
from astock_lens.universe.models import UniverseSnapshot

DEFAULT_DATASET = "daily_bars"
DEFAULT_SECURITIES_DATASET = "securities"


class NormalizeOutcome(DomainRecord):
    """What NORMALIZE produced, with the raw metadata it came from.

    The raw datasets are kept on the outcome so a later stage — Data Health, or
    the job record — can report which provider dataset a run actually read
    without fetching anything again.
    """

    raw_bars: RawDataset
    raw_securities: RawDataset
    quality_report: QualityReport
    bars: NormalizedDataset
    securities: tuple[SecurityProfile, ...] = ()


def normalize_stage(
    *,
    csv_root: Path,
    as_of: datetime,
    dataset: str = DEFAULT_DATASET,
    securities_dataset: str = DEFAULT_SECURITIES_DATASET,
) -> NormalizeOutcome:
    """Fetch, normalize, and gate one point in time.

    Only bars the gate did not flag move on; the report still records what was
    set aside, so the removal stays visible.
    """
    provider = LocalCsvProvider(csv_root)
    raw_bars = provider.fetch(FetchRequest(dataset=dataset, as_of=as_of))
    raw_securities = provider.fetch(
        FetchRequest(dataset=securities_dataset, as_of=as_of)
    )

    normalized = CsvDailyBarNormalizer().normalize(raw_bars, as_of=as_of)
    securities = CsvSecurityNormalizer().normalize(raw_securities, as_of=as_of)
    report = DailyBarQualityGate().check(normalized)

    gated = NormalizedDataset(
        dataset=normalized.dataset,
        as_of=normalized.as_of,
        daily_bars=valid_bars(normalized, report),
        parse_failures=normalized.parse_failures,
    )

    return NormalizeOutcome(
        raw_bars=raw_bars,
        raw_securities=raw_securities,
        quality_report=report,
        bars=gated,
        securities=securities.securities,
    )


def factor_stage(
    *,
    outcome: NormalizeOutcome,
    factor_configs: Sequence[FactorConfig],
    as_of: datetime,
) -> tuple[FactorResult, ...]:
    """Compute every configured factor for every symbol that has bars."""
    registry = build_registry(factor_configs)
    # The registry fixes the order once, so every symbol is measured by the
    # same factors in the same sequence.
    factors = [registry.get(name) for name in registry.names()]

    results: list[FactorResult] = []
    for symbol in symbols_of(outcome.bars):
        results.extend(
            factor.compute(
                FactorContext(symbol=symbol, as_of=as_of, dataset=outcome.bars)
            )
            for factor in factors
        )
    return tuple(results)


def universe_stage(
    *,
    outcome: NormalizeOutcome,
    factor_results: Sequence[FactorResult],
    config: UniverseConfig,
    as_of: datetime,
) -> UniverseSnapshot:
    """Apply every Universe rule and record the verdicts."""
    return UniverseBuilder(config).build(
        outcome.securities,
        as_of=as_of,
        bars=outcome.bars.daily_bars,
        liquidity=liquidity_by_symbol(factor_results),
    )


def strategy_stage(
    *,
    scanners: Sequence[RegisteredStrategy],
    universe: UniverseSnapshot,
    factor_results: Sequence[FactorResult],
    as_of: datetime,
) -> tuple[StrategyResult, ...]:
    """Score the admitted symbols with every scanner, one cross-section each.

    Only admitted symbols enter: the cross-section is the population the
    Universe says the scan considers, no more and no less, so an excluded
    symbol can never be scored behind its back.
    """
    results: list[StrategyResult] = []
    for scanner in scanners:
        contexts = [
            StrategyContext(
                symbol=symbol,
                as_of=as_of,
                factors=results_for(factor_results, symbol),
            )
            for symbol in universe.included
        ]
        results.extend(scanner.plugin.score_cross_section(contexts))
    return tuple(results)


def candidate_stage(
    *,
    strategy_results: Sequence[StrategyResult],
    lineage: SnapshotLineage,
    as_of: datetime,
) -> tuple[Candidate, ...]:
    """Build one candidate per symbol that at least one scanner found eligible.

    Evidence from every scanner that fired for the symbol travels together, so
    a candidate can say which strategies explain it.
    """
    builder = CandidateBuilder()
    by_symbol: dict[str, list[StrategyResult]] = {}
    for result in strategy_results:
        if result.eligible:
            by_symbol.setdefault(result.symbol, []).append(result)

    return tuple(
        builder.build(
            symbol,
            as_of=as_of,
            strategy_results=tuple(found),
            lineage=lineage,
            next_action=route_candidate_actions(found),
        )
        for symbol, found in by_symbol.items()
    )


def factor_versions(factor_configs: Sequence[FactorConfig]) -> tuple[str, ...]:
    """Return the distinct factor versions a configuration set implies."""
    registry = build_registry(factor_configs)
    return tuple(
        sorted({registry.get(name).metadata.version for name in registry.names()})
    )


def lineage_for(
    *,
    universe: UniverseSnapshot,
    factor_configs: Sequence[FactorConfig],
    scanners: Sequence[RegisteredStrategy],
) -> SnapshotLineage:
    """Describe what produced a run, so its result can be reproduced."""
    return SnapshotLineage(
        universe_snapshot=universe.snapshot_id,
        factor_version=",".join(factor_versions(factor_configs)),
        strategy_version=",".join(
            sorted({scanner.config.version for scanner in scanners})
        ),
    )


def liquidity_by_symbol(
    factor_results: Sequence[FactorResult],
) -> dict[str, FactorResult]:
    """One liquidity measure per symbol, from the factors already computed."""
    return {
        result.symbol: result
        for result in factor_results
        if result.factor == LIQUIDITY_FACTOR
    }


def results_for(
    factor_results: Sequence[FactorResult], symbol: str
) -> tuple[FactorResult, ...]:
    """Every factor result for one symbol."""
    return tuple(result for result in factor_results if result.symbol == symbol)


def symbols_of(dataset: NormalizedDataset) -> tuple[str, ...]:
    """Return the dataset's symbols in a stable order."""
    return tuple(sorted({bar.symbol for bar in dataset.daily_bars}))
