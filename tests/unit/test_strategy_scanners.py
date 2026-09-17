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

import pytest

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


@pytest.mark.parametrize("strategy_id", sorted(SCANNERS))
def test_the_class_is_its_own(strategy_id: str) -> None:
    assert type(_scanner(strategy_id)).__name__ == SCANNERS[strategy_id]


@pytest.mark.parametrize("strategy_id", sorted(SCANNERS))
def test_the_required_factors_match_the_configuration(strategy_id: str) -> None:
    config = load_strategy_config(CONFIGS / f"{strategy_id}.yaml")

    assert _scanner(strategy_id).required_factors() == set(config.required_factors)


@pytest.mark.parametrize("strategy_id", sorted(SCANNERS))
def test_scoring_one_symbol_alone_reports_no_score(strategy_id: str) -> None:
    """`score()` 没有总体可排，所以它只报告资格与证据。"""
    scanner = _scanner(strategy_id)

    result = scanner.score(_context(scanner, "ONLY"))

    assert result.eligible is True
    assert result.score is None
    assert result.rank_percentile is None
    assert result.confidence is None
    assert result.strategy_id == strategy_id


@pytest.mark.parametrize("strategy_id", sorted(SCANNERS))
def test_a_missing_factor_makes_the_symbol_ineligible_with_a_reason(
    strategy_id: str,
) -> None:
    scanner = _scanner(strategy_id)
    missing = min(scanner.required_factors())

    result = scanner.score(_context(scanner, "HOLE", missing=missing))

    assert result.eligible is False
    assert any(missing in reason for reason in result.risks)


@pytest.mark.parametrize("strategy_id", sorted(SCANNERS))
def test_the_explanation_reaches_factor_level(strategy_id: str) -> None:
    scanner = _scanner(strategy_id)
    contexts = (
        _context(scanner, "A"),
        _context(scanner, "B"),
        _context(scanner, "C"),
    )

    result = scanner.score_cross_section(contexts)[0]
    explanation = scanner.explain(result)

    assert explanation.strategy_id == strategy_id
    assert {item.factor for item in explanation.factors} == scanner.required_factors()


@pytest.mark.parametrize("strategy_id", sorted(SCANNERS))
def test_the_cross_section_ranks_exactly_the_eligible_population(
    strategy_id: str,
) -> None:
    scanner = _scanner(strategy_id)
    missing = min(scanner.required_factors())
    contexts = (
        _context(scanner, "A"),
        _context(scanner, "B"),
        _context(scanner, "HOLE", missing=missing),
    )

    results = {
        result.symbol: result for result in scanner.score_cross_section(contexts)
    }

    assert results["A"].score is not None
    assert results["B"].score is not None
    assert results["HOLE"].score is None
