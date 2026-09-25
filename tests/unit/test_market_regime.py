"""Market regime detector unit tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from astock_lens.domain.enums import MarketRegime
from astock_lens.market.regime import (
    MarketRegimeContext,
    MarketRegimeDetector,
    MarketRegimeEvidenceIncomplete,
    MarketRegimeResult,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SHANGHAI)


REGIME_JUDGEMENT_CASES = (
    # test_regime_detector_bull_when_breadth_high_and_index_up:
    #   测试当市场宽度大于55%且指数趋势向上时，判定为 BULL。
    (
        "test_regime_detector_bull_when_breadth_high_and_index_up",
        0.68,
        0.035,
        False,
        MarketRegime.BULL,
        (),
        "v1",
    ),
    # test_regime_detector_range_up_when_breadth_high_but_index_flat:
    #   测试当市场宽度大于55%但指数平淡或未确认单边上升时，判定为 RANGE_UP。
    (
        "test_regime_detector_range_up_when_breadth_high_but_index_flat",
        0.58,
        -0.005,
        False,
        MarketRegime.RANGE_UP,
        (),
        None,
    ),
    # test_regime_detector_range_in_middle_breadth:
    #   测试当市场宽度处于 40% ~ 55% 时，判定为 RANGE 震荡分化。
    (
        "test_regime_detector_range_in_middle_breadth",
        0.48,
        0.01,
        False,
        MarketRegime.RANGE,
        (),
        None,
    ),
    # test_regime_detector_bear_when_breadth_low_and_index_down:
    #   测试当市场宽度小于40%且指数趋势下行时，判定为 BEAR。
    (
        "test_regime_detector_bear_when_breadth_low_and_index_down",
        0.25,
        -0.04,
        False,
        MarketRegime.BEAR,
        (),
        None,
    ),
    # test_regime_detector_range_down_when_breadth_low_but_index_flat:
    #   测试当市场宽度小于40%但指数未单边大跌时，判定为 RANGE_DOWN。
    (
        "test_regime_detector_range_down_when_breadth_low_but_index_flat",
        0.32,
        0.002,
        False,
        MarketRegime.RANGE_DOWN,
        (),
        None,
    ),
    # test_regime_detector_extreme_volatility_downgrades_bull:
    #   测试当触发极端流动性踩踏时，原 BULL 降级为 RANGE_UP 并记录风险。
    (
        "test_regime_detector_extreme_volatility_downgrades_bull",
        0.70,
        0.05,
        True,
        MarketRegime.RANGE_UP,
        ("波动率", "踩踏"),
        None,
    ),
    # test_regime_detector_with_trend_ratio_bull_under_approved_decision_a1:
    #   决策 A1：当指数趋势以均线比率 (ma_20 / ma_60 > 1.0) 传入且宽度高时判定为 BULL。
    (
        "test_regime_detector_with_trend_ratio_bull_under_approved_decision_a1",
        0.62,
        1.035,  # 均线比率 ma_20 / ma_60 = 1.035 > 1.0
        False,
        MarketRegime.BULL,
        ("走多", "均线"),
        None,
    ),
    # test_regime_detector_with_trend_ratio_bear_under_approved_decision_a1:
    #   决策 A1：当指数趋势以均线比率 (ma_20 / ma_60 < 1.0) 传入且宽度低时判定为 BEAR。
    (
        "test_regime_detector_with_trend_ratio_bear_under_approved_decision_a1",
        0.28,
        0.965,  # 均线比率 ma_20 / ma_60 = 0.965 < 1.0
        False,
        MarketRegime.BEAR,
        ("下行", "空头", "走弱"),
        None,
    ),
)


def test_regime_detector_judgements() -> None:
    """测试 8 组宽度/趋势输入各自输出预期 regime（原 8 条判定用例收表）。

    倒数第二列的 fragments 承接原「reasons 命中任一关键词」断言；
    末列承接原 bull 行的结果合同断言（`isinstance`、`breadth_ratio`、
    `reasons` 非空、`regime_version == "v1"`），为 None 的行不做这些断言。
    """
    detector = MarketRegimeDetector(version="v1")
    wrong = []
    for (
        label,
        breadth_ratio,
        index_trend,
        extreme_volatility,
        expected,
        reasons_any,
        expected_regime_version,
    ) in REGIME_JUDGEMENT_CASES:
        ctx = MarketRegimeContext(
            as_of=AS_OF,
            breadth_ratio=breadth_ratio,
            index_trend=index_trend,
            extreme_volatility=extreme_volatility,
        )
        result = detector.detect(ctx)
        if not isinstance(result, MarketRegimeResult):
            wrong.append(
                f"{label}: 期望 MarketRegimeResult，实际 {type(result).__name__}"
            )
            continue
        if result.regime != expected:
            wrong.append(f"{label}: regime 得到 {result.regime!r}，期望 {expected!r}")
        if reasons_any and not any(
            fragment in reason for fragment in reasons_any for reason in result.reasons
        ):
            wrong.append(
                f"{label}: reasons 缺少 {reasons_any!r} 中任一关键词，"
                f"实际 {result.reasons!r}"
            )
        if expected_regime_version is not None:
            if result.breadth_ratio != breadth_ratio:
                wrong.append(
                    f"{label}: breadth_ratio 得到 {result.breadth_ratio!r}，"
                    f"期望 {breadth_ratio!r}"
                )
            if not result.reasons:
                wrong.append(f"{label}: reasons 不应为空")
            if result.lineage.regime_version != expected_regime_version:
                wrong.append(
                    f"{label}: lineage.regime_version 得到 "
                    f"{result.lineage.regime_version!r}，"
                    f"期望 {expected_regime_version!r}"
                )
    assert not wrong, "市场 regime 判定未按预期:\n" + "\n".join(wrong)


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


def test_r2_requires_breadth_and_index_trend() -> None:
    detector = MarketRegimeDetector(version="v2")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=0.61,
        index_trend=None,
        extreme_volatility=False,
    )
    with pytest.raises(MarketRegimeEvidenceIncomplete):
        detector.detect(ctx)


def test_r2_requires_breadth_when_index_trend_present() -> None:
    detector = MarketRegimeDetector(version="v2")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=None,
        index_trend=1.035,
        extreme_volatility=False,
    )
    with pytest.raises(MarketRegimeEvidenceIncomplete):
        detector.detect(ctx)


def test_r2_b3_volatility_deferred_reason() -> None:
    detector = MarketRegimeDetector(version="v2")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=0.68,
        index_trend=1.035,
        extreme_volatility=False,
    )
    result = detector.detect(ctx)
    assert any("B3" in r or "暂缓启用" in r for r in result.reasons)
