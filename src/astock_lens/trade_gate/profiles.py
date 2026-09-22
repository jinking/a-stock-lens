"""Trade Gate 策略画像的严格配置读取。"""

from pathlib import Path
from typing import Self

import yaml
from pydantic import model_validator

from astock_lens.domain.enums import TradeProfile
from astock_lens.domain.models import DomainRecord


class StrategyProfileConfig(DomainRecord):
    id: TradeProfile
    version: str
    pass_threshold: float
    wait_threshold: float
    weights: dict[str, float]
    required_ai_dimensions: tuple[str, ...] = ()
    enabled_vetoes: tuple[str, ...] = ()
    fomo_wait_threshold: int

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if abs(sum(self.weights.values()) - 100.0) > 1e-9:
            raise ValueError("trade gate profile weights must sum to 100")
        if self.pass_threshold != 80.0 or self.wait_threshold != 70.0:
            raise ValueError("V1 thresholds are fixed at PASS=80 and WAIT=70")
        if not 0 <= self.fomo_wait_threshold <= 10:
            raise ValueError("fomo_wait_threshold must be within 0..10")
        if (
            not self.version.strip()
            or not self.weights
            or any(v < 0 for v in self.weights.values())
        ):
            raise ValueError("version and non-negative weights are required")
        return self


def load_trade_gate_profiles(
    path: Path | None = None,
) -> dict[TradeProfile, StrategyProfileConfig]:
    """加载恰好三套画像；缺失、重复或非法内容均显式失败。"""
    directory = path or Path("configs/trade_gate")
    result: dict[TradeProfile, StrategyProfileConfig] = {}
    for file in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError(f"invalid trade gate profile: {file}")
        profile = StrategyProfileConfig.model_validate(raw)
        if profile.id in result:
            raise ValueError(f"duplicate trade gate profile: {profile.id}")
        result[profile.id] = profile
    if set(result) != set(TradeProfile):
        raise ValueError(
            "trade gate profiles must contain exactly EVENT, SWING, POSITION"
        )
    return result
