"""策略长尾（动量扫描器、独立 Scanner、因子索引、重构对齐、百分位评分）。

本文件由 Task 12「文件合并」把以下 5 个同域小文件整体搬入：
    - tests/unit/test_momentum_scanner.py（9 例）
    - tests/unit/test_strategy_scanners.py（6 例）
    - tests/unit/test_strategy_factor_index.py（4 例）
    - tests/unit/test_strategy_parity.py（2 例）
    - tests/unit/test_percentile_scorer.py（8 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

import json
import re
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.domain.enums import DataStatus, MarketRegime
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines.stages import FactorResultIndex, strategy_stage
from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import (
    EligibilityResult,
    StrategyContext,
    StrategyResult,
)
from astock_lens.strategies.momentum import MomentumScanner
from astock_lens.strategies.percentile_scorer import (
    WeightedPercentileScorer,
    explain_result,
    validated_weights,
)
from astock_lens.strategies.registry import RegisteredStrategy, build_scanner
from astock_lens.universe.models import UniverseSnapshot

# ===========================================================================
# 来源：tests/unit/test_momentum_scanner.py（9 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Momentum scanner tests.
#
# The rule these tests pin down: `score()` answers for one symbol, and a
# percentile needs a population, so it decides *eligibility* and does not rank. A
# score of `None` states that no cross-section was available — it never stands in
# a plausible-looking number. The ranking itself is covered by
# `test_strategy_scoring.py`.
#
# Factor names are read from the configuration rather than written here, so the
# scanner's contract stays under test when the strategy's factor set changes.
#


CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "strategies" / "momentum.yaml"
)


CONFIG = load_strategy_config(CONFIG_PATH)


REQUIRED = CONFIG.required_factors


MOMENTUM_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _momentum_scanner() -> MomentumScanner:
    return MomentumScanner(CONFIG)


def _factor_result(name: str, status: DataStatus, value: float | None) -> FactorResult:
    return FactorResult(
        symbol="600000.SH",
        factor=name,
        as_of=MOMENTUM_AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _valued() -> tuple[FactorResult, ...]:
    """Every configured factor, each carrying a value."""
    return tuple(
        _factor_result(name, DataStatus.VALUE, 1_000_000.0) for name in REQUIRED
    )


def _null_last() -> tuple[FactorResult, ...]:
    return (*_valued()[:-1], _factor_result(REQUIRED[-1], DataStatus.NULL, None))


def _momentum_context(*results: FactorResult) -> StrategyContext:
    return StrategyContext(
        symbol="600000.SH",
        as_of=MOMENTUM_AS_OF,
        factors=results,
        market_regime=MarketRegime.RANGE,
    )


def test_required_factors_come_from_the_config_file() -> None:
    assert _momentum_scanner().required_factors() == set(REQUIRED)


def test_eligible_when_every_required_factor_has_a_value() -> None:
    result = _momentum_scanner().eligibility(_momentum_context(*_valued()))

    assert result.eligible is True
    assert result.reasons == ()


def test_missing_factor_makes_the_symbol_ineligible() -> None:
    result = _momentum_scanner().eligibility(_momentum_context(*_valued()[:-1]))

    assert result.eligible is False
    assert any(REQUIRED[-1] in reason for reason in result.reasons)


def test_null_factor_makes_the_symbol_ineligible() -> None:
    result = _momentum_scanner().eligibility(_momentum_context(*_null_last()))

    assert result.eligible is False
    assert any("NULL" in reason for reason in result.reasons)


def test_scoring_is_explicitly_absent_for_a_lone_symbol() -> None:
    """One symbol, no population to rank against, so no score is invented."""
    result = _momentum_scanner().score(_momentum_context(*_valued()))

    assert result.score is None
    assert result.rank_percentile is None
    assert result.confidence is None
    assert result.contributions == ()


def test_score_result_keeps_its_evidence() -> None:
    context = _momentum_context(*_valued())

    result = _momentum_scanner().score(context)

    assert result.eligible is True
    assert result.factor_snapshot == context.factors
    assert result.strategy_id == "momentum"
    assert result.strategy_version == "v1"
    assert result.lineage.strategy_version == "v1"
    assert any(REQUIRED[0] in reason for reason in result.reasons)


def test_ineligible_context_is_carried_into_risks() -> None:
    result = _momentum_scanner().score(_momentum_context(*_null_last()))

    assert result.eligible is False
    assert result.risks


def test_explain_reports_per_factor_notes() -> None:
    context = _momentum_context(*_valued())

    explanation = _momentum_scanner().explain(_momentum_scanner().score(context))

    assert explanation.symbol == "600000.SH"
    assert "momentum v1" in explanation.summary
    assert "eligible" in explanation.summary
    assert "eligibility only" in explanation.summary
    assert [note.factor for note in explanation.factors] == list(REQUIRED)
    assert explanation.factors[0].note == "1000000.0"


def test_explain_reports_a_missing_value_as_missing() -> None:
    context = _momentum_context(*_null_last())

    explanation = _momentum_scanner().explain(_momentum_scanner().score(context))

    assert explanation.factors[-1].note == "no value (NULL)"


# ===========================================================================
# 来源：tests/unit/test_strategy_scanners.py（6 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 独立 Scanner 类的共同边界。
#
# Task 6 的产出不是"换了个实现"，而是**每个策略都能自己拥有规则**。这些测试
# 逐个类核对同一组约定：
#
# * 四个方法都在（`required_factors` / `eligibility` / 打分 / `explain`）；
# * `score()` 看单只标的不给分——百分位需要一个总体；
# * 缺证据的标的不合格，理由点名缺的是哪个因子；
# * `explain()` 能把分数展开到因子层；
# * 每个类真的是自己的类，不是同一个通用类换了个名字。
#


SCANNERS_ROOT = Path(__file__).resolve().parents[2]


SCANNERS_CONFIGS = SCANNERS_ROOT / "configs" / "strategies"


SCANNERS_AS_OF = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)


# 每个策略一个自己的类名。这是本 Task 的核心断言：策略边界不能再由配置推断。
SCANNERS = {
    "growth": "GrowthScanner",
    "quality": "QualityScanner",
    "dividend": "DividendScanner",
    "value": "ValueScanner",
    "garp": "GarpScanner",
}


def _scanner(strategy_id: str):
    return build_scanner(load_strategy_config(SCANNERS_CONFIGS / f"{strategy_id}.yaml"))


def _scanners_context(
    scanner: object, symbol: str, *, missing: str | None = None
) -> StrategyContext:
    names = sorted(scanner.required_factors())  # type: ignore[attr-defined]
    return StrategyContext(
        symbol=symbol,
        as_of=SCANNERS_AS_OF,
        factors=tuple(
            FactorResult(
                symbol=symbol,
                factor=name,
                as_of=SCANNERS_AS_OF,
                status=DataStatus.NOT_APPLICABLE
                if name == missing
                else DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=None if name == missing else float(index + 1) * 3.0,
            )
            for index, name in enumerate(names)
        ),
    )


def test_the_class_is_its_own() -> None:
    wrong = [
        sid for sid in sorted(SCANNERS) if type(_scanner(sid)).__name__ != SCANNERS[sid]
    ]
    assert not wrong, f"扫描器类名与配置不符: {wrong}"


def test_the_required_factors_match_the_configuration() -> None:
    wrong = []
    for sid in sorted(SCANNERS):
        config = load_strategy_config(SCANNERS_CONFIGS / f"{sid}.yaml")
        if _scanner(sid).required_factors() != set(config.required_factors):
            wrong.append(sid)
    assert not wrong, f"必需因子与配置不符: {wrong}"


def test_scoring_one_symbol_alone_reports_no_score() -> None:
    """`score()` 没有总体可排，所以它只报告资格与证据。"""
    wrong = []
    for sid in sorted(SCANNERS):
        scanner = _scanner(sid)
        result = scanner.score(_scanners_context(scanner, "ONLY"))
        ok = (
            result.eligible is True
            and result.score is None
            and result.rank_percentile is None
            and result.confidence is None
            and result.strategy_id == sid
        )
        if not ok:
            wrong.append(
                f"{sid}: eligible={result.eligible!r} score={result.score!r} "
                f"percentile={result.rank_percentile!r} "
                f"confidence={result.confidence!r} id={result.strategy_id!r}"
            )
    assert not wrong, "单独评分应只报资格与证据:\n" + "\n".join(wrong)


def test_a_missing_factor_makes_the_symbol_ineligible_with_a_reason() -> None:
    wrong = []
    for sid in sorted(SCANNERS):
        scanner = _scanner(sid)
        missing = min(scanner.required_factors())
        result = scanner.score(_scanners_context(scanner, "HOLE", missing=missing))
        if result.eligible is not False or not any(
            missing in reason for reason in result.risks
        ):
            wrong.append(f"{sid}: eligible={result.eligible!r} risks={result.risks!r}")
    assert not wrong, "缺因子应判不合格并给出原因:\n" + "\n".join(wrong)


def test_the_explanation_reaches_factor_level() -> None:
    wrong = []
    for sid in sorted(SCANNERS):
        scanner = _scanner(sid)
        contexts = (
            _scanners_context(scanner, "A"),
            _scanners_context(scanner, "B"),
            _scanners_context(scanner, "C"),
        )
        result = scanner.score_cross_section(contexts)[0]
        explanation = scanner.explain(result)
        factors = {item.factor for item in explanation.factors}
        if explanation.strategy_id != sid or factors != scanner.required_factors():
            wrong.append(
                f"{sid}: id={explanation.strategy_id!r} factors={sorted(factors)!r} "
                f"expected={sorted(scanner.required_factors())!r}"
            )
    assert not wrong, "解释应落到因子层:\n" + "\n".join(wrong)


def test_the_cross_section_ranks_exactly_the_eligible_population() -> None:
    wrong = []
    for sid in sorted(SCANNERS):
        scanner = _scanner(sid)
        missing = min(scanner.required_factors())
        contexts = (
            _scanners_context(scanner, "A"),
            _scanners_context(scanner, "B"),
            _scanners_context(scanner, "HOLE", missing=missing),
        )
        results = {
            result.symbol: result for result in scanner.score_cross_section(contexts)
        }
        if not (
            results["A"].score is not None
            and results["B"].score is not None
            and results["HOLE"].score is None
        ):
            wrong.append(
                f"{sid}: A={results['A'].score!r} B={results['B'].score!r} "
                f"HOLE={results['HOLE'].score!r}"
            )
    assert not wrong, "横截面应只给合格标的打分:\n" + "\n".join(wrong)


# ===========================================================================
# 来源：tests/unit/test_strategy_factor_index.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Factor lookup inside the strategy stage.
#
# `strategy_stage` asks "which factor results belong to this symbol?" once per
# (scanner, symbol) pair. Answering that by rescanning the whole factor list is
# quadratic: 6 scanners × N symbols × 24·N results. The index answers the same
# question from one pass.
#
# Two properties matter and both are pinned here: the indexed answer is byte-for-
# byte the same as a naive scan, and the factor list is walked exactly once no
# matter how many scanners or symbols the run has. The second test uses a
# counting sequence, so it fails against the old implementation for the right
# reason rather than by inspecting code.
#


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


# ===========================================================================
# 来源：tests/unit/test_strategy_parity.py（2 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 重构前后的策略输出必须逐位相同。
#
# Task 6 只做架构重构：把"通用加权 Scanner"降级为评分组件，并让每个策略拥有
# 独立的 Scanner 类。它**不许**顺手改业务语义——权重、极性、资格规则、异常处理
# 都要保持原样。这个测试是那句话的可执行版本。
#
# 期望值不是手写的，也不是重构后跑出来的：`tests/fixtures/strategy_parity.json`
# 由重构前的实现（commit `7d58d4c`）在固定合成横截面上算出并落盘，JSON 里记着
# 产出它的提交号。合成输入的意义在于每个策略都有真实可打的分数——CSV fixture
# 上没有落地的财报与估值，五个基本面策略在那里全是"不合格"，parity 就无从谈。
#
# 只比对业务输出：`eligible`、`score`、`rank_percentile`、因子贡献。Scanner 的类名
# 不在比对范围内——它正是本次重构要改的东西。
#


ROOT = Path(__file__).resolve().parents[2]


CONFIGS = ROOT / "configs" / "strategies"


FIXTURE = ROOT / "tests" / "fixtures" / "strategy_parity.json"


PARITY = json.loads(FIXTURE.read_text(encoding="utf-8"))


PARITY_AS_OF = datetime.fromisoformat(PARITY["as_of"])


PARITY_SYMBOLS: list[str] = PARITY["symbols"]


MISSING = {tuple(item) for item in PARITY["missing"]}


def _parity_factor_result(factor: str, symbol: str) -> FactorResult:
    if (factor, symbol) in MISSING:
        return FactorResult(
            symbol=symbol,
            factor=factor,
            as_of=PARITY_AS_OF,
            status=DataStatus.NOT_APPLICABLE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=None,
        )
    index = PARITY_SYMBOLS.index(symbol)
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=PARITY_AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=PARITY["values"][factor][index],
    )


def _contexts() -> tuple[StrategyContext, ...]:
    factors = sorted(PARITY["values"])
    return tuple(
        StrategyContext(
            symbol=symbol,
            as_of=PARITY_AS_OF,
            factors=tuple(_parity_factor_result(name, symbol) for name in factors),
        )
        for symbol in PARITY_SYMBOLS
    )


def _observed(result: StrategyResult) -> dict[str, object]:
    return {
        "symbol": result.symbol,
        "eligible": result.eligible,
        "score": result.score,
        "rank_percentile": result.rank_percentile,
        "contributions": [
            {
                "factor": item.factor,
                "percentile": item.percentile,
                "weight": item.weight,
                "weighted": item.weighted,
            }
            for item in result.contributions
        ],
    }


def test_the_refactored_scanner_reproduces_the_recorded_output() -> None:
    wrong = []
    for strategy_id in sorted(PARITY["strategies"]):
        scanner = build_scanner(load_strategy_config(CONFIGS / f"{strategy_id}.yaml"))
        observed = [
            _observed(result) for result in scanner.score_cross_section(_contexts())
        ]
        expected = PARITY["strategies"][strategy_id]["results"]
        if observed != expected:
            first = next(
                (
                    i
                    for i, (a, b) in enumerate(zip(observed, expected, strict=False))
                    if a != b
                ),
                None,
            )
            wrong.append(f"{strategy_id}: 第 {first} 条起不一致")
    assert not wrong, "重构后的扫描器未复现录制输出:\n" + "\n".join(wrong)


def test_the_fixture_was_recorded_before_this_refactor() -> None:
    """期望值必须来自重构前的实现；没有出处就没有意义。"""
    assert PARITY["generated_from_commit"]


# ===========================================================================
# 来源：tests/unit/test_percentile_scorer.py（8 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 共享评分组件的约定。
#
# 把一份已评审的权重集合变成分数，所以这些测试钉住的是"评审者批准数字时同意的
# 那套规矩"：
#
# - 权重的符号表达极性，所以"越小越好"的因子（`debt_to_asset`）排名前先反向；
# - 只有合格的标的进入横截面，缺证据的标的不挪动别人的百分位；
# - 权重必须恰好覆盖必需要求的因子，0 权重被拒绝而不是被静默忽略；
# - `confidence` 保持缺席，因为设计没有为它定义算法。
#
# 以及一条边界：这个组件**不知道**任何策略的资格规则。调用方注入自己的判定，
# 组件只负责排名——否则"资格规则"就会重新变成配置推断出来的东西。
#


PERCENTILE_AS_OF = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)


WEIGHTS = {"roe_ttm": 1.0, "debt_to_asset": -1.0}


def _config(**overrides: object) -> StrategyConfig:
    payload: dict[str, object] = {
        "id": "quality",
        "version": "v1",
        "description": "quality",
        "required_factors": ["roe_ttm", "debt_to_asset"],
        "weights": dict(WEIGHTS),
    }
    payload.update(overrides)
    return StrategyConfig.model_validate(payload)


def _factor(symbol: str, name: str, value: float | None) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=PERCENTILE_AS_OF,
        status=DataStatus.VALUE if value is not None else DataStatus.NULL,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _context(symbol: str, roe: float | None, debt: float | None) -> StrategyContext:
    return StrategyContext(
        symbol=symbol,
        as_of=PERCENTILE_AS_OF,
        factors=(
            _factor(symbol, "roe_ttm", roe),
            _factor(symbol, "debt_to_asset", debt),
        ),
    )


def _score(contexts: tuple[StrategyContext, ...], **overrides: object):
    scorer = WeightedPercentileScorer()
    return scorer.score_cross_section(
        strategy_id="quality",
        strategy_version="v1",
        contexts=contexts,
        weights=overrides.pop("weights", WEIGHTS),
        **overrides,
    )


def _by_symbol(results: tuple[object, ...]) -> dict[str, object]:
    return {result.symbol: result for result in results}  # type: ignore[attr-defined]


def test_a_negative_weight_orients_a_factor_where_lower_is_better() -> None:
    """High ROE and low leverage must both raise the score."""
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("MIDDLE", roe=15.0, debt=30.0),
        _context("BAD", roe=5.0, debt=90.0),
    )

    results = _by_symbol(_score(contexts))

    assert results["GOOD"].score > results["MIDDLE"].score > results["BAD"].score
    assert results["GOOD"].rank_percentile == 1.0
    assert results["BAD"].rank_percentile == pytest.approx(1 / 3)


def test_the_orientation_is_visible_in_the_contribution() -> None:
    """A reader must be able to see that leverage was inverted, not added."""
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("BAD", roe=5.0, debt=90.0),
    )

    result = _by_symbol(_score(contexts))["GOOD"]
    contributions = {item.factor: item for item in result.contributions}

    assert contributions["roe_ttm"].percentile == 1.0
    assert contributions["debt_to_asset"].percentile == 1.0  # inverted: 10 < 90
    assert contributions["debt_to_asset"].weight == -1.0


def test_an_ineligible_symbol_shifts_nobody_else() -> None:
    """A missing factor must not move the population's percentiles."""
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("BAD", roe=5.0, debt=90.0),
        _context("UNKNOWN", roe=None, debt=50.0),
    )

    results = _by_symbol(_score(contexts))

    assert results["GOOD"].score == 100.0
    assert results["GOOD"].rank_percentile == 1.0
    assert results["UNKNOWN"].eligible is False
    assert results["UNKNOWN"].score is None
    assert "roe_ttm is NULL, not VALUE" in results["UNKNOWN"].risks


def test_a_single_symbol_population_gets_a_score_but_no_rank() -> None:
    """A percentile against nobody is not a percentile."""
    result = _score((_context("ONLY", 20.0, 10.0),))[0]

    assert result.score == 100.0
    assert result.rank_percentile is None


def test_no_contexts_means_no_results() -> None:
    assert _score(()) == ()


def test_the_caller_supplies_the_eligibility_rule() -> None:
    """资格规则由调用方注入，组件不自带某个策略的规则。"""
    seen: list[str] = []

    def nobody_is_eligible(context: StrategyContext) -> EligibilityResult:
        seen.append(context.symbol)
        return EligibilityResult(eligible=False, reasons=("policy",))

    results = _score(
        (
            _context("GOOD", roe=20.0, debt=10.0),
            _context("ALSO_FINE", roe=12.0, debt=20.0),
        ),
        eligibility=nobody_is_eligible,
    )

    # 注入的规则说了算：两个标的的因子都齐备，但判定它们不合格的是调用方，
    # 不是组件里写死的默认规则。
    assert seen == ["GOOD", "ALSO_FINE"]
    assert all(result.eligible is False for result in results)
    assert all(result.score is None for result in results)


def test_the_explanation_shows_each_factor_and_its_weight() -> None:
    contexts = (
        _context("GOOD", roe=20.0, debt=10.0),
        _context("BAD", roe=5.0, debt=90.0),
    )
    result = _score(contexts)[0]

    explanation = explain_result(result)

    assert "score" in explanation.summary
    assert {item.factor for item in explanation.factors} == {
        "roe_ttm",
        "debt_to_asset",
    }
    assert any("weight -1.0" in item.note for item in explanation.factors)


# 「权重集合必须被校验」三行：行序与原用例一致，label 即原测试名，
# 第 2 行的原 docstring 逐字保留为行注释。
# 列 = label, weights, expected：
#   - `weights` 逐行保留原 `_config(weights=...)` 的字面量；
#   - `expected` 逐字取自原 `pytest.raises(..., match=...)` 的片段，
#     比对方式与原断言同为 `re.search`。
WEIGHTS_VALIDATION_CASES = (
    # test_weights_must_cover_the_required_factors_exactly
    (
        "test_weights_must_cover_the_required_factors_exactly",
        {"roe_ttm": 1.0},
        "must cover required_factors exactly",
    ),
    # test_a_zero_weight_is_refused:
    #   A factor with no weight does not belong in the strategy's requirements.
    (
        "test_a_zero_weight_is_refused",
        {"roe_ttm": 1.0, "debt_to_asset": 0.0},
        "does not belong",
    ),
    # test_a_strategy_without_weights_has_nothing_to_score
    (
        "test_a_strategy_without_weights_has_nothing_to_score",
        {},
        "declares no weights",
    ),
)


def test_invalid_weight_sets_are_refused() -> None:
    """三种非法权重集合各自以 ValueError 拒绝，消息须匹配原 `match=` 片段。

    原 3 条「must cover / is refused / has nothing」用例逐条成行；循环只收集，
    断言在表外一次完成，失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, weights, expected in WEIGHTS_VALIDATION_CASES:
        try:
            validated_weights(_config(weights=weights))
        except ValueError as exc:
            if re.search(expected, str(exc)) is None:
                wrong.append(
                    f"{label}: 错误消息中找不到 {expected!r}，实际 {str(exc)!r}"
                )
        else:
            wrong.append(f"{label}: 未抛出 ValueError")
    assert not wrong, "非法权重集合未被拒绝:\n" + "\n".join(wrong)
