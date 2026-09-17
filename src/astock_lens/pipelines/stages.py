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
    RawPayload,
)
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.normalize.financials import (
    FinancialNormalizeOutcome,
    FinancialStatementNormalizer,
)
from astock_lens.data.normalize.valuations import (
    NeodataValuationNormalizer,
    ValuationFailure,
)
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.providers.westock import FINANCIAL_DATASETS
from astock_lens.data.quality.financial_gate import (
    FinancialQualityGate,
    FinancialQualityReport,
    usable_observations,
)
from astock_lens.data.quality.gate import (
    DailyBarQualityGate,
    QualityReport,
    valid_bars,
)
from astock_lens.data.sync import latest_neodata_file, read_raw_rows
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import (
    DomainRecord,
    FinancialObservation,
    SecurityProfile,
    SnapshotLineage,
    ValuationObservation,
)
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


class FinancialInputs(DomainRecord):
    """Normalized and gated fundamentals for one point in time.

    `observations` holds only what survived the gate; the per-dataset outcomes
    and reports keep everything the gate rejected visible, and
    `absent_datasets` names the statements that were never landed at all.
    """

    outcomes: tuple[FinancialNormalizeOutcome, ...] = ()
    reports: tuple[FinancialQualityReport, ...] = ()
    observations: tuple[FinancialObservation, ...] = ()
    absent_datasets: tuple[str, ...] = ()


class ValuationInputs(DomainRecord):
    """某一时点可用的估值观测，以及它们来自哪一天的取数。

    `source_file` 为 `None` 表示还没有落过估值数据——这是一个**可见**的事实，
    而不是"市场没有估值"。
    """

    as_of: datetime
    source_file: Path | None = None
    observations: tuple[ValuationObservation, ...] = ()
    absent_metrics: tuple[str, ...] = ()
    failures: tuple[ValuationFailure, ...] = ()


class DatasetIndex:
    """Per-symbol views of one normalized dataset, indexed once.

    Handing every factor the whole market would make each call scan the full
    dataset — at whole-market size (5,565 symbols, 2.1M observations) that is
    quadratic and unusable. It is also the wrong statement of what a factor may
    read: a factor is asked about one symbol, so its context holds that symbol.
    """

    def __init__(self, dataset: NormalizedDataset) -> None:
        self._dataset = dataset
        self._bars = _group_by_symbol(dataset.daily_bars)
        self._observations = _group_by_symbol(dataset.observations)
        self._valuations = _group_by_symbol(dataset.valuations)

    def for_symbol(self, symbol: str) -> NormalizedDataset:
        """Return the dataset restricted to one instrument."""
        return self._dataset.model_copy(
            update={
                "daily_bars": self._bars.get(symbol, ()),
                "observations": self._observations.get(symbol, ()),
                "valuations": self._valuations.get(symbol, ()),
            }
        )


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
    financials: FinancialInputs = FinancialInputs()
    valuations: ValuationInputs | None = None


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

    financials = financial_inputs(csv_root, as_of=as_of)
    valuations = valuation_inputs(csv_root, as_of=as_of)

    gated = NormalizedDataset(
        dataset=normalized.dataset,
        as_of=normalized.as_of,
        daily_bars=valid_bars(normalized, report),
        # The factor engine reads one normalized dataset per symbol context, so
        # the fundamentals travel with the bars rather than beside them.
        observations=financials.observations,
        valuations=valuations.observations,
        parse_failures=normalized.parse_failures,
    )

    return NormalizeOutcome(
        raw_bars=raw_bars,
        raw_securities=raw_securities,
        quality_report=report,
        bars=gated,
        securities=securities.securities,
        financials=financials,
        valuations=valuations,
    )


def financial_inputs(csv_root: Path, *, as_of: datetime) -> FinancialInputs:
    """Normalize and gate every landed financial statement.

    A statement that was never landed is named in `absent_datasets` rather than
    treated as an empty one: "nobody synced the balance sheet" and "the balance
    sheet had nothing in it" are different facts, and a factor has to be able
    to tell them apart.
    """
    provider = LocalCsvProvider(csv_root)
    normalizer = FinancialStatementNormalizer()
    gate = FinancialQualityGate()

    outcomes: list[FinancialNormalizeOutcome] = []
    reports: list[FinancialQualityReport] = []
    usable: list[FinancialObservation] = []
    absent: list[str] = []

    for dataset in sorted(FINANCIAL_DATASETS):
        raw = provider.fetch(FetchRequest(dataset=dataset, as_of=as_of))
        if raw.payload is None or not raw.payload.rows:
            absent.append(dataset)
            continue

        outcome = normalizer.normalize(raw, as_of=as_of)
        report = gate.check(
            outcome.observations,
            dataset=dataset,
            as_of=as_of,
            failures=outcome.failures,
        )
        outcomes.append(outcome)
        reports.append(report)
        usable.extend(usable_observations(outcome.observations, report))

    return FinancialInputs(
        outcomes=tuple(outcomes),
        reports=tuple(reports),
        observations=tuple(usable),
        absent_datasets=tuple(absent),
    )


def valuation_inputs(csv_root: Path, *, as_of: datetime) -> ValuationInputs:
    """读取不晚于 `as_of` 的最新一天 neodata 估值落地，并归一化。

    时点由文件选择保证：未来日期的文件不会被读到（`latest_neodata_file`
    按 ISO 文件名比较）。没有落地过任何估值数据时 `source_file` 为 `None`——
    这是"还没同步"，与"市场没有估值"是两回事，因子层会因此报
    `NOT_APPLICABLE`，而不是把缺失当成 0。
    """
    path = latest_neodata_file(csv_root, "valuation", as_of=as_of)
    if path is None:
        return ValuationInputs(as_of=as_of)

    columns, rows = read_raw_rows(path)
    if not columns:
        return ValuationInputs(as_of=as_of, source_file=path)

    raw = RawDataset(
        provider="neodata",
        dataset="valuation",
        fetched_at=as_of,
        provider_version="v1",
        status=DataStatus.VALUE,
        row_count=len(rows),
        payload=RawPayload(columns=columns, rows=rows),
    )
    outcome = NeodataValuationNormalizer().normalize(raw, as_of=as_of)
    return ValuationInputs(
        as_of=as_of,
        source_file=path,
        observations=outcome.observations,
        absent_metrics=outcome.absent_metrics,
        failures=outcome.failures,
    )


def factor_stage(
    *,
    outcome: NormalizeOutcome,
    factor_configs: Sequence[FactorConfig],
    as_of: datetime,
) -> tuple[FactorResult, ...]:
    """Compute every configured factor for every symbol that has bars.

    Each symbol's context carries only that symbol's rows. Handing every factor
    the whole market would make each call scan the full dataset — at
    whole-market size (5,565 symbols, 2.1M observations) that is quadratic and
    unusable, and it is also the wrong statement of what a factor may read.
    """
    registry = build_registry(factor_configs)
    # The registry fixes the order once, so every symbol is measured by the
    # same factors in the same sequence.
    factors = [registry.get(name) for name in registry.names()]
    index = DatasetIndex(outcome.bars)

    results: list[FactorResult] = []
    for symbol in symbols_of(outcome.bars):
        results.extend(
            factor.compute(
                FactorContext(
                    symbol=symbol, as_of=as_of, dataset=index.for_symbol(symbol)
                )
            )
            for factor in factors
        )
    return tuple(results)


def _group_by_symbol[T](items: Sequence[T]) -> dict[str, tuple[T, ...]]:
    """Index records by their symbol, keeping the original order."""
    grouped: dict[str, list[T]] = {}
    for item in items:
        grouped.setdefault(item.symbol, []).append(item)  # type: ignore[attr-defined]
    return {symbol: tuple(found) for symbol, found in grouped.items()}


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
