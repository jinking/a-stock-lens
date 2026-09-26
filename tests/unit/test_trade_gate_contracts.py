"""Trade Gate 契约（受控词表与模型、Profile 配置、审计 Adapter）——本域唯一权威。

本文件由 Task 12「文件合并」把以下 3 个同域小文件整体搬入：
    - tests/unit/test_trade_gate_models.py（3 例）
    - tests/unit/test_trade_gate_profiles.py（2 例）
    - tests/unit/test_trade_gate_audit_adapter.py（3 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

import shlex
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from astock_lens.domain.enums import TradeAction, TradeDecision, TradeProfile
from astock_lens.trade_gate.audit.cli import (
    CliThesisAuditAdapter,
    TradeAuditInvocationError,
    adjusted_ratio,
)
from astock_lens.trade_gate.models import (
    DimensionJudgement,
    TradeIntent,
    TradeRiskProposal,
)
from astock_lens.trade_gate.profiles import load_trade_gate_profiles

# ===========================================================================
# 来源：tests/unit/test_trade_gate_models.py（3 例）
# ===========================================================================


SH = ZoneInfo("Asia/Shanghai")


def test_trade_gate_vocab_is_exact() -> None:
    assert [x.value for x in TradeAction] == ["ENTRY", "ADD"]
    assert [x.value for x in TradeProfile] == ["EVENT", "SWING", "POSITION"]
    assert [x.value for x in TradeDecision] == ["PASS", "WAIT", "NO_TRADE"]


def test_trade_intent_rejects_naive_time() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        TradeIntent(
            id="intent-1",
            symbol="603991.SH",
            action=TradeAction.ENTRY,
            profile=TradeProfile.EVENT,
            thesis="隔夜芯片上涨可能传导 A 股",
            expected_holding_days=3,
            created_at=datetime(2026, 9, 22, 9, 20),  # noqa: DTZ001
            risk=TradeRiskProposal(
                account_nav=100_000,
                planned_entry_price=175.5,
                stop_loss_price=169.0,
                quantity=100,
                invalidation_rule="跌破 169 且个股继续弱于板块",
            ),
        )


def test_risk_proposal_computes_loss_without_inventing_account_limit() -> None:
    risk = TradeRiskProposal(
        account_nav=100_000,
        planned_entry_price=175.5,
        stop_loss_price=169.0,
        quantity=100,
        invalidation_rule="跌破 169",
    )
    assert risk.position_value == pytest.approx(17_550)
    assert risk.max_loss_amount == pytest.approx(650)
    assert risk.max_loss_pct_of_nav == pytest.approx(0.0065)


# ===========================================================================
# 来源：tests/unit/test_trade_gate_profiles.py（2 例）
# ===========================================================================


def test_profiles_sum_to_100_and_use_fixed_thresholds() -> None:
    profiles = load_trade_gate_profiles(Path("configs/trade_gate"))
    for profile in profiles.values():
        assert sum(profile.weights.values()) == pytest.approx(100.0)
        assert profile.pass_threshold == 80.0
        assert profile.wait_threshold == 70.0
    assert profiles[TradeProfile.EVENT].weights["expectation_gap"] == 20.0
    assert profiles[TradeProfile.SWING].weights["key_level"] == 20.0
    assert profiles[TradeProfile.POSITION].weights["competitiveness"] == 20.0


def test_invalid_weight_total_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "event.yaml").write_text(
        "id: EVENT\nversion: v1\npass_threshold: 80\nwait_threshold: 70\n"
        "weights: {x: 99}\nrequired_ai_dimensions: []\nenabled_vetoes: []\nfomo_wait_threshold: 8\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="100"):
        load_trade_gate_profiles(tmp_path)


# ===========================================================================
# 来源：tests/unit/test_trade_gate_audit_adapter.py（3 例）
# ===========================================================================


def _command(source: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"


def test_phase_one_does_not_receive_thesis(tmp_path) -> None:
    source = "import json,sys; p=json.load(sys.stdin); assert 'user_thesis' not in p; assert 'secret thesis' not in json.dumps(p); print(json.dumps({'summary':'independent','dimensions':[],'risks':[],'evidence':[]}))"
    CliThesisAuditAdapter(_command(source)).independent_assessment(
        profile=TradeProfile.EVENT, facts={"symbol": "603991.SH"}
    )


def test_confidence_adjustment_is_exact() -> None:
    judgement = DimensionJudgement(
        name="expectation_gap",
        score_ratio=0.9,
        confidence=0.55,
        evidence=("x",),
        summary="x",
    )
    assert adjusted_ratio(judgement) == pytest.approx(0.6975)


def test_adapter_rejects_invalid_output() -> None:
    adapter = CliThesisAuditAdapter(_command("print('[]')"))
    with pytest.raises((TradeAuditInvocationError, ValidationError)):
        adapter.independent_assessment(profile=TradeProfile.EVENT, facts={})
