"""生产资格规则契约测试：把所有者批准的六策略规则锁死为硬契约。

本文件把所有者于 2026-09-20 批准的绝对资格阈值逐字写死，并对生产 YAML
做契约断言。在 Task 4 修复生产 YAML 之前，本契约测试预期保持 RED；它是后
续任务必须达成的、不可协商的目标，而不是对当前实现的描述。

参考：
- `docs/superpowers/specs/2026-09-20-qualification-correctness-hardening-design.md`
- `docs/superpowers/specs/2026-09-20-qualification-correctness-hardening-implementation-plan.md`
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_DIR = ROOT / "configs" / "qualifications"

# 所有者批准的唯一资格目标（方案：稳健平衡型）。任何偏差都视为规则漂移。
EXPECTED: dict[str, dict[str, dict[str, float]]] = {
    "value": {
        "pe_ttm": {"max": 25.0},
        "pb": {"max": 2.5},
        "roe_ttm": {"min": 5.0},
    },
    "growth": {
        "net_profit_parent_yoy": {"min": 15.0},
        "revenue_yoy": {"min": 5.0},
        "roe_ttm": {"min": 8.0},
    },
    "garp": {
        "pe_ttm": {"max": 35.0},
        "net_profit_parent_yoy": {"min": 15.0},
        "roe_ttm": {"min": 10.0},
    },
    "quality": {
        "roe_ttm": {"min": 12.0},
        "gross_margin": {"min": 20.0},
        "debt_to_asset": {"max": 65.0},
    },
    "dividend": {
        "dividend_yield_ttm": {"min": 3.0},
        "dividend_payout_ttm": {"min": 0.10, "max": 0.80},
    },
    "momentum": {
        "proximity_52w_high": {"min": 0.80},
    },
}


def _load_yaml(strategy_id: str) -> dict[str, Any]:
    """读取某个策略的生产资格 YAML 原文。"""
    path = QUALIFICATION_DIR / f"{strategy_id}.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} 必须是映射"
    return loaded


def load_raw_thresholds(strategy_id: str) -> dict[str, dict[str, float]]:
    """返回生产资格 YAML 中原始 ``thresholds`` 映射。"""
    raw = _load_yaml(strategy_id)
    thresholds = raw["thresholds"]
    assert isinstance(thresholds, dict), f"{strategy_id}.yaml 的 thresholds 必须是映射"
    return thresholds


@pytest.mark.parametrize("strategy_id", EXPECTED)
def test_production_rule_matches_owner_approval(strategy_id: str) -> None:
    """生产 YAML 必须与所有者批准的因子名与阈值逐字一致。"""
    raw = _load_yaml(strategy_id)

    assert raw["strategy_id"] == strategy_id
    assert raw["version"] == "v1"
    assert raw["thresholds"] == EXPECTED[strategy_id]


def test_dividend_rule_uses_approved_metrics_not_percent_ratio_substitute() -> None:
    """红利资格必须使用获批指标，且不得用百分比口径的替代因子。

    审批口径：
    - ``dividend_yield_ttm`` 单位是 ``%``，下限 3.0；
    - ``dividend_payout_ttm`` 单位是 ratio，区间 ``[0.10, 0.80]``。

    旧实现用 ``dividend_paid_ratio``（单位 ``%``，真实值可为 27.13 / 79.00）冒充
    ``10%~80%``，实际含义退化为 ``0.10%~0.80%``，属于单位错误 + 指标替换。
    """
    thresholds = load_raw_thresholds("dividend")
    assert thresholds["dividend_yield_ttm"]["min"] == 3.0
    assert thresholds["dividend_payout_ttm"] == {"min": 0.10, "max": 0.80}
    assert "dividend_paid_ratio" not in thresholds


def test_momentum_liquidity_is_an_upstream_universe_gate() -> None:
    """Momentum 的流动性属于上游 Research Universe 准入，不在资格层二次发明。

    审批记录中的"流动性符合研究池要求"由 canonical Universe 的
    ``min_average_turnover_20d`` 承担；Qualification 只保留价格强度门槛，
    不得自造"高于横截面平均"逻辑。
    """
    universe = yaml.safe_load(
        (ROOT / "configs" / "universe.yaml").read_text(encoding="utf-8")
    )
    assert universe["min_average_turnover_20d"] == 150_000_000

    momentum = load_raw_thresholds("momentum")
    assert momentum == {"proximity_52w_high": {"min": 0.80}}
