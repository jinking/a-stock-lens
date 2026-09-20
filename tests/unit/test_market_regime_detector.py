"""Market regime detector unit tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from astock_lens.domain.enums import MarketRegime
from astock_lens.market.regime import (
    MarketRegimeContext,
    MarketRegimeDetector,
    MarketRegimeResult,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SHANGHAI)


def test_regime_detector_bull_when_breadth_high_and_index_up() -> None:
    """测试当市场宽度大于55%且指数趋势向上时，判定为 BULL。"""
    detector = MarketRegimeDetector(version="v1")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=0.68,
        index_trend=0.035,
    )
    result = detector.detect(ctx)
    assert isinstance(result, MarketRegimeResult)
    assert result.regime == MarketRegime.BULL
    assert result.breadth_ratio == 0.68
    assert len(result.reasons) > 0
    assert result.lineage.regime_version == "v1"


def test_regime_detector_range_up_when_breadth_high_but_index_flat() -> None:
    """测试当市场宽度大于55%但指数平淡或未确认单边上升时，判定为 RANGE_UP。"""
    detector = MarketRegimeDetector(version="v1")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=0.58,
        index_trend=-0.005,
    )
    result = detector.detect(ctx)
    assert result.regime == MarketRegime.RANGE_UP


def test_regime_detector_range_in_middle_breadth() -> None:
    """测试当市场宽度处于 40% ~ 55% 时，判定为 RANGE 震荡分化。"""
    detector = MarketRegimeDetector(version="v1")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=0.48,
        index_trend=0.01,
    )
    result = detector.detect(ctx)
    assert result.regime == MarketRegime.RANGE


def test_regime_detector_bear_when_breadth_low_and_index_down() -> None:
    """测试当市场宽度小于40%且指数趋势下行时，判定为 BEAR。"""
    detector = MarketRegimeDetector(version="v1")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=0.25,
        index_trend=-0.04,
    )
    result = detector.detect(ctx)
    assert result.regime == MarketRegime.BEAR


def test_regime_detector_range_down_when_breadth_low_but_index_flat() -> None:
    """测试当市场宽度小于40%但指数未单边大跌时，判定为 RANGE_DOWN。"""
    detector = MarketRegimeDetector(version="v1")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=0.32,
        index_trend=0.002,
    )
    result = detector.detect(ctx)
    assert result.regime == MarketRegime.RANGE_DOWN


def test_regime_detector_extreme_volatility_downgrades_bull() -> None:
    """测试当触发极端流动性踩踏时，原 BULL 降级为 RANGE_UP 并记录风险。"""
    detector = MarketRegimeDetector(version="v1")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=0.70,
        index_trend=0.05,
        extreme_volatility=True,
    )
    result = detector.detect(ctx)
    assert result.regime == MarketRegime.RANGE_UP
    assert any("波动率" in r or "踩踏" in r for r in result.reasons)


def test_regime_detector_raises_when_no_data() -> None:
    """测试当所有市场指标均缺失时，绝不静默兜底，必须报错 fail-closed。"""
    detector = MarketRegimeDetector(version="v1")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=None,
        index_trend=None,
    )
    with pytest.raises(ValueError, match="Missing market regime inputs"):
        detector.detect(ctx)
