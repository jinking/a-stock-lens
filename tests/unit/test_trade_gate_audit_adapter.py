import shlex
import sys

import pytest
from pydantic import ValidationError

from astock_lens.domain.enums import TradeProfile
from astock_lens.trade_gate.audit.cli import (
    CliThesisAuditAdapter,
    TradeAuditInvocationError,
    adjusted_ratio,
)
from astock_lens.trade_gate.models import DimensionJudgement


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
    with pytest.raises(TradeAuditInvocationError | ValidationError):
        adapter.independent_assessment(profile=TradeProfile.EVENT, facts={})
