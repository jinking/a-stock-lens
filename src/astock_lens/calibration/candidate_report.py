"""Candidate qualification calibration models and report generation."""

import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from astock_lens.domain.models import DomainRecord
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult

CALIBRATION_WARNING = "CALIBRATION ONLY — NOT APPROVED PRODUCT RULE"
CALIBRATION_PERCENTILES: tuple[float, ...] = (0.80, 0.85, 0.90, 0.95)
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
    percentile_boundary_90: float | None
    top_symbols: tuple[str, ...]
    boundary_above_symbols: tuple[str, ...]
    boundary_below_symbols: tuple[str, ...]
    industry_counts: tuple[tuple[str, int], ...]
    overlap_counts: tuple[tuple[str, int], ...]
    sensitivity_counts: tuple[tuple[float, int], ...] = ()
    score_quantiles: tuple[tuple[str, float], ...] = ()


class CandidateCalibrationReport(DomainRecord):
    """Complete cross-sectional calibration report across all strategies and factors."""

    as_of: datetime
    warning: str
    strategies: tuple[StrategyCalibration, ...]
    industry_coverage_ratio: float
    unknown_industry_count: int
    factor_anomalies: tuple[tuple[str, str], ...] = ()
    data_status_counts: tuple[tuple[str, int], ...] = ()


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
) -> CandidateCalibrationReport:
    """Generate a deterministic calibration evidence report.

    Raises ValueError if industry_map is empty.
    """
    if not industry_map:
        raise ValueError("industry_map cannot be empty")

    all_symbols = sorted(
        {r.symbol for r in strategy_results} | {f.symbol for f in factor_results}
    )
    known_symbols = [
        s for s in all_symbols if s in industry_map and industry_map[s].strip()
    ]
    unknown_industry_count = len(all_symbols) - len(known_symbols)
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

        boundary_above_symbols = tuple(r.symbol for r in top10_items[-5:])
        boundary_below_symbols = tuple(r.symbol for r in below_pool[:5])

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
                percentile_boundary_90=boundary_90,
                top_symbols=top_symbols,
                boundary_above_symbols=boundary_above_symbols,
                boundary_below_symbols=boundary_below_symbols,
                industry_counts=sorted_ind,
                overlap_counts=tuple(overlap_list),
                sensitivity_counts=tuple(sensitivities),
                score_quantiles=quantiles,
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
        factor_anomalies=tuple(anomalies),
        data_status_counts=sorted_status,
    )
