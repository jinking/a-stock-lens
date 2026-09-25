"""市场阶段（市场证据、行业证据、信号就绪、基准证据）长尾用例。

本文件由 Task 12「文件合并」把以下 4 个同域小文件整体搬入：
    - tests/unit/test_market_evidence.py（6 例）
    - tests/unit/test_industry_market_evidence.py（2 例）
    - tests/unit/test_market_signal_readiness.py（5 例）
    - tests/unit/test_benchmark_evidence.py（4 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from astock_lens.calibration.market_signal_readiness import (
    build_market_signal_readiness,
    render_readiness_markdown,
)
from astock_lens.data.industry import IndustryMembership
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DailyBar, SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.market.benchmark import (
    BenchmarkEvidence,
    BenchmarkEvidenceUnavailable,
    compute_benchmark_evidence,
)
from astock_lens.market.evidence import StockMarketEvidence, build_stock_market_evidence
from astock_lens.market.industry import (
    IndustryEvidence,
    IndustryEvidenceUnavailable,
    build_industry_evidence,
)
from astock_lens.qualifications.models import StrategyQualification

# ===========================================================================
# 来源：tests/unit/test_market_evidence.py（6 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Stock market evidence tests.
#
# Auditable evidence layer: ensures volume ratio is computed deterministically
# from validated bars without future leakage and without silent fallbacks.
#


MARKET_EVIDENCE_AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def _factor_result(
    factor: str, value: float | None, status: DataStatus = DataStatus.VALUE
) -> FactorResult:
    return FactorResult(
        symbol="600519.SH",
        factor=factor,
        as_of=MARKET_EVIDENCE_AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _bar(day_offset: int, volume: float) -> DailyBar:
    trade_date = MARKET_EVIDENCE_AS_OF.date() - timedelta(days=25 - day_offset)
    return DailyBar(
        symbol="600519.SH",
        trade_date=trade_date,
        open=100.0,
        high=105.0,
        low=99.0,
        close=102.0,
        volume=volume,
        amount=volume * 102.0,
    )


def test_build_stock_market_evidence_computes_exact_volume_ratio() -> None:
    # 20 根有效 bar：前 15 根 volume 为 1000.0，后 5 根 volume 为 2000.0
    # 5日均量 = 2000.0
    # 20日总成交量 = 15 * 1000 + 5 * 2000 = 25000.0，20日均量 = 1250.0
    # volume_ratio_5_20 = 2000.0 / 1250.0 = 1.60
    bars = tuple(_bar(i, 1000.0) for i in range(15)) + tuple(
        _bar(i + 15, 2000.0) for i in range(5)
    )
    factors = (
        _factor_result("ret_20d", 0.12),
        _factor_result("proximity_52w_high", 0.95),
        _factor_result("avg_amount_20d", 500_000_000.0),
    )

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=factors,
        bars=bars,
        as_of=MARKET_EVIDENCE_AS_OF,
    )

    assert isinstance(evidence, StockMarketEvidence)
    assert evidence.symbol == "600519.SH"
    assert evidence.as_of == MARKET_EVIDENCE_AS_OF
    assert evidence.ret_20d == 0.12
    assert evidence.proximity_52w_high == 0.95
    assert evidence.avg_amount_20d == 500_000_000.0
    assert evidence.volume_ratio_5_20 == pytest.approx(1.60)


def test_fewer_than_20_bars_returns_none_volume_ratio() -> None:
    # 只有 19 根 bar，数据不足以支持 20 日均线，必须返回 None 而绝非 0 或假值
    bars = tuple(_bar(i, 1000.0) for i in range(19))

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=(),
        bars=bars,
        as_of=MARKET_EVIDENCE_AS_OF,
    )

    assert evidence.volume_ratio_5_20 is None


def test_future_bars_are_strictly_excluded() -> None:
    # 20 根历史 bar，外加 2 根 as_of 之后的未来 bar
    past_bars = tuple(_bar(i, 1000.0) for i in range(20))
    future_bars = (
        DailyBar(
            symbol="600519.SH",
            trade_date=MARKET_EVIDENCE_AS_OF.date() + timedelta(days=1),
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.0,
            volume=50000.0,
        ),
        DailyBar(
            symbol="600519.SH",
            trade_date=MARKET_EVIDENCE_AS_OF.date() + timedelta(days=2),
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.0,
            volume=50000.0,
        ),
    )

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=(),
        bars=past_bars + future_bars,
        as_of=MARKET_EVIDENCE_AS_OF,
    )

    # 历史 20 根均量 1000.0，5日与20日均为 1000.0，比率为 1.0
    # 若泄漏未来数据，比率会畸高
    assert evidence.volume_ratio_5_20 == pytest.approx(1.0)


def test_missing_or_error_factors_become_none() -> None:
    factors = (
        _factor_result("ret_20d", None, status=DataStatus.NULL),
        _factor_result("proximity_52w_high", 0.80, status=DataStatus.SOURCE_ERROR),
    )

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=factors,
        bars=(),
        as_of=MARKET_EVIDENCE_AS_OF,
    )

    assert evidence.ret_20d is None
    assert evidence.proximity_52w_high is None
    assert evidence.avg_amount_20d is None
    assert evidence.volume_ratio_5_20 is None
    assert evidence.relative_strength_60d is None


def test_relative_strength_60d_exact_calculation() -> None:
    # 个股 ret_60d = 0.25, 基准 ret_60d = 0.10
    # 相对强弱 = 0.25 - 0.10 = 0.15
    factors = (_factor_result("ret_60d", 0.25),)

    evidence = build_stock_market_evidence(
        symbol="600519.SH",
        factors=factors,
        bars=(),
        as_of=MARKET_EVIDENCE_AS_OF,
        benchmark_ret_60d=0.10,
    )

    assert evidence.relative_strength_60d == pytest.approx(0.15)


# 「相对强弱的输入缺失」两行：行序与原用例一致，label 即原测试名。
# 列 = label, payload, expected：
#   - `payload` 逐行保留原 `build_stock_market_evidence(...)` 的关键字参数
#     （第 1 行的 `factors = (...)` 绑定按同一表达式内联）；
#   - `expected` 是该行断言的 `relative_strength_60d` 期望值（原断言为 `is None`），
#     比对方式同为 `is`。
MARKET_EVIDENCE_MISSING_INPUT_CASES = (
    # test_missing_benchmark_ret_60d_results_in_none
    (
        "test_missing_benchmark_ret_60d_results_in_none",
        {
            "symbol": "600519.SH",
            "factors": (_factor_result("ret_60d", 0.25),),
            "bars": (),
            "as_of": MARKET_EVIDENCE_AS_OF,
            "benchmark_ret_60d": None,
        },
        None,
    ),
    # test_missing_stock_ret_60d_results_in_none
    (
        "test_missing_stock_ret_60d_results_in_none",
        {
            "symbol": "600519.SH",
            "factors": (),
            "bars": (),
            "as_of": MARKET_EVIDENCE_AS_OF,
            "benchmark_ret_60d": 0.10,
        },
        None,
    ),
)


def test_missing_relative_strength_inputs_result_in_none() -> None:
    """缺基准或个股 ret_60d 时相对强弱必须是 None，绝不静默兜底。

    原 2 条「results_in_none」用例逐条成行；循环只收集，断言在表外一次完成，
    失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, payload, expected in MARKET_EVIDENCE_MISSING_INPUT_CASES:
        evidence = build_stock_market_evidence(**payload)
        if evidence.relative_strength_60d is not expected:
            wrong.append(
                f"{label}: relative_strength_60d 为 {evidence.relative_strength_60d!r}，"
                f"期望 {expected!r}"
            )
    assert not wrong, "相对强弱未对缺失输入返回 None:\n" + "\n".join(wrong)


# ===========================================================================
# 来源：tests/unit/test_industry_market_evidence.py（2 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Industry market evidence unit tests.
#
# Auditable industry evidence tests:
# - Strict rejection when SW1 is requested but only SW2 exists (no relabeling);
# - Strict fail-closed when benchmark or membership is missing;
# - Exact calculation of industry 20d return and excess return.
#


INDUSTRY_EVIDENCE_AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def _membership(
    symbol: str,
    industry_id: str = "pt001",
    name: str = "股份制银行Ⅱ",
) -> IndustryMembership:
    return IndustryMembership(
        symbol=symbol,
        industry_id=industry_id,
        industry_name=name,
        as_of=INDUSTRY_EVIDENCE_AS_OF,
        provider="westock-cli",
    )


def _sw1_requested_kwargs() -> dict[str, object]:
    """第 1 行的输入：请求 SW1；原用例的 `membership = _membership(...)` 逐字保留。"""
    membership = _membership("600036.SH")
    return {
        "symbol": "600036.SH",
        "membership": membership,
        "all_memberships": (membership,),
        "member_returns_20d": {"600036.SH": 0.05},
        "benchmark_return_20d": 0.02,
        "requested_level": "SW1",
        "as_of": INDUSTRY_EVIDENCE_AS_OF,
    }


def _missing_benchmark_kwargs() -> dict[str, object]:
    """第 2 行的输入：基准收益率缺失；原用例的 `m = _membership(...)` 逐字保留。"""
    m = _membership("600036.SH")
    return {
        "symbol": "600036.SH",
        "membership": m,
        "all_memberships": (m,),
        "member_returns_20d": {"600036.SH": 0.05},
        "benchmark_return_20d": None,
        "requested_level": "SW2",
        "as_of": INDUSTRY_EVIDENCE_AS_OF,
    }


def _unmapped_symbol_kwargs() -> dict[str, object]:
    """第 3 行的输入：标的不在行业成员表内。"""
    return {
        "symbol": "600036.SH",
        "membership": None,
        "all_memberships": (),
        "member_returns_20d": {},
        "benchmark_return_20d": 0.02,
        "requested_level": "SW2",
        "as_of": INDUSTRY_EVIDENCE_AS_OF,
    }


def _no_valid_member_returns_kwargs() -> dict[str, object]:
    """第 4 行的输入：成员表非空但没有有效的 20d 收益。"""
    m = _membership("600036.SH")
    return {
        "symbol": "600036.SH",
        "membership": m,
        "all_memberships": (m,),
        "member_returns_20d": {},
        "benchmark_return_20d": 0.02,
        "requested_level": "SW2",
        "as_of": INDUSTRY_EVIDENCE_AS_OF,
    }


# 「行业证据必须显式失败」四行：行序与原用例一致，label 即原测试名；
# 列 = label, payload, expected_fragments：
#   - `payload` 为零参可调用，返回 `build_industry_evidence` 的关键字参数
#     （原用例的就地绑定原样保留在对应函数体内）；
#   - `expected_fragments` 逐字取自原 `assert "<片段>" in str(exc_info.value)`，
#     比对方式同为 `in`。
INDUSTRY_EVIDENCE_REJECTION_CASES = (
    # test_sw1_requested_raises_industry_evidence_unavailable:
    #   规范来源仅有申万二级（SW2），请求 SW1 必须抛出 IndustryEvidenceUnavailable，绝不伪标
    (
        "test_sw1_requested_raises_industry_evidence_unavailable",
        _sw1_requested_kwargs,
        ("SW1 hierarchy unavailable", "SW2 is supported"),
    ),
    # test_missing_benchmark_raises_industry_evidence_unavailable
    (
        "test_missing_benchmark_raises_industry_evidence_unavailable",
        _missing_benchmark_kwargs,
        ("Benchmark return is missing",),
    ),
    # test_unmapped_symbol_raises_industry_evidence_unavailable
    (
        "test_unmapped_symbol_raises_industry_evidence_unavailable",
        _unmapped_symbol_kwargs,
        ("No industry membership",),
    ),
    # test_no_valid_member_returns_raises_industry_evidence_unavailable
    (
        "test_no_valid_member_returns_raises_industry_evidence_unavailable",
        _no_valid_member_returns_kwargs,
        ("No valid 20d returns found",),
    ),
)


def test_industry_evidence_unavailable_rejections() -> None:
    """四种缺失/越级请求各自抛出 IndustryEvidenceUnavailable，消息点名原因。

    原 4 条「raises_industry_evidence_unavailable」用例逐条成行；循环只收集，
    断言在表外一次完成，失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, payload, expected_fragments in INDUSTRY_EVIDENCE_REJECTION_CASES:
        arguments = payload()
        try:
            build_industry_evidence(**arguments)
        except IndustryEvidenceUnavailable as exc:
            message = str(exc)
            for fragment in expected_fragments:
                if fragment not in message:
                    wrong.append(
                        f"{label}: 错误信息缺少 {fragment!r}，实际 {message!r}"
                    )
        else:
            wrong.append(f"{label}: 未抛出 IndustryEvidenceUnavailable")
    assert not wrong, "行业证据未显式失败:\n" + "\n".join(wrong)


def test_exact_industry_excess_calculation() -> None:
    # 行业内 3 只标的，20d 收益率分别为 0.04, 0.06, 0.08 -> 行业均值 0.06
    # 基准 20d 收益率 = 0.02
    # 行业超额收益率 = 0.06 - 0.02 = 0.04
    m1 = _membership("600036.SH")
    m2 = _membership("601998.SH")
    m3 = _membership("600000.SH")

    evidence = build_industry_evidence(
        symbol="600036.SH",
        membership=m1,
        all_memberships=(m1, m2, m3),
        member_returns_20d={
            "600036.SH": 0.04,
            "601998.SH": 0.06,
            "600000.SH": 0.08,
        },
        benchmark_return_20d=0.02,
        requested_level="SW2",
        as_of=INDUSTRY_EVIDENCE_AS_OF,
    )

    assert isinstance(evidence, IndustryEvidence)
    assert evidence.symbol == "600036.SH"
    assert evidence.industry_id == "pt001"
    assert evidence.industry_level == "SW2"
    assert evidence.industry_return_20d == pytest.approx(0.06)
    assert evidence.benchmark_return_20d == pytest.approx(0.02)
    assert evidence.industry_excess_return_20d == pytest.approx(0.04)
    assert evidence.member_count == 3
    assert evidence.as_of == INDUSTRY_EVIDENCE_AS_OF


# ===========================================================================
# 来源：tests/unit/test_market_signal_readiness.py（5 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 市场与信号决策就绪分布报告测试 (Plan C Task 1).
#
# 验证：
# - 确定性分位数：不同输入顺序产出完全相同的 p10/p25/p50/p75/p90；
# - 缺失值纪律：NULL/NOT_APPLICABLE/STALE 永不退化为数值 0；
# - 合格标的范围：严格仅针对各策略合格标的 (StrategyQualification.qualified == True)；
# - 严禁枚举越界：报告中绝对不出现 MarketRegime/MarketValidation/Signal 判决枚举。
#


SHANGHAI = ZoneInfo("Asia/Shanghai")


SIGNAL_READINESS_AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=SHANGHAI)


def _fr(
    symbol: str,
    factor: str,
    value: float | None,
    status: DataStatus = DataStatus.VALUE,
) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=factor,
        as_of=SIGNAL_READINESS_AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(),
        raw_value=value,
    )


def _sq(
    symbol: str,
    strategy_id: str,
    qualified: bool,
) -> StrategyQualification:
    return StrategyQualification(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        qualification_version="v1",
        qualified=qualified,
        percentile_pass=qualified,
        absolute_pass=qualified,
        rank_percentile=0.95 if qualified else 0.5,
        reasons=(),
        risks=(),
    )


def test_deterministic_quantiles_under_different_input_orders() -> None:
    """Step 1: 无论输入顺序如何，分位数计算完全一致且确定。"""
    strategy_id = "value"
    qualifications = [
        _sq("000001.SZ", strategy_id, qualified=True),
        _sq("000002.SZ", strategy_id, qualified=True),
        _sq("000003.SZ", strategy_id, qualified=True),
        _sq("000004.SZ", strategy_id, qualified=True),
        _sq("000005.SZ", strategy_id, qualified=True),
    ]

    # 正序
    factors_order1 = [
        _fr("000001.SZ", "ret_20d", 0.05),
        _fr("000002.SZ", "ret_20d", 0.10),
        _fr("000003.SZ", "ret_20d", 0.15),
        _fr("000004.SZ", "ret_20d", 0.20),
        _fr("000005.SZ", "ret_20d", 0.25),
    ]
    # 逆序
    factors_order2 = list(reversed(factors_order1))

    report1 = build_market_signal_readiness(
        as_of=SIGNAL_READINESS_AS_OF,
        qualifications=qualifications,
        factor_results=factors_order1,
    )
    report2 = build_market_signal_readiness(
        as_of=SIGNAL_READINESS_AS_OF,
        qualifications=qualifications,
        factor_results=factors_order2,
    )

    strat1 = next(s for s in report1.strategies if s.strategy_id == strategy_id)
    strat2 = next(s for s in report2.strategies if s.strategy_id == strategy_id)

    m1 = next(m for m in strat1.metrics if m.metric == "ret_20d")
    m2 = next(m for m in strat2.metrics if m.metric == "ret_20d")

    assert m1.p10 == m2.p10 == 0.05
    assert m1.p25 == m2.p25 == 0.10
    assert m1.p50 == m2.p50 == 0.15
    assert m1.p75 == m2.p75 == 0.20
    assert m1.p90 == m2.p90 == 0.25
    assert m1.count == m2.count == 5
    assert m1.missing == m2.missing == 0


def test_missing_values_never_become_zero() -> None:
    """Step 2: 缺失数据 (NULL/NOT_APPLICABLE/STALE) 严禁转为 0，只能计入 missing。"""
    strategy_id = "growth"
    qualifications = [
        _sq("000001.SZ", strategy_id, qualified=True),
        _sq("000002.SZ", strategy_id, qualified=True),
        _sq("000003.SZ", strategy_id, qualified=True),
        _sq("000004.SZ", strategy_id, qualified=True),
    ]

    factors = [
        _fr("000001.SZ", "proximity_52w_high", 0.95, DataStatus.VALUE),
        _fr("000002.SZ", "proximity_52w_high", None, DataStatus.NULL),
        _fr("000003.SZ", "proximity_52w_high", None, DataStatus.NOT_APPLICABLE),
        _fr("000004.SZ", "proximity_52w_high", None, DataStatus.STALE),
    ]

    report = build_market_signal_readiness(
        as_of=SIGNAL_READINESS_AS_OF,
        qualifications=qualifications,
        factor_results=factors,
    )

    strat = next(s for s in report.strategies if s.strategy_id == strategy_id)
    dist = next(m for m in strat.metrics if m.metric == "proximity_52w_high")

    assert dist.count == 1
    assert dist.missing == 3
    assert dist.p50 == 0.95
    assert dist.p10 == 0.95


def test_scope_strictly_restricted_to_qualified_stocks() -> None:
    """Step 3: 只有 qualified == True 的标的才能进入分布，不合格标的严格排除。"""
    strategy_id = "quality"
    qualifications = [
        _sq("000001.SZ", strategy_id, qualified=True),
        _sq("000002.SZ", strategy_id, qualified=False),  # 不合格
    ]

    factors = [
        _fr("000001.SZ", "ret_60d", 0.30),
        _fr("000002.SZ", "ret_60d", -0.50),  # 不应计入
    ]

    report = build_market_signal_readiness(
        as_of=SIGNAL_READINESS_AS_OF,
        qualifications=qualifications,
        factor_results=factors,
    )

    strat = next(s for s in report.strategies if s.strategy_id == strategy_id)
    assert strat.qualified_count == 1

    dist = next(m for m in strat.metrics if m.metric == "ret_60d")
    assert dist.count == 1
    assert dist.p50 == 0.30
    assert -0.50 not in (dist.p10, dist.p25, dist.p50, dist.p75, dist.p90)


def test_representative_sampling_deterministic_with_tie_breaking() -> None:
    """Task 3 Step 1 & Step 2: 极值采样，平局按 symbol 升序，携带原始状态与数值。"""
    strategy_id = "momentum"
    qualifications = [
        _sq("000001.SZ", strategy_id, qualified=True),
        _sq("000002.SZ", strategy_id, qualified=True),
        _sq("000003.SZ", strategy_id, qualified=True),
    ]

    # 000001.SZ 与 000002.SZ 平局具有相同最高的 ret_20d (0.50)
    # 000003.SZ 具有最低的 ret_20d (-0.20)
    factors = [
        _fr("000001.SZ", "ret_20d", 0.50),
        _fr("000002.SZ", "ret_20d", 0.50),
        _fr("000003.SZ", "ret_20d", -0.20),
        _fr("000001.SZ", "proximity_52w_high", 0.95),
        _fr("000002.SZ", "proximity_52w_high", 0.70),
    ]

    report = build_market_signal_readiness(
        as_of=SIGNAL_READINESS_AS_OF,
        qualifications=qualifications,
        factor_results=factors,
    )

    strat = next(s for s in report.strategies if s.strategy_id == strategy_id)

    highest_sample = next(
        s for s in strat.samples if s.metric == "ret_20d" and s.sample_kind == "highest"
    )
    lowest_sample = next(
        s for s in strat.samples if s.metric == "ret_20d" and s.sample_kind == "lowest"
    )

    # 平局时 symbol 升序：000001.SZ < 000002.SZ
    assert highest_sample.symbol == "000001.SZ"
    assert highest_sample.raw_value == 0.50
    assert highest_sample.status == DataStatus.VALUE

    assert lowest_sample.symbol == "000003.SZ"
    assert lowest_sample.raw_value == -0.20
    assert lowest_sample.status == DataStatus.VALUE

    closest_sample = next(
        s
        for s in strat.samples
        if s.metric == "proximity_52w_high" and s.sample_kind == "closest"
    )
    farthest_sample = next(
        s
        for s in strat.samples
        if s.metric == "proximity_52w_high" and s.sample_kind == "farthest"
    )
    assert closest_sample.symbol == "000001.SZ"
    assert closest_sample.raw_value == 0.95
    assert farthest_sample.symbol == "000002.SZ"
    assert farthest_sample.raw_value == 0.70

    md = render_readiness_markdown(report)
    assert "#### 代表性边界样本" in md
    assert "附录：未来规则词表" in md
    assert "CONFIRMED" in md
    assert "BREAKOUT" in md

    payload = report.to_payload()
    strat_payload = payload["strategies"][0]  # type: ignore[index]
    assert len(strat_payload["samples"]) > 0  # type: ignore[index]


def test_assert_vocabulary_boundary_no_verdict_fields() -> None:
    """Task 3 Step 3: 严禁在报告模型中出现判决字段或判决枚举。"""
    strategy_id = "value"
    qualifications = [_sq("000001.SZ", strategy_id, qualified=True)]
    factors = [_fr("000001.SZ", "ret_20d", 0.10)]

    report = build_market_signal_readiness(
        as_of=SIGNAL_READINESS_AS_OF,
        qualifications=qualifications,
        factor_results=factors,
    )

    payload = report.to_payload()
    # 转换为 JSON 字符串检查 key 与 value
    json_str = str(payload)
    for forbidden_verdict_key in (
        "market_regime",
        "market_validation",
        "signal",
        "verdict",
    ):
        assert forbidden_verdict_key not in json_str


# ===========================================================================
# 来源：tests/unit/test_benchmark_evidence.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Benchmark market evidence unit tests.
#
# Auditable benchmark evidence tests:
# - Strict fail-closed when benchmark series or bars are insufficient (< 60 bars);
# - Deterministic calculation of ret_60d and trend_value (ma_20 / ma_60);
# - No future bar leakage.
#


AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def _benchmark_bar(
    day_offset: int, close: float, benchmark_id: str = "000300.SH"
) -> DailyBar:
    trade_date = AS_OF.date() - timedelta(days=100 - day_offset)
    return DailyBar(
        symbol=benchmark_id,
        trade_date=trade_date,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=100000.0,
    )


def test_compute_benchmark_evidence_exact_calculation() -> None:
    # 构造 60 根 bar：前 40 根收盘价 3000.0，后 20 根收盘价 3300.0
    # close_60_ago = 3000.0, close_latest = 3300.0
    # ret_60d = (3300 - 3000) / 3000 = +0.10 (+10.0%)
    # ma_20 = 3300.0
    # ma_60 = (40 * 3000 + 20 * 3300) / 60 = (120000 + 66000) / 60 = 186000 / 60 = 3100.0
    # trend_value = 3300.0 / 3100.0 = 1.064516...
    bars = tuple(_benchmark_bar(i, 3000.0) for i in range(40)) + tuple(
        _benchmark_bar(i + 40, 3300.0) for i in range(20)
    )

    evidence = compute_benchmark_evidence(
        benchmark_id="000300.SH",
        bars=bars,
        as_of=AS_OF,
        source="test_fixture",
    )

    assert isinstance(evidence, BenchmarkEvidence)
    assert evidence.benchmark_id == "000300.SH"
    assert evidence.as_of == AS_OF
    assert evidence.ret_60d == pytest.approx(0.10)
    assert evidence.trend_value == pytest.approx(3300.0 / 3100.0)
    assert evidence.source == "test_fixture"


def test_insufficient_bars_raises_benchmark_evidence_unavailable() -> None:
    # 仅 59 根 bar，不足 60 根窗口，必须抛出 BenchmarkEvidenceUnavailable，绝不静默兜底
    bars = tuple(_benchmark_bar(i, 3000.0) for i in range(59))

    with pytest.raises(BenchmarkEvidenceUnavailable) as exc_info:
        compute_benchmark_evidence(
            benchmark_id="000300.SH",
            bars=bars,
            as_of=AS_OF,
        )

    assert "Insufficient benchmark bars" in str(exc_info.value)
    assert "000300.SH" in str(exc_info.value)


def test_empty_bars_raises_benchmark_evidence_unavailable() -> None:
    with pytest.raises(BenchmarkEvidenceUnavailable):
        compute_benchmark_evidence(
            benchmark_id="000300.SH",
            bars=(),
            as_of=AS_OF,
        )


def test_future_bars_strictly_excluded() -> None:
    # 60 根历史 bar，各收盘价 3000.0；另有 2 根未来 bar，收盘价 9999.0
    past_bars = tuple(_benchmark_bar(i, 3000.0) for i in range(60))
    future_bars = (
        DailyBar(
            symbol="000300.SH",
            trade_date=AS_OF.date() + timedelta(days=1),
            open=9999.0,
            high=9999.0,
            low=9999.0,
            close=9999.0,
            volume=100000.0,
        ),
        DailyBar(
            symbol="000300.SH",
            trade_date=AS_OF.date() + timedelta(days=2),
            open=9999.0,
            high=9999.0,
            low=9999.0,
            close=9999.0,
            volume=100000.0,
        ),
    )

    evidence = compute_benchmark_evidence(
        benchmark_id="000300.SH",
        bars=past_bars + future_bars,
        as_of=AS_OF,
    )

    # 历史 60 根均为 3000.0，ret_60d = 0.0, trend_value = 1.0
    assert evidence.ret_60d == pytest.approx(0.0)
    assert evidence.trend_value == pytest.approx(1.0)
