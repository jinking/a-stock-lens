"""市场长尾（体制判定、市场验证矩阵）。

本文件由 Task 12「文件合并」把以下 2 个同域小文件整体搬入：
    - tests/unit/test_market_regime.py（5 例）
    - tests/unit/test_market_validator.py（8 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from astock_lens.domain.enums import DataStatus, MarketRegime, MarketValidation
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.market.regime import (
    MarketRegimeContext,
    MarketRegimeDetector,
    MarketRegimeEvidenceIncomplete,
    MarketRegimeResult,
)
from astock_lens.market.validation import (
    MarketValidationContext,
    MarketValidationEvidenceIncomplete,
    MarketValidationResult,
    MarketValidator,
)

# ===========================================================================
# 来源：tests/unit/test_market_regime.py（5 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Market regime detector unit tests."""
#


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


# ===========================================================================
# 来源：tests/unit/test_market_validator.py（8 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Market validation 5-dimension matrix unit tests."""
#


MARKET_VALIDATOR_SHANGHAI = ZoneInfo("Asia/Shanghai")


MARKET_VALIDATOR_AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=MARKET_VALIDATOR_SHANGHAI)


def _fr(symbol: str, factor: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=MARKET_VALIDATOR_AS_OF,
        status=DataStatus.VALUE,
        raw_value=value,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
    )


def test_market_validator_liquidity_veto_contradicted() -> None:
    """测试流动性警戒线一票否决：avg_amount_20d < 1.0 亿元 直接输出 CONTRADICTED。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr("601398.SH", "avg_amount_20d", 80_000_000.0),  # 0.8 亿 < 1.0 亿
        _fr("601398.SH", "ret_20d", 0.10),
        _fr("601398.SH", "proximity_52w_high", 0.95),
    )
    ctx = MarketValidationContext(
        symbol="601398.SH",
        strategy_id="momentum",
        as_of=MARKET_VALIDATOR_AS_OF,
        factors=factors,
        industry_excess_return=0.01,
        relative_strength_60d=0.02,
        vol_ratio=1.0,
    )
    result = validator.validate(ctx)
    assert isinstance(result, MarketValidationResult)
    assert result.status == MarketValidation.CONTRADICTED
    assert any("流动性" in r and "警戒线" in r for r in result.risks)


VALIDATION_STATUS_CASES = (
    # test_market_validator_two_negatives_contradicted:
    #   测试负向冲突项数 >= 2 时输出 CONTRADICTED（破位 + 相对强弱大幅跑输）。
    (
        "test_market_validator_two_negatives_contradicted",
        "688525.SH",
        "growth",
        (
            ("avg_amount_20d", 300_000_000.0),  # 3.0 亿 流动性达标
            ("ret_20d", -0.18),  # 负向项 1: 跌幅超过 15%
            ("proximity_52w_high", 0.50),
        ),
        0.0,
        -0.20,  # 负向项 2: 相对强弱 < -15%
        1.0,
        MarketValidation.CONTRADICTED,
        {"negative_count_min": 2},
    ),
    # test_market_validator_momentum_confirmed:
    #   测试动量标的各项指标优良时，通过验证输出 CONFIRMED。
    (
        "test_market_validator_momentum_confirmed",
        "300741.SZ",
        "momentum",
        (
            ("avg_amount_20d", 400_000_000.0),  # 4.0 亿 >= 1.5 亿
            ("ret_20d", 0.25),  # > 6.4%
            ("proximity_52w_high", 0.98),  # > 0.85
        ),
        0.03,
        0.05,
        1.10,
        MarketValidation.CONFIRMED,
        {
            "negative_count_exact": 0,
            "positive_count_min": 2,
            "reasons_nonempty": True,
        },
    ),
    # test_market_validator_value_tolerates_drawdown_neutral:
    #   测试价值策略标的在未破位区间 (-10% ~ 0%)，不会被错杀为 CONTRADICTED，而是 NEUTRAL。
    (
        "test_market_validator_value_tolerates_drawdown_neutral",
        "600000.SH",
        "value",
        (
            ("avg_amount_20d", 250_000_000.0),  # 2.5 亿
            ("ret_20d", -0.04),  # 虽下跌但不超过 -10%
            ("proximity_52w_high", 0.75),
        ),
        0.0,
        0.0,
        1.0,
        MarketValidation.NEUTRAL,
        {"negative_count_exact": 0},
    ),
    # test_market_validator_consumes_all_five_dimensions:
    #   测试市场验证完整消费 5 维输入（流动性、个股趋势、行业超额、相对基准强弱、量比配合）。
    (
        "test_market_validator_consumes_all_five_dimensions",
        "600519.SH",
        "growth",
        (
            ("avg_amount_20d", 500_000_000.0),  # 维度 5: 流动性 >= 1.5 亿 (+1)
            ("ret_20d", 0.08),  # 维度 1: 个股趋势 (+1)
            ("proximity_52w_high", 0.90),
        ),
        0.035,  # 维度 2: 行业超额 (+1)
        0.062,  # 维度 3: 相对基准超额 (+1)
        1.25,  # 维度 4: 量价配合 (+1)
        MarketValidation.CONFIRMED,
        {
            "negative_count_exact": 0,
            "positive_count_exact": 5,
            "reasons_any": (("相对基准", "+6.20%"), ("行业",), ("量比",)),
        },
    ),
)


def test_market_validator_status_matrix() -> None:
    """测试 4 组 5 维输入各自输出预期 status 与计数字段（原 4 条 status 用例收表）。

    checks 支持的键：`negative_count_min` / `negative_count_exact` /
    `positive_count_min` / `positive_count_exact` / `reasons_nonempty` /
    `reasons_any`（每组片段须同时出现在同一条 reason 里）。
    """
    validator = MarketValidator(version="v1")
    wrong = []
    for (
        label,
        symbol,
        strategy_id,
        factor_values,
        industry_excess_return,
        relative_strength_60d,
        vol_ratio,
        expected_status,
        checks,
    ) in VALIDATION_STATUS_CASES:
        ctx = MarketValidationContext(
            symbol=symbol,
            strategy_id=strategy_id,
            as_of=MARKET_VALIDATOR_AS_OF,
            factors=tuple(
                _fr(symbol, factor, value) for factor, value in factor_values
            ),
            industry_excess_return=industry_excess_return,
            relative_strength_60d=relative_strength_60d,
            vol_ratio=vol_ratio,
        )
        result = validator.validate(ctx)
        if result.status != expected_status:
            wrong.append(
                f"{label}: status 得到 {result.status!r}，期望 {expected_status!r}"
            )
        if (
            minimum := checks.get("negative_count_min")
        ) is not None and result.negative_count < minimum:
            wrong.append(
                f"{label}: negative_count 得到 {result.negative_count}，期望 >= {minimum}"
            )
        if (
            exact := checks.get("negative_count_exact")
        ) is not None and result.negative_count != exact:
            wrong.append(
                f"{label}: negative_count 得到 {result.negative_count}，期望 {exact}"
            )
        if (
            minimum := checks.get("positive_count_min")
        ) is not None and result.positive_count < minimum:
            wrong.append(
                f"{label}: positive_count 得到 {result.positive_count}，期望 >= {minimum}"
            )
        if (
            exact := checks.get("positive_count_exact")
        ) is not None and result.positive_count != exact:
            wrong.append(
                f"{label}: positive_count 得到 {result.positive_count}，期望 {exact}"
            )
        if checks.get("reasons_nonempty") and not result.reasons:
            wrong.append(f"{label}: reasons 不应为空，实际 {result.reasons!r}")
        for fragments in checks.get("reasons_any", ()):
            if not any(
                all(fragment in reason for fragment in fragments)
                for reason in result.reasons
            ):
                wrong.append(
                    f"{label}: reasons 缺少同时含 {fragments!r} 的条目，"
                    f"实际 {result.reasons!r}"
                )
    assert not wrong, "5 维市场验证 status 未按预期:\n" + "\n".join(wrong)


def test_market_validator_lineage_contains_market_validation_version() -> None:
    """测试 MarketValidationResult 的 lineage 携带 market_validation_version 且不复用 regime_version。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr("601398.SH", "avg_amount_20d", 80_000_000.0),
        _fr("601398.SH", "ret_20d", 0.05),
        _fr("601398.SH", "proximity_52w_high", 0.90),
    )
    ctx = MarketValidationContext(
        symbol="601398.SH",
        strategy_id="momentum",
        as_of=MARKET_VALIDATOR_AS_OF,
        factors=factors,
        industry_excess_return=0.01,
        relative_strength_60d=0.02,
        vol_ratio=1.0,
    )
    result = validator.validate(ctx)
    assert result.lineage.market_validation_version == "v1"
    assert "v1" in result.lineage.market_validation_versions()
    assert result.lineage.regime_version is None


def test_market_validator_relative_strength_negative_adds_risk() -> None:
    """测试相对基准大幅跑输（< -15%）时，记入 negative 且添加 risk 警示。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr("600519.SH", "avg_amount_20d", 200_000_000.0),
        _fr("600519.SH", "ret_20d", -0.02),
        _fr("600519.SH", "proximity_52w_high", 0.70),
    )
    ctx = MarketValidationContext(
        symbol="600519.SH",
        strategy_id="value",
        as_of=MARKET_VALIDATOR_AS_OF,
        factors=factors,
        industry_excess_return=0.0,
        relative_strength_60d=-0.18,  # < -15%
        vol_ratio=1.0,
    )
    result = validator.validate(ctx)
    assert result.negative_count >= 1
    assert any("相对基准" in r and "落后" in r for r in result.risks)


def _valid_context(
    *,
    symbol: str = "600519.SH",
    strategy_id: str = "growth",
    as_of: datetime = MARKET_VALIDATOR_AS_OF,
    factors: tuple[FactorResult, ...] | None = None,
    industry_excess_return: float | None = 0.03,
    relative_strength_60d: float | None = 0.05,
    vol_ratio: float | None = 1.1,
) -> MarketValidationContext:
    if factors is None:
        factors = (
            _fr(symbol, "avg_amount_20d", 200_000_000.0),
            _fr(symbol, "ret_20d", 0.05),
            _fr(symbol, "proximity_52w_high", 0.90),
        )
    return MarketValidationContext(
        symbol=symbol,
        strategy_id=strategy_id,
        as_of=as_of,
        factors=factors,
        industry_excess_return=industry_excess_return,
        relative_strength_60d=relative_strength_60d,
        vol_ratio=vol_ratio,
    )


def test_market_validator_missing_context_dimensions_raise() -> None:
    """测试缺少行业超额、相对强弱或量比时，必须抛出 MarketValidationEvidenceIncomplete。"""
    validator = MarketValidator(version="v1")
    valid_context = _valid_context()

    with pytest.raises(MarketValidationEvidenceIncomplete) as exc_info:
        validator.validate(
            valid_context.model_copy(update={"industry_excess_return": None})
        )
    assert "industry_excess_return_20d" in str(exc_info.value)

    with pytest.raises(MarketValidationEvidenceIncomplete) as exc_info:
        validator.validate(
            valid_context.model_copy(update={"relative_strength_60d": None})
        )
    assert "relative_strength_60d" in str(exc_info.value)

    with pytest.raises(MarketValidationEvidenceIncomplete) as exc_info:
        validator.validate(valid_context.model_copy(update={"vol_ratio": None}))
    assert "volume_ratio_5_20" in str(exc_info.value)


def test_market_validator_missing_trend_or_liquidity_factors_raise() -> None:
    """测试动量策略缺少 ret_20d、proximity_52w_high 或 avg_amount_20d 因子时抛出异常。"""
    validator = MarketValidator(version="v1")
    valid_context = _valid_context(strategy_id="momentum")

    for factor_name in ("ret_20d", "proximity_52w_high", "avg_amount_20d"):
        remaining_factors = tuple(
            f for f in valid_context.factors if f.factor != factor_name
        )
        with pytest.raises(MarketValidationEvidenceIncomplete) as exc_info:
            validator.validate(
                valid_context.model_copy(update={"factors": remaining_factors})
            )
        assert factor_name in str(exc_info.value)


def test_market_validator_non_momentum_allows_missing_proximity_52w_high() -> None:
    """测试非动量策略（如成长/质量次新股）缺少 proximity_52w_high 时仍可正常完成验证。"""
    validator = MarketValidator(version="v1")
    valid_context = _valid_context(strategy_id="growth")
    factors_without_prox = tuple(
        f for f in valid_context.factors if f.factor != "proximity_52w_high"
    )
    result = validator.validate(
        valid_context.model_copy(update={"factors": factors_without_prox})
    )
    assert isinstance(result, MarketValidationResult)
    assert result.status == MarketValidation.CONFIRMED


def test_market_validator_multiple_missing_factors_reported() -> None:
    """测试同时缺失多个维度时，异常消息中列出所有缺失字段。"""
    validator = MarketValidator(version="v1")
    ctx = MarketValidationContext(
        symbol="000001.SZ",
        strategy_id="momentum",
        as_of=MARKET_VALIDATOR_AS_OF,
        factors=(),
        industry_excess_return=None,
        relative_strength_60d=None,
        vol_ratio=None,
    )
    with pytest.raises(MarketValidationEvidenceIncomplete) as exc_info:
        validator.validate(ctx)
    msg = str(exc_info.value)
    assert "000001.SZ missing required 5D evidence:" in msg
    assert "ret_20d" in msg
    assert "proximity_52w_high" in msg
    assert "avg_amount_20d" in msg
    assert "industry_excess_return_20d" in msg
    assert "relative_strength_60d" in msg
    assert "volume_ratio_5_20" in msg
