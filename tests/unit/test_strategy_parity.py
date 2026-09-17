"""重构前后的策略输出必须逐位相同。

Task 6 只做架构重构：把"通用加权 Scanner"降级为评分组件，并让每个策略拥有
独立的 Scanner 类。它**不许**顺手改业务语义——权重、极性、资格规则、异常处理
都要保持原样。这个测试是那句话的可执行版本。

期望值不是手写的，也不是重构后跑出来的：`tests/fixtures/strategy_parity.json`
由重构前的实现（commit `7d58d4c`）在固定合成横截面上算出并落盘，JSON 里记着
产出它的提交号。合成输入的意义在于每个策略都有真实可打的分数——CSV fixture
上没有落地的财报与估值，五个基本面策略在那里全是"不合格"，parity 就无从谈。

只比对业务输出：`eligible`、`score`、`rank_percentile`、因子贡献。Scanner 的类名
不在比对范围内——它正是本次重构要改的东西。
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.config import load_strategy_config
from astock_lens.strategies.contracts import StrategyContext, StrategyResult
from astock_lens.strategies.registry import build_scanner

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs" / "strategies"
FIXTURE = ROOT / "tests" / "fixtures" / "strategy_parity.json"

PARITY = json.loads(FIXTURE.read_text(encoding="utf-8"))
AS_OF = datetime.fromisoformat(PARITY["as_of"])
SYMBOLS: list[str] = PARITY["symbols"]
MISSING = {tuple(item) for item in PARITY["missing"]}


def _factor_result(factor: str, symbol: str) -> FactorResult:
    if (factor, symbol) in MISSING:
        return FactorResult(
            symbol=symbol,
            factor=factor,
            as_of=AS_OF,
            status=DataStatus.NOT_APPLICABLE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=None,
        )
    index = SYMBOLS.index(symbol)
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=AS_OF,
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
            as_of=AS_OF,
            factors=tuple(_factor_result(name, symbol) for name in factors),
        )
        for symbol in SYMBOLS
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


@pytest.mark.parametrize("strategy_id", sorted(PARITY["strategies"]))
def test_the_refactored_scanner_reproduces_the_recorded_output(
    strategy_id: str,
) -> None:
    scanner = build_scanner(load_strategy_config(CONFIGS / f"{strategy_id}.yaml"))

    observed = [
        _observed(result) for result in scanner.score_cross_section(_contexts())
    ]

    assert observed == PARITY["strategies"][strategy_id]["results"]


def test_the_fixture_was_recorded_before_this_refactor() -> None:
    """期望值必须来自重构前的实现；没有出处就没有意义。"""
    assert PARITY["generated_from_commit"]
