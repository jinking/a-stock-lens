"""Candidate qualification calibration models and report generation."""

import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal

from pydantic import Field

from astock_lens.calibration.factor_distribution import (
    BoundarySample,
    CalibrationPopulation,
    FactorDistribution,
    boundary_samples,
    factor_distributions,
)
from astock_lens.domain.models import DomainRecord
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult

CALIBRATION_WARNING = "CALIBRATION ONLY — NOT APPROVED PRODUCT RULE"
CALIBRATION_PERCENTILES: tuple[float, ...] = (0.80, 0.85, 0.90, 0.95)


class IndustryCoverageUnavailable(RuntimeError):
    """决策级报告缺少行业覆盖：少一整项证据就不该被当成可批复的材料。"""


class IndustryEvidence(DomainRecord):
    """行业映射这份证据是谁给的、哪一天的、能不能当正式口径用。

    这张映射有一半是"事实"，另一半是"判断"，字段必须把两者分开：

    * `origin` 说清这份映射是仓库规范链路（`canonical`）产出的，还是外部文件
      （`external`），还是压根没声明（`unspecified`）。外部映射**永远不会**被
      改写成 `canonical`——那等于用一次便利输入替换掉正式证据。
    * `mapping_as_of` 是映射自己的时点。不知道就留 `None`。**不用文件 mtime
      顶替，也不把分析时点写上去**：前者是文件系统的噪声，后者是把别人的日期
      说成自己的。
    * `source_sha256` 让"用的是哪一份文件"可复算；`source_ref` 是它的名字。
    * `diagnostic_only` 本阶段恒为 `True`。这张映射只用于诊断，不构成已批准
      的产品规则。
    """

    origin: Literal["canonical", "external", "unspecified"] = "unspecified"
    source_ref: str | None = None
    source_sha256: str | None = None
    mapping_as_of: datetime | None = None
    diagnostic_only: bool = True


class IndustryCoverage(DomainRecord):
    """参与计算的标的里有多少只有行业归属，缺的到底是哪些代码。

    缺口用**集合差**算出来（参与计算标的 − 有行业归属标的），不靠计数反推：
    一份只有数字没有代码的缺口报告，读者无法核对也无法据此补数据。
    """

    missing_symbols: tuple[str, ...]
    known_count: int
    total_count: int
    ratio: float


TRACKED_ANOMALY_FACTORS: tuple[str, ...] = (
    "net_profit_parent_yoy",
    "dividend_payout_ttm",
    "peg",
)


class StrategyCalibration(DomainRecord):
    """Distribution statistics and samples for a single strategy."""

    strategy_id: str
    evaluable_count: int
    ranked_count: int
    # 0.90 线是两个不同的量，曾经被一个字段名混在一起：线本身的**分位值**，
    # 与恰好站在线内最后一个标的的**策略分数**。它们必须分开报。
    boundary_rank_percentile: float | None
    boundary_strategy_score: float | None
    top_symbols: tuple[str, ...]
    boundary_above_symbols: tuple[str, ...]
    boundary_below_symbols: tuple[str, ...]
    industry_counts: tuple[tuple[str, int], ...]
    overlap_counts: tuple[tuple[str, int], ...]
    sensitivity_counts: tuple[tuple[float, int], ...] = ()
    score_quantiles: tuple[tuple[str, float], ...] = ()
    samples: tuple[BoundarySample, ...] = ()


class CandidateCalibrationReport(DomainRecord):
    """Complete cross-sectional calibration report across all strategies and factors."""

    as_of: datetime
    warning: str
    strategies: tuple[StrategyCalibration, ...]
    industry_coverage_ratio: float
    unknown_industry_count: int
    # 缺口同时以三种形态存在，它们必须说的是同一件事：标量计数供人读，代码列表
    # 供人核，结构化的 `IndustryCoverage` 供机器消费。测试里有一条专门盯住三者
    # 不许漂移。
    unknown_industry_symbols: tuple[str, ...] = ()
    industry_coverage: IndustryCoverage | None = None
    industry_evidence: IndustryEvidence = Field(default_factory=IndustryEvidence)
    factor_anomalies: tuple[tuple[str, str], ...] = ()
    data_status_counts: tuple[tuple[str, int], ...] = ()
    factor_distributions: tuple[FactorDistribution, ...] = ()
    population: CalibrationPopulation | None = None


def _compute_quantiles(scores: list[float]) -> tuple[tuple[str, float], ...]:
    if not scores:
        return ()
    sorted_scores = sorted(scores)
    n = len(sorted_scores)
    return (
        ("min", sorted_scores[0]),
        ("p25", sorted_scores[int(n * 0.25)]),
        ("median", sorted_scores[int(n * 0.50)]),
        ("p75", sorted_scores[int(n * 0.75)]),
        ("max", sorted_scores[-1]),
    )


def generate_calibration_report(
    *,
    as_of: datetime,
    strategy_results: Sequence[StrategyResult],
    factor_results: Sequence[FactorResult],
    industry_map: Mapping[str, str],
    population: CalibrationPopulation | None = None,
    industry_evidence: IndustryEvidence | None = None,
    require_full_industry_coverage: bool = False,
) -> CandidateCalibrationReport:
    """Generate a deterministic calibration evidence report.

    Raises ValueError if industry_map is empty, and `IndustryCoverageUnavailable`
    when full coverage is required but some symbols have no industry: a report
    missing the industry evidence must not read as a decision-grade one.

    `industry_evidence` describes the mapping itself and is recorded verbatim;
    it never takes part in the computation. `require_full_industry_coverage`
    is the *only* branch that refuses on a gap — external mappings are allowed
    to be incomplete and must still produce a diagnostic that names the gap.
    """
    if not industry_map:
        raise ValueError("industry_map cannot be empty")

    all_symbols = sorted(
        {r.symbol for r in strategy_results} | {f.symbol for f in factor_results}
    )
    known_symbols = [
        s for s in all_symbols if s in industry_map and industry_map[s].strip()
    ]
    # 缺口是集合差，不是 "总数减已知数"：后者在重复代码或去重失误时会给出一个
    # 自洽但错误的数字，而集合差只会如实列出真正缺的那些代码。
    missing_symbols = tuple(sorted(set(all_symbols) - set(known_symbols)))
    unknown_industry_count = len(missing_symbols)
    if require_full_industry_coverage and unknown_industry_count:
        raise IndustryCoverageUnavailable(
            "decision-grade calibration requires canonical industry coverage for "
            f"every symbol, but {unknown_industry_count} of {len(all_symbols)} "
            "have no industry membership; run `astock sync-industry` or pass an "
            "explicit --industry-map and label the report as externally mapped"
        )
    industry_coverage_ratio = (
        len(known_symbols) / len(all_symbols) if all_symbols else 0.0
    )

    # Group strategy results by strategy_id
    by_strat: dict[str, list[StrategyResult]] = {}
    for r in strategy_results:
        by_strat.setdefault(r.strategy_id, []).append(r)

    # Precompute top 10% sets for overlap calculation
    top10_by_strat: dict[str, set[str]] = {}
    for sid, res_list in by_strat.items():
        top10_by_strat[sid] = {
            r.symbol
            for r in res_list
            if r.eligible
            and r.rank_percentile is not None
            and r.rank_percentile >= 0.90
        }

    strategy_calibrations: list[StrategyCalibration] = []
    for sid in sorted(by_strat.keys()):
        res_list = by_strat[sid]
        evaluable = [r for r in res_list if r.eligible]
        ranked = [
            r
            for r in evaluable
            if r.rank_percentile is not None and r.score is not None
        ]

        def _rank_key(r: StrategyResult) -> tuple[float, float, str]:
            pct = r.rank_percentile if r.rank_percentile is not None else 0.0
            sc = r.score if r.score is not None else 0.0
            return (-pct, -sc, r.symbol)

        # Sort ranked by rank_percentile DESC, score DESC, symbol ASC
        ranked.sort(key=_rank_key)

        scores = [r.score for r in ranked if r.score is not None]
        quantiles = _compute_quantiles(scores)

        top10_items = [
            r
            for r in ranked
            if r.rank_percentile is not None and r.rank_percentile >= 0.90
        ]
        top_symbols = tuple(r.symbol for r in top10_items[:5])

        # Boundary items
        below_pool = [r for r in ranked if r.rank_percentile < 0.90]  # type: ignore[operator]
        boundary_90 = top10_items[-1].rank_percentile if top10_items else None
        boundary_score = top10_items[-1].score if top10_items else None

        boundary_above_symbols = tuple(r.symbol for r in top10_items[-5:])
        boundary_below_symbols = tuple(r.symbol for r in below_pool[:5])
        samples = boundary_samples(res_list, strategy_id=sid)

        # Industry distribution among Top 10%
        ind_counts = Counter(
            industry_map.get(r.symbol, "未知行业") for r in top10_items
        )
        sorted_ind = tuple(
            sorted(ind_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        )

        # Overlap with other strategies
        my_top10_symbols = top10_by_strat.get(sid, set())
        overlap_list: list[tuple[str, int]] = []
        for other_sid in sorted(by_strat.keys()):
            if other_sid == sid:
                continue
            common = len(my_top10_symbols & top10_by_strat.get(other_sid, set()))
            overlap_list.append((other_sid, common))
        overlap_list.sort(key=lambda pair: (-pair[1], pair[0]))

        # Sensitivity counts
        sensitivities: list[tuple[float, int]] = []
        for cutoff in CALIBRATION_PERCENTILES:
            count = len(
                [
                    r
                    for r in ranked
                    if r.rank_percentile is not None and r.rank_percentile >= cutoff
                ]
            )
            sensitivities.append((cutoff, count))

        strategy_calibrations.append(
            StrategyCalibration(
                strategy_id=sid,
                evaluable_count=len(evaluable),
                ranked_count=len(ranked),
                boundary_rank_percentile=boundary_90,
                boundary_strategy_score=boundary_score,
                top_symbols=top_symbols,
                boundary_above_symbols=boundary_above_symbols,
                boundary_below_symbols=boundary_below_symbols,
                industry_counts=sorted_ind,
                overlap_counts=tuple(overlap_list),
                sensitivity_counts=tuple(sensitivities),
                score_quantiles=quantiles,
                samples=samples,
            )
        )

    # Factor anomalies
    anomalies: list[tuple[str, str]] = []
    for factor_name in TRACKED_ANOMALY_FACTORS:
        matching = [
            f.raw_value
            for f in factor_results
            if f.factor == factor_name and f.raw_value is not None
        ]
        if not matching:
            anomalies.append((factor_name, "not available in this calibration input"))
        else:
            anomalies.append(
                (
                    factor_name,
                    (
                        f"count={len(matching)}, min={min(matching):.2f}, "
                        f"median={statistics.median(matching):.2f}, max={max(matching):.2f}"
                    ),
                )
            )

    # DataStatus counts
    status_counter = Counter(f.status.value for f in factor_results)
    sorted_status = tuple(
        sorted(status_counter.items(), key=lambda pair: (-pair[1], pair[0]))
    )

    return CandidateCalibrationReport(
        as_of=as_of,
        warning=CALIBRATION_WARNING,
        strategies=tuple(strategy_calibrations),
        industry_coverage_ratio=round(industry_coverage_ratio, 4),
        unknown_industry_count=unknown_industry_count,
        unknown_industry_symbols=missing_symbols,
        industry_coverage=IndustryCoverage(
            missing_symbols=missing_symbols,
            known_count=len(known_symbols),
            total_count=len(all_symbols),
            ratio=round(industry_coverage_ratio, 4),
        ),
        industry_evidence=(
            industry_evidence if industry_evidence is not None else IndustryEvidence()
        ),
        factor_anomalies=tuple(anomalies),
        data_status_counts=sorted_status,
        factor_distributions=factor_distributions(factor_results),
        population=population,
    )
