"""市场与信号决策就绪分布报告 (Market & Signal Decision Readiness).

用于为项目所有者审定 Market Regime / Market Validation / Signal 提供真实分布证据。
核心红线：
1. 本模块严格只读，仅暴露分布统计与样本数据；
2. 严禁生成 MarketRegime/MarketValidation/Signal 的判决枚举；
3. 缺失值 (NULL/NOT_APPLICABLE/STALE) 严禁默认兜底为 0；
4. 严禁 Candidate Publishing。
"""

import json
from collections.abc import Sequence
from datetime import datetime

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.models import StrategyQualification

TECHNICAL_METRICS: tuple[str, ...] = (
    "ret_20d",
    "ret_60d",
    "proximity_52w_high",
    "avg_amount_20d",
)


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


class StrategyTechnicalReadiness(DomainRecord):
    """单个策略合格标的的技术特征就绪度分布。"""

    strategy_id: str
    qualified_count: int
    metrics: tuple[MetricDistribution, ...]


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

        strategies.append(
            StrategyTechnicalReadiness(
                strategy_id=strat_id,
                qualified_count=q_count,
                metrics=tuple(dist_list),
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

    lines.append("## 2. 缺失的宏观/市场输入项")
    lines.append("")
    for item in report.missing_inputs:
        lines.append(f"- `{item}`: 尚未纳入数据源或尚未定义计算")
    lines.append("")

    return "\n".join(lines)
