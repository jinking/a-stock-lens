"""Deterministic rendering for calibration evidence reports."""

import json
from collections.abc import Mapping

from astock_lens.calibration.candidate_report import CandidateCalibrationReport


def _show_quantile(quantiles: Mapping[str, float], label: str) -> str:
    """A quantile or `N/A` — never a zero standing in for "no observations"."""
    value = quantiles.get(label)
    return "N/A" if value is None else f"{value:.4f}"


def render_json(report: CandidateCalibrationReport) -> str:
    """Render the calibration report as pretty-printed deterministic JSON."""
    return json.dumps(
        report.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False
    )


def render_markdown(report: CandidateCalibrationReport) -> str:
    """Render the calibration report as deterministic GitHub-flavored Markdown."""
    lines: list[str] = [
        "# Candidate Qualification Calibration Report",
        "",
        f"> **WARNING: {report.warning}**",
        "",
        f"- **As of:** {report.as_of.isoformat()}",
        f"- **Industry Coverage:** {report.industry_coverage_ratio * 100:.2f}%",
        f"- **Unknown Industry Symbols:** {report.unknown_industry_count}",
        "",
        "## 1. Strategy Summary & Sensitivity",
        "",
        "| Strategy | Evaluable | Ranked | Boundary rank_percentile | Boundary score | Cutoff 0.80 | Cutoff 0.85 | Cutoff 0.90 | Cutoff 0.95 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for strat in report.strategies:
        sens_map = dict(strat.sensitivity_counts)
        boundary_str = (
            f"{strat.boundary_rank_percentile:.4f}"
            if strat.boundary_rank_percentile is not None
            else "N/A"
        )
        score_str = (
            f"{strat.boundary_strategy_score:.4f}"
            if strat.boundary_strategy_score is not None
            else "N/A"
        )
        lines.append(
            f"| {strat.strategy_id} | {strat.evaluable_count} | {strat.ranked_count} | "
            f"{boundary_str} | {score_str} | {sens_map.get(0.80, 0)} | "
            f"{sens_map.get(0.85, 0)} | {sens_map.get(0.90, 0)} | "
            f"{sens_map.get(0.95, 0)} |"
        )

    lines.extend(["", "## 2. Boundary Samples (0.90 Threshold)", ""])
    for strat in report.strategies:
        above_str = ", ".join(strat.boundary_above_symbols) or "None"
        below_str = ", ".join(strat.boundary_below_symbols) or "None"
        lines.append(f"### Strategy: `{strat.strategy_id}`")
        lines.append(f"- **Immediately Above 0.90:** {above_str}")
        lines.append(f"- **Immediately Below 0.90:** {below_str}")
        lines.append("")

    lines.extend(["## 3. Top 10% Industry Concentration", ""])
    for strat in report.strategies:
        lines.append(f"### Strategy: `{strat.strategy_id}`")
        if not strat.industry_counts:
            lines.append("No qualified items.")
        else:
            lines.append("| Industry | Count |")
            lines.append("| --- | --- |")
            for ind, count in strat.industry_counts:
                lines.append(f"| {ind} | {count} |")
        lines.append("")

    lines.extend(["## 4. Cross-Strategy Overlap (Top 10%)", ""])
    for strat in report.strategies:
        lines.append(f"### Strategy: `{strat.strategy_id}`")
        if not strat.overlap_counts:
            lines.append("No overlap data.")
        else:
            lines.append("| Other Strategy | Overlap Count |")
            lines.append("| --- | --- |")
            for other_id, count in strat.overlap_counts:
                lines.append(f"| {other_id} | {count} |")
        lines.append("")

    lines.extend(["## 5. Tracked Factor Outliers & Distributions", ""])
    lines.append("| Factor | Distribution Summary |")
    lines.append("| --- | --- |")
    for factor_name, summary in report.factor_anomalies:
        lines.append(f"| {factor_name} | {summary} |")

    lines.extend(["", "## 6. Factor DataStatus Counts", ""])
    lines.append("| Status | Count |")
    lines.append("| --- | --- |")
    for status_val, count in report.data_status_counts:
        lines.append(f"| {status_val} | {count} |")

    lines.extend(["", "## 7. Factor Distributions (VALUE observations only)", ""])
    lines.append(
        "| Factor | Values | NULL | STALE | SOURCE_ERROR | min | p10 | p25 | p50 | p75 | p90 | p95 | max |"
    )
    lines.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    for dist in report.factor_distributions:
        quantiles = dict(dist.quantiles)

        lines.append(
            f"| {dist.factor} | {dist.value_count} | {dist.null_count} | "
            f"{dist.stale_count} | {dist.source_error_count} | "
            f"{'N/A' if dist.min_value is None else f'{dist.min_value:.4f}'} | "
            f"{_show_quantile(quantiles, 'p10')} | "
            f"{_show_quantile(quantiles, 'p25')} | "
            f"{_show_quantile(quantiles, 'p50')} | "
            f"{_show_quantile(quantiles, 'p75')} | "
            f"{_show_quantile(quantiles, 'p90')} | "
            f"{_show_quantile(quantiles, 'p95')} | "
            f"{'N/A' if dist.max_value is None else f'{dist.max_value:.4f}'} |"
        )

    if report.population is not None:
        population = report.population
        lines.extend(["", "## 8. Calibration Population", ""])
        lines.append(f"- **Broad listing:** {population.broad_listing_count}")
        lines.append(f"- **Listing prefilter:** {population.prefilter_count}")
        lines.append(f"- **Research Universe:** {population.research_count}")
        lines.append(f"- **Research / listing ratio:** {population.research_ratio:.4f}")
        lines.append(
            f"- **Universe config digest:** {population.universe_config_digest}"
        )
        lines.append(
            f"- **Approved threshold in force:** "
            f"min_average_turnover_20d={population.min_average_turnover_20d}, "
            f"min_listing_days={population.min_listing_days}"
        )
        for factor, version in population.factor_versions:
            lines.append(f"- **Factor version:** {factor}={version}")
        for strategy, version in population.strategy_versions:
            lines.append(f"- **Strategy version:** {strategy}={version}")

    lines.extend(["", "## 9. Boundary Samples (evidence per symbol)", ""])
    for strat in report.strategies:
        lines.append(f"### Strategy: `{strat.strategy_id}`")
        if not strat.samples:
            lines.append("No ranked samples.")
            lines.append("")
            continue
        lines.append("| Symbol | Score | Rank percentile | Factor | Value | Status |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for sample in strat.samples:
            if not sample.factor_values:
                lines.append(
                    f"| {sample.symbol} | "
                    f"{'N/A' if sample.score is None else f'{sample.score:.4f}'} | "
                    f"{sample.rank_percentile:.4f} | (no factor snapshot) | | |"
                )
                continue
            for factor, value, status in sample.factor_values:
                lines.append(
                    f"| {sample.symbol} | "
                    f"{'N/A' if sample.score is None else f'{sample.score:.4f}'} | "
                    f"{sample.rank_percentile:.4f} | {factor} | "
                    f"{'N/A' if value is None else f'{value:.4f}'} | {status} |"
                )
        lines.append("")

    lines.append("")
    return "\n".join(lines)
