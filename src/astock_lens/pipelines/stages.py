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

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from astock_lens.candidates.builder import CandidateBuilder
from astock_lens.candidates.models import Candidate
from astock_lens.candidates.policy import (
    CANDIDATE_POLICY_DEFERRED,
    CandidateEvidence,
    CandidateEvidenceIncomplete,
    CandidatePolicy,
    CandidatePolicyNotConfigured,
)
from astock_lens.data.contracts import NormalizedDataset
from astock_lens.data.repository.contracts import NormalizedRepository
from astock_lens.data.repository.csv import CsvNormalizedRepository
from astock_lens.data.repository.models import (
    FinancialInputs,
    NormalizeOutcome,
    ValuationInputs,
)
from astock_lens.domain.enums import MarketRegime, MarketValidation, Signal
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorContext, FactorResult
from astock_lens.factors.registry import build_registry
from astock_lens.market.regime import (
    MarketRegimeContext,
    MarketRegimeDetector,
    MarketRegimeResult,
)
from astock_lens.market.validation import (
    MarketValidationContext,
    MarketValidationResult,
    MarketValidator,
)
from astock_lens.qualifications.contracts import (
    QualificationRuleNotConfigured,
    StrategyQualifier,
)
from astock_lens.qualifications.models import (
    QualificationContext,
    StrategyQualification,
)
from astock_lens.signals.contracts import SignalContext, SignalDetector, SignalResult
from astock_lens.signals.detector import DefaultSignalDetector
from astock_lens.strategies.contracts import StrategyContext, StrategyResult
from astock_lens.strategies.registry import RegisteredStrategy
from astock_lens.universe.builder import LIQUIDITY_FACTOR, UniverseBuilder
from astock_lens.universe.config import UniverseConfig
from astock_lens.universe.models import UniverseSnapshot

# 三个模型搬去了 `data/repository/models.py`（它们描述数据，不描述计算），但
# `pipelines.stages` 上的老 import 路径必须继续可用——调用方不该因为一次内部
# 搬家而改代码。
__all__ = [
    "DEFAULT_DATASET",
    "DEFAULT_SECURITIES_DATASET",
    "DatasetIndex",
    "FactorResultIndex",
    "FinancialInputs",
    "NormalizeOutcome",
    "ValuationInputs",
    "candidate_stage",
    "factor_stage",
    "factor_versions",
    "financial_inputs",
    "lineage_for",
    "liquidity_by_symbol",
    "market_regime_stage",
    "market_validation_stage",
    "normalize_stage",
    "qualification_stage",
    "signal_stage",
    "strategy_stage",
    "symbols_of",
    "universe_stage",
    "valuation_inputs",
]

DEFAULT_DATASET = "daily_bars"
DEFAULT_SECURITIES_DATASET = "securities"


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
        self._dividends = _group_by_symbol(dataset.dividend_events)

    def for_symbol(self, symbol: str) -> NormalizedDataset:
        """Return the dataset restricted to one instrument."""
        return self._dataset.model_copy(
            update={
                "daily_bars": self._bars.get(symbol, ()),
                "observations": self._observations.get(symbol, ()),
                "valuations": self._valuations.get(symbol, ()),
                "dividend_events": self._dividends.get(symbol, ()),
            }
        )


def normalize_stage(
    *,
    csv_root: Path,
    as_of: datetime,
    dataset: str = DEFAULT_DATASET,
    securities_dataset: str = DEFAULT_SECURITIES_DATASET,
    repository: NormalizedRepository | None = None,
) -> NormalizeOutcome:
    """Fetch, normalize, and gate one point in time.

    `repository` 是读取边界的注入点。为 `None` 时用 CSV 回放实现——与迁移前
    完全相同的一条路；显式传入时**只**从它读。

    注入时不再回头看 `csv_root`：一个读不到的仓库必须让分析失败，而不是被
    一次静默的 CSV 兜底掩盖。`csv_root` 仍然保留在签名里，是为了让"注入"是
    加法而不是改签名，老调用方一个字都不用动。
    """
    source = repository if repository is not None else CsvNormalizedRepository(csv_root)
    return source.read(
        as_of=as_of, dataset=dataset, securities_dataset=securities_dataset
    )


def financial_inputs(csv_root: Path, *, as_of: datetime) -> FinancialInputs:
    """兼容转发：老的按 root 调用方式不变，算法在 `repository.csv` 里。"""
    return CsvNormalizedRepository(csv_root).financial_inputs(as_of=as_of)


def valuation_inputs(csv_root: Path, *, as_of: datetime) -> ValuationInputs:
    """兼容转发：老的按 root 调用方式不变，算法在 `repository.csv` 里。"""
    return CsvNormalizedRepository(csv_root).valuation_inputs(as_of=as_of)


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


class FactorResultIndex:
    """Answer "this symbol's factor results" without rescanning the list.

    The strategy stage asks that question once per (scanner, symbol) pair.
    Answering it with a linear scan of every factor result turns a run into
    O(scanners × symbols × factor results); building the map once makes the
    lookups free. The mapping keeps the input order inside each symbol, so a
    cross-section sees exactly the sequence it saw before.
    """

    def __init__(self, results: Sequence[FactorResult]) -> None:
        grouped: dict[str, list[FactorResult]] = {}
        for result in results:
            grouped.setdefault(result.symbol, []).append(result)
        self._by_symbol = {symbol: tuple(items) for symbol, items in grouped.items()}

    def for_symbol(self, symbol: str) -> tuple[FactorResult, ...]:
        """Every factor result for one symbol; empty when the symbol has none."""
        return self._by_symbol.get(symbol, ())


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
    # One pass over the factor results for the whole stage. Every scanner sees
    # the same cross-section, so the lookup table is built once and reused
    # instead of rescanned for each (scanner, symbol) pair.
    index = FactorResultIndex(factor_results)

    results: list[StrategyResult] = []
    for scanner in scanners:
        contexts = [
            StrategyContext(
                symbol=symbol,
                as_of=as_of,
                factors=index.for_symbol(symbol),
            )
            for symbol in universe.included
        ]
        results.extend(scanner.plugin.score_cross_section(contexts))
    return tuple(results)


def qualification_stage(
    *,
    strategy_results: Sequence[StrategyResult],
    factor_results: Sequence[FactorResult],
    qualifiers: Mapping[str, StrategyQualifier],
) -> tuple[StrategyQualification, ...]:
    """Evaluate eligible strategy results against their strategy's qualifier.

    - Only results with eligible=True are evaluated.
    - Every eligible result's strategy_id must be in qualifiers.
    - Missing qualifier raises QualificationRuleNotConfigured.
    - No candidate objects are created here.

    Qualification reads the symbol's **complete** Factor evidence
    (``factor_results``), not just the strategy's scoring snapshot, so an
    approved non-scoring factor stays available to the absolute rule. The
    per-symbol index is built once to avoid rescanning the whole list.
    """
    index = FactorResultIndex(factor_results)

    qualifications: list[StrategyQualification] = []
    for result in strategy_results:
        if not result.eligible:
            continue
        qualifier = qualifiers.get(result.strategy_id)
        if qualifier is None:
            raise QualificationRuleNotConfigured(
                f"No qualifier configured for strategy '{result.strategy_id}'"
            )
        context = QualificationContext(
            strategy_result=result,
            factors=index.for_symbol(result.symbol),
        )
        qualifications.append(qualifier.qualify(context))
    return tuple(qualifications)


def candidate_stage(
    *,
    strategy_results: Sequence[StrategyResult],
    qualifications: Sequence[StrategyQualification] = (),
    market_validation_by_symbol: Mapping[str, MarketValidation] | None = None,
    signal_by_symbol: Mapping[str, Signal] | None = None,
    lineage: SnapshotLineage,
    as_of: datetime,
    policy: CandidatePolicy | None,
) -> tuple[Candidate, ...]:
    """Select and assemble research candidates from cross-sectional evidence.

    - Fails clearly when policy is missing (CandidatePolicyNotConfigured).
    - Builds one CandidateEvidence per symbol that has at least one qualified StrategyQualification.
    - Fails incomplete evidence instead of synthesizing NEUTRAL/NO_SIGNAL:
      If symbol not in market_validation_by_symbol or market_validation is None,
      or symbol not in signal_by_symbol or signal is None -> CandidateEvidenceIncomplete.
    - Calls policy.select(evidence_list) once for the whole cross-section.
    - Builds Candidates only for returned selections.
    """
    if policy is None:
        raise CandidatePolicyNotConfigured(CANDIDATE_POLICY_DEFERRED)

    mv_by_symbol = (
        market_validation_by_symbol if market_validation_by_symbol is not None else {}
    )
    sig_by_symbol = signal_by_symbol if signal_by_symbol is not None else {}

    quals_by_symbol: dict[str, list[StrategyQualification]] = {}
    for q in qualifications:
        quals_by_symbol.setdefault(q.symbol, []).append(q)

    results_by_symbol: dict[str, list[StrategyResult]] = {}
    for r in strategy_results:
        results_by_symbol.setdefault(r.symbol, []).append(r)

    # Find symbols that have at least one qualified StrategyQualification
    candidate_symbols = sorted(
        sym for sym, quals in quals_by_symbol.items() if any(q.qualified for q in quals)
    )

    evidence_list: list[CandidateEvidence] = []
    for sym in candidate_symbols:
        mv = mv_by_symbol.get(sym)
        sig = sig_by_symbol.get(sym)
        if mv is None or sig is None:
            raise CandidateEvidenceIncomplete(
                f"CandidateEvidence for symbol '{sym}' is incomplete: "
                f"market_validation={mv}, signal={sig}"
            )
        evidence = CandidateEvidence(
            symbol=sym,
            strategy_results=tuple(results_by_symbol.get(sym, ())),
            strategy_qualifications=tuple(quals_by_symbol.get(sym, ())),
            market_validation=mv,
            signal=sig,
        )
        evidence_list.append(evidence)

    selections = policy.select(evidence_list)

    evidence_by_symbol = {e.symbol: e for e in evidence_list}
    builder = CandidateBuilder()
    candidates: list[Candidate] = []
    for sel in selections:
        ev = evidence_by_symbol[sel.symbol]
        candidates.append(
            builder.build(
                evidence=ev,
                selection=sel,
                as_of=as_of,
                lineage=lineage,
            )
        )
    return tuple(candidates)


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


def symbols_of(dataset: NormalizedDataset) -> tuple[str, ...]:
    """Return the dataset's symbols in a stable order."""
    return tuple(sorted({bar.symbol for bar in dataset.daily_bars}))


def market_regime_stage(
    *,
    as_of: datetime,
    breadth_ratio: float | None = None,
    index_trend: float | None = None,
    extreme_volatility: bool = False,
    detector: MarketRegimeDetector | None = None,
) -> MarketRegimeResult:
    """Detect market regime state."""
    active_detector = detector or MarketRegimeDetector()
    context = MarketRegimeContext(
        as_of=as_of,
        breadth_ratio=breadth_ratio,
        index_trend=index_trend,
        extreme_volatility=extreme_volatility,
    )
    return active_detector.detect(context)


def market_validation_stage(
    *,
    symbols: Sequence[str],
    factor_results: Sequence[FactorResult],
    as_of: datetime,
    strategy_id: str = "momentum",
    validator: MarketValidator | None = None,
) -> tuple[MarketValidationResult, ...]:
    """Validate candidate market behavior against the 5-dimension matrix."""
    active_validator = validator or MarketValidator()
    index = FactorResultIndex(factor_results)
    results: list[MarketValidationResult] = []
    for sym in symbols:
        factors = index.for_symbol(sym)
        context = MarketValidationContext(
            symbol=sym,
            strategy_id=strategy_id,
            as_of=as_of,
            factors=factors,
        )
        results.append(active_validator.validate(context))
    return tuple(results)


def signal_stage(
    *,
    symbols: Sequence[str],
    factor_results: Sequence[FactorResult],
    as_of: datetime,
    strategy_id: str | None = None,
    strategy_by_symbol: Mapping[str, str] | None = None,
    market_regime: MarketRegime | None = None,
    detector: SignalDetector | None = None,
) -> tuple[SignalResult, ...]:
    """Detect technical market state signals."""
    active_detector = detector or DefaultSignalDetector()
    index = FactorResultIndex(factor_results)
    results: list[SignalResult] = []
    for sym in symbols:
        factors = index.for_symbol(sym)
        sid = (
            strategy_by_symbol.get(sym)
            if strategy_by_symbol is not None
            else strategy_id
        )
        context = SignalContext(
            symbol=sym,
            as_of=as_of,
            factors=factors,
            market_regime=market_regime,
            strategy_id=sid,
        )
        results.append(active_detector.detect(context))
    return tuple(results)
