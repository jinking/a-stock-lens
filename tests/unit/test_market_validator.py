"""Market validation 5-dimension matrix unit tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from astock_lens.domain.enums import DataStatus, MarketValidation
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.market.validation import (
    MarketValidationContext,
    MarketValidationEvidenceIncomplete,
    MarketValidationResult,
    MarketValidator,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SHANGHAI)


def _fr(symbol: str, factor: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=AS_OF,
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
        as_of=AS_OF,
        factors=factors,
        industry_excess_return=0.01,
        relative_strength_60d=0.02,
        vol_ratio=1.0,
    )
    result = validator.validate(ctx)
    assert isinstance(result, MarketValidationResult)
    assert result.status == MarketValidation.CONTRADICTED
    assert any("流动性" in r and "警戒线" in r for r in result.risks)


def test_market_validator_two_negatives_contradicted() -> None:
    """测试负向冲突项数 >= 2 时输出 CONTRADICTED（破位 + 相对强弱大幅跑输）。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr("688525.SH", "avg_amount_20d", 300_000_000.0),  # 3.0 亿 流动性达标
        _fr("688525.SH", "ret_20d", -0.18),  # 负向项 1: 跌幅超过 15%
        _fr("688525.SH", "proximity_52w_high", 0.50),
    )
    ctx = MarketValidationContext(
        symbol="688525.SH",
        strategy_id="growth",
        as_of=AS_OF,
        factors=factors,
        industry_excess_return=0.0,
        relative_strength_60d=-0.20,  # 负向项 2: 相对强弱 < -15%
        vol_ratio=1.0,
    )
    result = validator.validate(ctx)
    assert result.status == MarketValidation.CONTRADICTED
    assert result.negative_count >= 2


def test_market_validator_momentum_confirmed() -> None:
    """测试动量标的各项指标优良时，通过验证输出 CONFIRMED。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr("300741.SZ", "avg_amount_20d", 400_000_000.0),  # 4.0 亿 >= 1.5 亿
        _fr("300741.SZ", "ret_20d", 0.25),  # > 6.4%
        _fr("300741.SZ", "proximity_52w_high", 0.98),  # > 0.85
    )
    ctx = MarketValidationContext(
        symbol="300741.SZ",
        strategy_id="momentum",
        as_of=AS_OF,
        factors=factors,
        industry_excess_return=0.03,
        relative_strength_60d=0.05,
        vol_ratio=1.10,
    )
    result = validator.validate(ctx)
    assert result.status == MarketValidation.CONFIRMED
    assert result.negative_count == 0
    assert result.positive_count >= 2
    assert len(result.reasons) > 0


def test_market_validator_value_tolerates_drawdown_neutral() -> None:
    """测试价值策略标的在未破位区间 (-10% ~ 0%)，不会被错杀为 CONTRADICTED，而是 NEUTRAL。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr("600000.SH", "avg_amount_20d", 250_000_000.0),  # 2.5 亿
        _fr("600000.SH", "ret_20d", -0.04),  # 虽下跌但不超过 -10%
        _fr("600000.SH", "proximity_52w_high", 0.75),
    )
    ctx = MarketValidationContext(
        symbol="600000.SH",
        strategy_id="value",
        as_of=AS_OF,
        factors=factors,
        industry_excess_return=0.0,
        relative_strength_60d=0.0,
        vol_ratio=1.0,
    )
    result = validator.validate(ctx)
    assert result.status == MarketValidation.NEUTRAL
    assert result.negative_count == 0


def test_market_validator_missing_liquidity_factor_raises_incomplete() -> None:
    """测试当缺少流动性因子时，绝不静默兜底，必须抛出 MarketValidationEvidenceIncomplete 阻断。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr("000001.SZ", "ret_20d", 0.05),
        _fr("000001.SZ", "proximity_52w_high", 0.88),
    )
    ctx = MarketValidationContext(
        symbol="000001.SZ",
        strategy_id="momentum",
        as_of=AS_OF,
        factors=factors,
        industry_excess_return=0.01,
        relative_strength_60d=0.02,
        vol_ratio=1.0,
    )
    with pytest.raises(MarketValidationEvidenceIncomplete) as exc_info:
        validator.validate(ctx)
    assert "avg_amount_20d" in str(exc_info.value)


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
        as_of=AS_OF,
        factors=factors,
        industry_excess_return=0.01,
        relative_strength_60d=0.02,
        vol_ratio=1.0,
    )
    result = validator.validate(ctx)
    assert result.lineage.market_validation_version == "v1"
    assert "v1" in result.lineage.market_validation_versions()
    assert result.lineage.regime_version is None


def test_market_validator_consumes_all_five_dimensions() -> None:
    """测试市场验证完整消费 5 维输入（流动性、个股趋势、行业超额、相对基准强弱、量比配合）。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr(
            "600519.SH", "avg_amount_20d", 500_000_000.0
        ),  # 维度 5: 流动性 >= 1.5 亿 (+1)
        _fr("600519.SH", "ret_20d", 0.08),  # 维度 1: 个股趋势 (+1)
        _fr("600519.SH", "proximity_52w_high", 0.90),
    )
    ctx = MarketValidationContext(
        symbol="600519.SH",
        strategy_id="growth",
        as_of=AS_OF,
        factors=factors,
        industry_excess_return=0.035,  # 维度 2: 行业超额 (+1)
        relative_strength_60d=0.062,  # 维度 3: 相对基准超额 (+1)
        vol_ratio=1.25,  # 维度 4: 量价配合 (+1)
    )
    result = validator.validate(ctx)
    assert result.status == MarketValidation.CONFIRMED
    assert result.positive_count == 5
    assert result.negative_count == 0
    assert any("相对基准" in r and "+6.20%" in r for r in result.reasons)
    assert any("行业" in r for r in result.reasons)
    assert any("量比" in r for r in result.reasons)


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
        as_of=AS_OF,
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
    as_of: datetime = AS_OF,
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
        as_of=AS_OF,
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
