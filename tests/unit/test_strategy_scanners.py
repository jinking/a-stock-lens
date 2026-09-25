"""独立 Scanner 类的共同边界。

Task 6 的产出不是"换了个实现"，而是**每个策略都能自己拥有规则**。这些测试
逐个类核对同一组约定：

* 四个方法都在（`required_factors` / `eligibility` / 打分 / `explain`）；
* `score()` 看单只标的不给分——百分位需要一个总体；
* 缺证据的标的不合格，理由点名缺的是哪个因子；
* `explain()` 能把分数展开到因子层；
* 每个类真的是自己的类，不是同一个通用类换了个名字。
"""

from datetime import UTC, datetime
from pathlib import Path

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.config import load_strategy_config
from astock_lens.strategies.contracts import StrategyContext
from astock_lens.strategies.registry import build_scanner

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs" / "strategies"
AS_OF = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)

# 每个策略一个自己的类名。这是本 Task 的核心断言：策略边界不能再由配置推断。
SCANNERS = {
    "growth": "GrowthScanner",
    "quality": "QualityScanner",
    "dividend": "DividendScanner",
    "value": "ValueScanner",
    "garp": "GarpScanner",
}


def _scanner(strategy_id: str):
    return build_scanner(load_strategy_config(CONFIGS / f"{strategy_id}.yaml"))


def _context(
    scanner: object, symbol: str, *, missing: str | None = None
) -> StrategyContext:
    names = sorted(scanner.required_factors())  # type: ignore[attr-defined]
    return StrategyContext(
        symbol=symbol,
        as_of=AS_OF,
        factors=tuple(
            FactorResult(
                symbol=symbol,
                factor=name,
                as_of=AS_OF,
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
        config = load_strategy_config(CONFIGS / f"{sid}.yaml")
        if _scanner(sid).required_factors() != set(config.required_factors):
            wrong.append(sid)
    assert not wrong, f"必需因子与配置不符: {wrong}"


def test_scoring_one_symbol_alone_reports_no_score() -> None:
    """`score()` 没有总体可排，所以它只报告资格与证据。"""
    wrong = []
    for sid in sorted(SCANNERS):
        scanner = _scanner(sid)
        result = scanner.score(_context(scanner, "ONLY"))
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
        result = scanner.score(_context(scanner, "HOLE", missing=missing))
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
            _context(scanner, "A"),
            _context(scanner, "B"),
            _context(scanner, "C"),
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
            _context(scanner, "A"),
            _context(scanner, "B"),
            _context(scanner, "HOLE", missing=missing),
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
