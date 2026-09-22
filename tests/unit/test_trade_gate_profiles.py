from pathlib import Path

import pytest

from astock_lens.domain.enums import TradeProfile
from astock_lens.trade_gate.profiles import load_trade_gate_profiles


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
