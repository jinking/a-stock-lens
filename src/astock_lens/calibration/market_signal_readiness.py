"""市场与信号决策就绪分布报告 (Market & Signal Decision Readiness).

用于为项目所有者审定 Market Regime / Market Validation / Signal 提供真实分布证据。
核心红线：
1. 本模块严格只读，仅暴露分布统计与样本数据；
2. 严禁生成 MarketRegime/MarketValidation/Signal 的判决枚举；
3. 缺失值 (NULL/NOT_APPLICABLE/STALE) 严禁默认兜底为 0；
4. 严禁 Candidate Publishing。
"""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.contracts import StrategyQualifier
from astock_lens.qualifications.models import (
    QualificationContext,
    StrategyQualification,
)
from astock_lens.strategies.contracts import StrategyResult

TECHNICAL_METRICS: tuple[str, ...] = (
    "ret_20d",
    "ret_60d",
    "proximity_52w_high",
    "avg_amount_20d",
)


def compute_strategy_qualifications(
    strategy_results: Sequence[StrategyResult],
    factor_results: Sequence[FactorResult],
    qualifiers: Mapping[str, StrategyQualifier],
) -> tuple[StrategyQualification, ...]:
    """计算各策略标的的双门槛合格结果。"""
    factors_by_symbol: dict[str, list[FactorResult]] = {}
    for factor in factor_results:
        factors_by_symbol.setdefault(factor.symbol, []).append(factor)

    quals: list[StrategyQualification] = []
    for r in strategy_results:
        if r.eligible and r.rank_percentile is not None and r.strategy_id in qualifiers:
            qualifier = qualifiers[r.strategy_id]
            q = qualifier.qualify(
                QualificationContext(
                    strategy_result=r,
                    factors=tuple(factors_by_symbol.get(r.symbol, ())),
                )
            )
            quals.append(q)
    return tuple(quals)


class MetricDistribution(DomainRecord):
    """一个技术指标在合格标的上的确定性分位数分布。"""

    metric: str
    count: int
    missing: int
    p10: float | None
    p25: float | None
    p50: float | None
    p75: float | None
    p90: float | None


class MetricSample(DomainRecord):
    """技术指标的代表性边界样本。"""

    symbol: str
    metric: str
    sample_kind: str
    raw_value: float | None
    status: DataStatus


class StrategyTechnicalReadiness(DomainRecord):
    """单个策略合格标的的技术特征就绪度分布。"""

    strategy_id: str
    qualified_count: int
    metrics: tuple[MetricDistribution, ...]
    samples: tuple[MetricSample, ...] = ()


class MarketSignalReadinessReport(DomainRecord):
    """全策略市场与信号决策就绪报告。"""

    as_of: datetime
    strategies: tuple[StrategyTechnicalReadiness, ...]
    missing_inputs: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        """输出适合 JSON 序列化的字典。"""
        return self.model_dump(mode="json")


def _compute_quantile(sorted_values: Sequence[float], fraction: float) -> float | None:
    """最近秩法取分位数：确定性，不插值。"""
    if not sorted_values:
        return None
    pos = min(
        len(sorted_values) - 1, max(0, round(fraction * (len(sorted_values) - 1)))
    )
    return sorted_values[pos]


def build_market_signal_readiness(
    as_of: datetime,
    qualifications: Sequence[StrategyQualification],
    factor_results: Sequence[FactorResult],
    metrics: Sequence[str] = TECHNICAL_METRICS,
) -> MarketSignalReadinessReport:
    """基于各策略合格标的与技术因子计算分布。"""
    # 按策略归类 qualification 记录
    quals_by_strat: dict[str, list[StrategyQualification]] = {}
    for q in qualifications:
        quals_by_strat.setdefault(q.strategy_id, []).append(q)

    # 建立 factor_map
    factor_map: dict[tuple[str, str], FactorResult] = {
        (fr.symbol, fr.factor): fr for fr in factor_results
    }

    strategies: list[StrategyTechnicalReadiness] = []
    for strat_id in sorted(quals_by_strat):
        strat_quals = quals_by_strat[strat_id]
        qualified_symbols = sorted({q.symbol for q in strat_quals if q.qualified})
        q_count = len(qualified_symbols)

        dist_list: list[MetricDistribution] = []
        for metric in metrics:
            values: list[float] = []
            missing = 0
            for sym in qualified_symbols:
                fr = factor_map.get((sym, metric))
                if (
                    fr is not None
                    and fr.status == DataStatus.VALUE
                    and fr.raw_value is not None
                ):
                    values.append(fr.raw_value)
                else:
                    missing += 1

            sorted_vals = sorted(values)
            dist_list.append(
                MetricDistribution(
                    metric=metric,
                    count=len(sorted_vals),
                    missing=missing,
                    p10=_compute_quantile(sorted_vals, 0.10),
                    p25=_compute_quantile(sorted_vals, 0.25),
                    p50=_compute_quantile(sorted_vals, 0.50),
                    p75=_compute_quantile(sorted_vals, 0.75),
                    p90=_compute_quantile(sorted_vals, 0.90),
                )
            )

        samples: list[MetricSample] = []
        for metric in metrics:
            valid_factors: list[FactorResult] = []
            for sym in qualified_symbols:
                fr = factor_map.get((sym, metric))
                if (
                    fr is not None
                    and fr.status == DataStatus.VALUE
                    and fr.raw_value is not None
                ):
                    valid_factors.append(fr)

            if valid_factors:
                # 最高/最近：数值降序，平局按 symbol 升序
                best_high = min(
                    valid_factors,
                    key=lambda f: (-cast(float, f.raw_value), f.symbol),
                )
                # 最低/最远：数值升序，平局按 symbol 升序
                best_low = min(
                    valid_factors,
                    key=lambda f: (cast(float, f.raw_value), f.symbol),
                )

                high_kind = "closest" if metric == "proximity_52w_high" else "highest"
                low_kind = "farthest" if metric == "proximity_52w_high" else "lowest"

                samples.append(
                    MetricSample(
                        symbol=best_high.symbol,
                        metric=metric,
                        sample_kind=high_kind,
                        raw_value=best_high.raw_value,
                        status=best_high.status,
                    )
                )
                samples.append(
                    MetricSample(
                        symbol=best_low.symbol,
                        metric=metric,
                        sample_kind=low_kind,
                        raw_value=best_low.raw_value,
                        status=best_low.status,
                    )
                )

        strategies.append(
            StrategyTechnicalReadiness(
                strategy_id=strat_id,
                qualified_count=q_count,
                metrics=tuple(dist_list),
                samples=tuple(samples),
            )
        )

    # 记录目前市场上缺失的输入类别（如宽度、波动率等尚未实现的证据）
    missing_inputs = (
        "market_breadth",
        "market_volatility",
        "benchmark_index_trend",
    )

    return MarketSignalReadinessReport(
        as_of=as_of,
        strategies=tuple(strategies),
        missing_inputs=missing_inputs,
    )


def render_readiness_json(report: MarketSignalReadinessReport) -> str:
    """确定性渲染 JSON 格式报告。"""
    return json.dumps(report.to_payload(), ensure_ascii=False, indent=2) + "\n"


def render_readiness_markdown(report: MarketSignalReadinessReport) -> str:
    """确定性渲染 Markdown 格式报告。"""
    lines: list[str] = [
        "# 市场与信号决策就绪分布报告",
        "",
        f"- **基准时间 (as_of)**: `{report.as_of.isoformat()}`",
        f"- **覆盖策略数**: `{len(report.strategies)}`",
        "",
        "## 1. 各策略合格标的技术因子分布",
        "",
    ]

    for strat in report.strategies:
        lines.append(
            f"### 策略: `{strat.strategy_id}` (合格标的: {strat.qualified_count} 只)"
        )
        lines.append("")
        lines.append(
            "| 因子/指标 | 有效数 | 缺失数 | P10 | P25 | P50 (中位数) | P75 | P90 |"
        )
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
        for m in strat.metrics:
            p10_str = f"{m.p10:.4f}" if m.p10 is not None else "N/A"
            p25_str = f"{m.p25:.4f}" if m.p25 is not None else "N/A"
            p50_str = f"{m.p50:.4f}" if m.p50 is not None else "N/A"
            p75_str = f"{m.p75:.4f}" if m.p75 is not None else "N/A"
            p90_str = f"{m.p90:.4f}" if m.p90 is not None else "N/A"
            lines.append(
                f"| `{m.metric}` | {m.count} | {m.missing} | {p10_str} | {p25_str} | {p50_str} | {p75_str} | {p90_str} |"
            )
        lines.append("")

        if strat.samples:
            lines.append("#### 代表性边界样本")
            lines.append("")
            lines.append("| 因子/指标 | 样本类型 | 股票代码 | 数值 | 数据状态 |")
            lines.append("| :--- | :---: | :---: | :---: | :---: |")
            for s in strat.samples:
                val_str = f"{s.raw_value:.4f}" if s.raw_value is not None else "N/A"
                lines.append(
                    f"| `{s.metric}` | `{s.sample_kind}` | `{s.symbol}` | {val_str} | `{s.status.value}` |"
                )
            lines.append("")

    lines.append("## 2. 缺失的宏观/市场输入项")
    lines.append("")
    for item in report.missing_inputs:
        lines.append(f"- `{item}`: 尚未纳入数据源或尚未定义计算")
    lines.append("")

    lines.append("## 附录：未来规则词表（当前未激活，仅作说明）")
    lines.append("")
    lines.append(
        "以下词表仅为架构预留候选词汇，**当前未激活且未在代码中执行任何判决计算**："
    )
    lines.append(
        "- **市场验证状态 (Market Validation)**: `CONFIRMED`, `NEUTRAL`, `CONTRADICTED`"
    )
    lines.append(
        "- **信号类型 (Signal)**: `BREAKOUT`, `PULLBACK`, `TREND_CONTINUE`, `TREND_WEAKEN`, `BREAKDOWN`"
    )
    lines.append("")
    lines.append("所有上述状态与信号必须由项目所有者明确审定阈值及规则后方可激活。")
    lines.append("")

    return "\n".join(lines)
