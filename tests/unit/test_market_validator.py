"""Market validation 5-dimension matrix unit tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from astock_lens.domain.enums import DataStatus, MarketValidation
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.market.validation import (
    MarketValidationContext,
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
        _fr("601398.SH", "ret_60d", 0.15),
        _fr("601398.SH", "proximity_52w_high", 0.95),
    )
    ctx = MarketValidationContext(
        symbol="601398.SH",
        strategy_id="momentum",
        as_of=AS_OF,
        factors=factors,
    )
    result = validator.validate(ctx)
    assert isinstance(result, MarketValidationResult)
    assert result.status == MarketValidation.CONTRADICTED
    assert any("流动性" in r and "警戒线" in r for r in result.risks)


def test_market_validator_two_negatives_contradicted() -> None:
    """测试负向冲突项数 >= 2 时输出 CONTRADICTED（破位 + 中期严重亏损）。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr("688525.SH", "avg_amount_20d", 300_000_000.0),  # 3.0 亿 流动性达标
        _fr("688525.SH", "ret_20d", -0.18),  # 负向项 1: 跌幅超过 15%
        _fr("688525.SH", "ret_60d", -0.35),  # 负向项 2: 60日跌幅超过 20%
        _fr("688525.SH", "proximity_52w_high", 0.50),
    )
    ctx = MarketValidationContext(
        symbol="688525.SH",
        strategy_id="growth",
        as_of=AS_OF,
        factors=factors,
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
        _fr("300741.SZ", "ret_60d", 0.40),  # > 0
        _fr("300741.SZ", "proximity_52w_high", 0.98),  # > 0.85
    )
    ctx = MarketValidationContext(
        symbol="300741.SZ",
        strategy_id="momentum",
        as_of=AS_OF,
        factors=factors,
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
        _fr("600000.SH", "ret_60d", 0.02),
        _fr("600000.SH", "proximity_52w_high", 0.75),
    )
    ctx = MarketValidationContext(
        symbol="600000.SH",
        strategy_id="value",
        as_of=AS_OF,
        factors=factors,
    )
    result = validator.validate(ctx)
    assert result.status == MarketValidation.NEUTRAL
    assert result.negative_count == 0


def test_market_validator_missing_liquidity_factor_fail_closed() -> None:
    """测试当缺少流动性因子时，绝不静默兜底，必须记入 risk 且不判定为 CONFIRMED。"""
    validator = MarketValidator(version="v1")
    factors = (
        _fr("000001.SZ", "ret_20d", 0.05),
        _fr("000001.SZ", "ret_60d", 0.10),
    )
    ctx = MarketValidationContext(
        symbol="000001.SZ",
        strategy_id="momentum",
        as_of=AS_OF,
        factors=factors,
    )
    result = validator.validate(ctx)
    assert result.status != MarketValidation.CONFIRMED
    assert any("avg_amount_20d" in r for r in result.risks)


def test_market_validator_lineage_contains_market_validation_version() -> None:
    """测试 MarketValidationResult 的 lineage 携带 market_validation_version 且不复用 regime_version。"""
    validator = MarketValidator(version="v1")
    factors = (_fr("601398.SH", "avg_amount_20d", 80_000_000.0),)
    ctx = MarketValidationContext(
        symbol="601398.SH",
        strategy_id="momentum",
        as_of=AS_OF,
        factors=factors,
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
        relative_strength_60d=-0.18,  # < -15%
    )
    result = validator.validate(ctx)
    assert result.negative_count >= 1
    assert any("相对基准" in r and "落后" in r for r in result.risks)
