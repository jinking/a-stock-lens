"""Deterministic rendering for calibration evidence reports."""

import json

from astock_lens.calibration.candidate_report import CandidateCalibrationReport


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
        "| Strategy | Evaluable | Ranked | Top 10% Boundary | Cutoff 0.80 | Cutoff 0.85 | Cutoff 0.90 | Cutoff 0.95 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for strat in report.strategies:
        sens_map = dict(strat.sensitivity_counts)
        boundary_str = (
            f"{strat.percentile_boundary_90:.4f}"
            if strat.percentile_boundary_90 is not None
            else "N/A"
        )
        lines.append(
            f"| {strat.strategy_id} | {strat.evaluable_count} | {strat.ranked_count} | "
            f"{boundary_str} | {sens_map.get(0.80, 0)} | {sens_map.get(0.85, 0)} | "
            f"{sens_map.get(0.90, 0)} | {sens_map.get(0.95, 0)} |"
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

    lines.append("")
    return "\n".join(lines)
