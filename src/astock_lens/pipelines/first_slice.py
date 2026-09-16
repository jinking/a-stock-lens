"""The first vertical slice, wired end to end.

One callable drives the whole chain:

    CSV → RawDataset → NormalizedDataset → QualityReport → FactorResult
        → StrategyResult → Candidate → snapshot

The CLI and the integration test both call this function, so there is one code
path rather than two that drift apart.

Every configured factor is computed and handed to the scanner, which then uses
the subset it declares in `required_factors`. Adding a factor is therefore a
configuration change rather than an engine change.

The slice stops where the design stops: it builds Candidates, and it does not
touch the Universe, the Watchlist lifecycle, the market layer, or the signal
layer. `run_daily_scan` adds the Universe and the cross-sectional ranking;
this function stays as the minimal proof that the chain runs.
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.models import Candidate
from astock_lens.candidates.routing import route_next_action
from astock_lens.data.contracts import FetchRequest, NormalizedDataset
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.quality.gate import (
    DailyBarQualityGate,
    QualityReport,
    valid_bars,
)
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.domain.enums import SnapshotKind
from astock_lens.domain.models import DomainRecord, SnapshotLineage
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorContext, FactorResult
from astock_lens.factors.registry import build_registry
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import StrategyContext, StrategyResult
from astock_lens.strategies.momentum import MomentumScanner

DEFAULT_DATASET = "daily_bars"


class FirstSliceResult(DomainRecord):
    """Everything one run produced, plus where its snapshots landed."""

    as_of: datetime
    quality_report: QualityReport
    factor_snapshot_path: Path
    candidate_snapshot_path: Path
    factor_results: tuple[FactorResult, ...] = ()
    strategy_results: tuple[StrategyResult, ...] = ()
    candidates: tuple[Candidate, ...] = ()


def run_first_slice(
    *,
    csv_root: Path,
    as_of: datetime,
    factor_configs: Sequence[FactorConfig],
    strategy_config: StrategyConfig,
    store: SnapshotStore,
    dataset: str = DEFAULT_DATASET,
) -> FirstSliceResult:
    """Run the slice once for one point in time.

    Configuration is passed in rather than loaded here, so a caller can see
    exactly which factor windows and strategy version a run used.
    """
    raw = LocalCsvProvider(csv_root).fetch(FetchRequest(dataset=dataset, as_of=as_of))
    normalized = CsvDailyBarNormalizer().normalize(raw, as_of=as_of)
    report = DailyBarQualityGate().check(normalized)

    # Only bars the gate did not flag reach the factor engine. The report still
    # records what was set aside, so the removal stays visible.
    gated = NormalizedDataset(
        dataset=normalized.dataset,
        as_of=normalized.as_of,
        daily_bars=valid_bars(normalized, report),
        parse_failures=normalized.parse_failures,
    )

    registry = build_registry(factor_configs)
    # The registry fixes the order once, so every symbol is measured by the
    # same factors in the same sequence.
    factors = [registry.get(name) for name in registry.names()]
    scanner = MomentumScanner(strategy_config)
    builder = CandidateBuilder()
    lineage = SnapshotLineage(
        factor_version=",".join(
            sorted({factor.metadata.version for factor in factors})
        ),
        strategy_version=strategy_config.version,
    )

    factor_results: list[FactorResult] = []
    strategy_results: list[StrategyResult] = []
    candidates: list[Candidate] = []

    for symbol in _symbols(gated):
        symbol_results = tuple(
            factor.compute(FactorContext(symbol=symbol, as_of=as_of, dataset=gated))
            for factor in factors
        )
        factor_results.extend(symbol_results)

        strategy_result = scanner.score(
            StrategyContext(symbol=symbol, as_of=as_of, factors=symbol_results)
        )
        strategy_results.append(strategy_result)

        if strategy_result.eligible:
            candidates.append(
                builder.build(
                    symbol,
                    as_of=as_of,
                    strategy_results=(strategy_result,),
                    lineage=lineage,
                    next_action=route_next_action(strategy_result),
                )
            )

    return FirstSliceResult(
        as_of=as_of,
        quality_report=report,
        factor_results=tuple(factor_results),
        strategy_results=tuple(strategy_results),
        candidates=tuple(candidates),
        factor_snapshot_path=store.write(SnapshotKind.FACTOR, as_of, factor_results),
        candidate_snapshot_path=store.write(SnapshotKind.CANDIDATE, as_of, candidates),
    )


def _symbols(dataset: NormalizedDataset) -> tuple[str, ...]:
    """Return the dataset's symbols in a stable order."""
    return tuple(sorted({bar.symbol for bar in dataset.daily_bars}))
