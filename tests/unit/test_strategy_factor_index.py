"""Factor lookup inside the strategy stage.

`strategy_stage` asks "which factor results belong to this symbol?" once per
(scanner, symbol) pair. Answering that by rescanning the whole factor list is
quadratic: 6 scanners × N symbols × 24·N results. The index answers the same
question from one pass.

Two properties matter and both are pinned here: the indexed answer is byte-for-
byte the same as a naive scan, and the factor list is walked exactly once no
matter how many scanners or symbols the run has. The second test uses a
counting sequence, so it fails against the old implementation for the right
reason rather than by inspecting code.
"""

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines.stages import FactorResultIndex, strategy_stage
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import StrategyContext, StrategyResult
from astock_lens.strategies.registry import RegisteredStrategy
from astock_lens.universe.models import UniverseSnapshot

AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
SYMBOLS = ("000001.SZ", "600519.SH", "300750.SZ", "688981.SH")
FACTORS = ("ret_20d", "ret_60d", "avg_amount_20d")


class CountingSequence(Sequence[FactorResult]):
    """A factor-result sequence that reports how often it was walked."""

    def __init__(self, items: Sequence[FactorResult]) -> None:
        self._items = tuple(items)
        self.iterations = 0

    def __iter__(self) -> Iterator[FactorResult]:
        self.iterations += 1
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> FactorResult:
        return self._items[index]


def _factor_results() -> tuple[FactorResult, ...]:
    return tuple(
        FactorResult(
            symbol=symbol,
            factor=factor,
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(),
            raw_value=float(index),
        )
        for symbol in SYMBOLS
        for index, factor in enumerate(FACTORS)
    )


def _universe() -> UniverseSnapshot:
    return UniverseSnapshot(
        as_of=AS_OF,
        snapshot_id="2026-09-17:test",
        config_digest="test",
        lineage=SnapshotLineage(universe_snapshot="2026-09-17:test"),
        included=SYMBOLS,
    )


class RecordingScanner:
    """A scanner that records the cross-section it was handed."""

    def __init__(self, strategy_id: str) -> None:
        self.strategy_id = strategy_id
        self.seen: list[tuple[str, tuple[str, ...]]] = []

    def required_factors(self) -> set[str]:
        return set(FACTORS)

    def score_cross_section(
        self, contexts: Sequence[StrategyContext]
    ) -> tuple[StrategyResult, ...]:
        self.seen.append(
            (
                contexts[0].symbol if contexts else "",
                tuple(
                    factor.factor for context in contexts for factor in context.factors
                ),
            )
        )
        return tuple(
            StrategyResult(
                symbol=context.symbol,
                strategy_id=self.strategy_id,
                strategy_version="v1",
                as_of=AS_OF,
                eligible=True,
                lineage=SnapshotLineage(),
                score=float(len(context.factors)),
            )
            for context in contexts
        )


def _scanners(count: int) -> tuple[RegisteredStrategy, ...]:
    scanners: list[RegisteredStrategy] = []
    for index in range(count):
        strategy_id = f"scanner_{index}"
        scanners.append(
            RegisteredStrategy(
                config=StrategyConfig(
                    id=strategy_id, version="v1", required_factors=FACTORS
                ),
                plugin=RecordingScanner(strategy_id),  # type: ignore[arg-type]
            )
        )
    return tuple(scanners)


def _naive_lookup(
    factor_results: Sequence[FactorResult], symbol: str
) -> tuple[FactorResult, ...]:
    """The oracle: what "this symbol's factor results" means, written out."""
    found: list[FactorResult] = []
    for result in factor_results:
        if result.symbol == symbol:
            found.append(result)
    return tuple(found)


def test_the_index_answers_exactly_like_a_naive_scan() -> None:
    results = _factor_results()
    index = FactorResultIndex(results)

    for symbol in SYMBOLS:
        assert index.for_symbol(symbol) == _naive_lookup(results, symbol)


def test_the_index_separates_symbols_and_keeps_input_order() -> None:
    results = _factor_results()
    index = FactorResultIndex(results)

    assert [result.factor for result in index.for_symbol("600519.SH")] == list(FACTORS)
    assert index.for_symbol("unknown.SZ") == ()


def test_strategy_stage_hands_each_symbol_its_own_factor_results() -> None:
    """The cross-section the scanners see is unchanged by the index."""
    results = _factor_results()
    scanners = _scanners(2)

    strategy_stage(
        scanners=scanners, universe=_universe(), factor_results=results, as_of=AS_OF
    )

    for scanner in scanners:
        plugin = scanner.plugin
        assert isinstance(plugin, RecordingScanner)
        assert len(plugin.seen) == 1
        _, factors_seen = plugin.seen[0]
        assert factors_seen == tuple(
            factor for symbol in SYMBOLS for factor in FACTORS
        ), "every admitted symbol must contribute exactly its own factors, in order"


def test_factor_results_are_walked_once_per_stage_not_once_per_scanner() -> None:
    """The anti-regression test.

    Three scanners over four symbols is twelve lookups. Walking the whole factor
    list for each of them is the quadratic behaviour this task removes.
    """
    counting = CountingSequence(_factor_results())

    strategy_stage(
        scanners=_scanners(3),
        universe=_universe(),
        factor_results=counting,
        as_of=AS_OF,
    )

    assert counting.iterations == 1, (
        "factor results must be indexed in one pass, not rescanned per "
        f"(scanner, symbol); observed {counting.iterations} passes"
    )
