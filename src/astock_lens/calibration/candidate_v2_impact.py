"""Candidate-v2 market evidence and signal impact audit engine.

Produces auditable evidence on how Candidate v2 requirements (5D Market Validation
and multi-strategy signals) impact the qualified candidate population.
"""

from collections.abc import Collection, Sequence
from datetime import datetime

from astock_lens.domain.enums import Signal
from astock_lens.domain.models import DailyBar, DomainRecord
from astock_lens.factors.contracts import FactorResult
from astock_lens.market.evidence import build_stock_market_evidence
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.signals.contracts import SignalContext
from astock_lens.signals.detector import DefaultSignalDetector


class StrategyImpactSummary(DomainRecord):
    """Impact metrics for a single primary strategy."""

    strategy_id: str
    qualified_count: int
    complete_5d_evidence_count: int
    missing_industry_count: int
    missing_benchmark_count: int
    missing_volume_ratio_count: int
    candidate_v1_count: int
    breakdown_count: int
    trend_weaken_count: int
    no_signal_count: int


class CandidateV2ImpactReport(DomainRecord):
    """Full Candidate v2 impact audit report across all strategies."""

    as_of: datetime
    summaries: tuple[StrategyImpactSummary, ...]


def compute_candidate_v2_impact(
    *,
    qualifications: Sequence[StrategyQualification],
    factors: Sequence[FactorResult],
    bars: Sequence[DailyBar],
    industry_mapped_symbols: Collection[str],
    benchmark_available: bool,
    as_of: datetime,
) -> CandidateV2ImpactReport:
    """Compute impact summary per strategy."""
    # Group qualified symbols by strategy_id
    quals_by_strat: dict[str, list[StrategyQualification]] = {}
    for q in qualifications:
        if q.qualified:
            quals_by_strat.setdefault(q.strategy_id, []).append(q)

    detector = DefaultSignalDetector()
    factors_by_symbol: dict[str, list[FactorResult]] = {}
    for f in factors:
        factors_by_symbol.setdefault(f.symbol, []).append(f)

    summaries: list[StrategyImpactSummary] = []
    for strat_id in sorted(quals_by_strat):
        strat_quals = quals_by_strat[strat_id]
        strat_quals.sort(key=lambda item: (-(item.rank_percentile or 0.0), item.symbol))

        qualified_count = len(strat_quals)
        complete_5d = 0
        missing_industry = 0
        missing_benchmark = 0 if benchmark_available else qualified_count
        missing_vol_ratio = 0
        breakdown_cnt = 0
        trend_weaken_cnt = 0
        no_signal_cnt = 0

        for q in strat_quals:
            sym = q.symbol
            sym_factors = tuple(factors_by_symbol.get(sym, ()))
            ev = build_stock_market_evidence(
                symbol=sym,
                factors=sym_factors,
                bars=bars,
                as_of=as_of,
                benchmark_ret_60d=0.0 if benchmark_available else None,
            )

            has_vol = ev.volume_ratio_5_20 is not None
            if not has_vol:
                missing_vol_ratio += 1

            has_ind = sym in industry_mapped_symbols
            if not has_ind:
                missing_industry += 1

            if (
                ev.ret_20d is not None
                and ev.proximity_52w_high is not None
                and has_vol
                and has_ind
                and benchmark_available
            ):
                complete_5d += 1

            # Detect signal
            sig_ctx = SignalContext(
                symbol=sym,
                strategy_id=strat_id,
                as_of=as_of,
                factors=sym_factors,
            )
            sig_res = detector.detect(sig_ctx)
            if sig_res.signal == Signal.BREAKDOWN:
                breakdown_cnt += 1
            elif sig_res.signal == Signal.TREND_WEAKEN:
                trend_weaken_cnt += 1
            elif sig_res.signal == Signal.NO_SIGNAL:
                no_signal_cnt += 1

        summaries.append(
            StrategyImpactSummary(
                strategy_id=strat_id,
                qualified_count=qualified_count,
                complete_5d_evidence_count=complete_5d,
                missing_industry_count=missing_industry,
                missing_benchmark_count=missing_benchmark,
                missing_volume_ratio_count=missing_vol_ratio,
                candidate_v1_count=qualified_count,
                breakdown_count=breakdown_cnt,
                trend_weaken_count=trend_weaken_cnt,
                no_signal_count=no_signal_cnt,
            )
        )

    return CandidateV2ImpactReport(as_of=as_of, summaries=tuple(summaries))


def render_candidate_v2_impact_markdown(report: CandidateV2ImpactReport) -> str:
    """Render report to markdown."""
    lines: list[str] = [
        f"# Candidate v2 市场证据与技术信号影响审计报告 ({report.as_of.strftime('%Y-%m-%d')})",
        "",
        "## 一、各策略市场证据完整度与缺项分布",
        "",
        "| 主策略 | 合格标的数 (分母) | 5D证据完整数 | 缺行业数 | 缺基准数 | 缺量比数 | 5D完整率 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for s in report.summaries:
        ratio = (
            f"{s.complete_5d_evidence_count / s.qualified_count:.1%}"
            if s.qualified_count > 0
            else "0.0%"
        )
        lines.append(
            f"| `{s.strategy_id}` | {s.qualified_count} | {s.complete_5d_evidence_count} | "
            f"{s.missing_industry_count} | {s.missing_benchmark_count} | "
            f"{s.missing_volume_ratio_count} | {ratio} |"
        )

    lines.extend(
        [
            "",
            "## 二、候选群体风险与中性技术信号分布",
            "",
            "| 主策略 | 合格标的数 | BREAKDOWN (严重破位) | TREND_WEAKEN (中强短弱) | NO_SIGNAL (无特定特征) | 风险信号合计 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )

    for s in report.summaries:
        risk_total = s.breakdown_count + s.trend_weaken_count
        lines.append(
            f"| `{s.strategy_id}` | {s.qualified_count} | {s.breakdown_count} | "
            f"{s.trend_weaken_count} | {s.no_signal_count} | {risk_total} |"
        )

    lines.append("")
    return "\n".join(lines)
