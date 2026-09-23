"""校准与影响审计命令。"""

import json
from pathlib import Path
from typing import Annotated

import typer

from astock_lens.calibration.candidate_report import (
    IndustryEvidence,
    generate_calibration_report,
)
from astock_lens.calibration.factor_distribution import CalibrationPopulation
from astock_lens.calibration.market_signal_readiness import (
    build_market_signal_readiness,
    compute_strategy_qualifications,
    render_readiness_json,
    render_readiness_markdown,
)
from astock_lens.calibration.qualification_impact import (
    build_qualification_impact,
    render_impact_json,
    render_impact_markdown,
)
from astock_lens.calibration.render import render_json, render_markdown
from astock_lens.data.industry import (
    build_industry_map,
    load_supplemental_industry_memberships,
)
from astock_lens.data.sync import INDUSTRY_ROOT, read_industry_memberships
from astock_lens.domain.enums import SnapshotKind
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines import stages
from astock_lens.pipelines.analysis import run_research_analysis
from astock_lens.qualifications import load_canonical_qualifiers
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config

from .runtime import (
    _as_of,
    _csv_root,
    _dataset,
    _declared_mapping_as_of,
    _factor_configs,
    _file_sha256,
    _load_industry_map,
    _securities_dataset,
    _snapshot_records,
    _strategy_dir,
    _universe_config_path,
)


def calibrate_candidates(
    as_of: Annotated[
        str,
        typer.Option(
            "--as-of",
            help="Trade date, YYYY-MM-DD.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Directory where calibration reports will be written.",
        ),
    ],
    industry_map: Annotated[
        Path | None,
        typer.Option(
            "--industry-map",
            help=(
                "显式指定 symbol,industry 的 CSV；不给就自动加载 canonical 行业映射"
                "（astock sync-industry 落地的结果）。给出时报告按“外部映射证据”呈现。"
            ),
        ),
    ] = None,
    industry_map_as_of: Annotated[
        str | None,
        typer.Option(
            "--industry-map-as-of",
            help=(
                "外部映射自己的时点（带时区 ISO 时间，如 2026-09-17T15:00:00+08:00）。"
                "只描述 --industry-map；不给就记为未知，绝不用文件 mtime 顶替。"
            ),
        ),
    ] = None,
) -> None:
    """Generate cross-sectional candidate calibration report without mutating state."""
    if industry_map_as_of is not None and industry_map is None:
        raise typer.BadParameter(
            "--industry-map-as-of describes a --industry-map file; pass "
            "--industry-map too, or drop the date (the canonical mapping dates "
            "itself from the membership records it was built from)"
        )
    declared_as_of = _declared_mapping_as_of(industry_map_as_of)

    day = _as_of(as_of)
    factor_configs = _factor_configs()
    universe_config = load_universe_config(_universe_config_path())
    scanners = load_scanners(_strategy_dir())
    population_state, analysis = run_research_analysis(
        csv_root=_csv_root(),
        as_of=day,
        universe_config=universe_config,
        factor_configs=factor_configs,
        scanners=scanners,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )

    # 本阶段所有校准报告都是诊断材料；来源与日期必须如实标注，不许含混。
    evidence = IndustryEvidence(origin="unspecified", diagnostic_only=True)
    if industry_map is not None:
        mapping = _load_industry_map(industry_map)
        requires_full_coverage = False
        evidence = IndustryEvidence(
            origin="external",
            source_ref=str(industry_map),
            source_sha256=_file_sha256(industry_map),
            mapping_as_of=declared_as_of,
            diagnostic_only=True,
        )
    else:
        canonical_path = _csv_root() / INDUSTRY_ROOT / f"{day.date().isoformat()}.csv"
        canonical = read_industry_memberships(canonical_path)
        if not canonical:
            typer.echo(
                "no canonical industry mapping for this date: run "
                "`astock sync-industry --as-of "
                f"{day.date().isoformat()}` or pass --industry-map for "
                "externally mapped evidence",
                err=True,
            )
            raise typer.Exit(code=1)
        supplements = load_supplemental_industry_memberships(as_of=day)
        all_canonical = (*canonical, *supplements)
        mapping = build_industry_map(all_canonical, as_of=day)
        requires_full_coverage = True
        # 日期取**可见**成员自己声明的取数时点：晚于分析时点的记录已经被
        # `build_industry_map` 过滤掉，所以这里不可能把一个未来日期当成历史口径。
        visible_dates = [
            membership.as_of for membership in all_canonical if membership.as_of <= day
        ]
        evidence = IndustryEvidence(
            origin="canonical",
            source_ref=str(canonical_path),
            source_sha256=_file_sha256(canonical_path),
            mapping_as_of=max(visible_dates, default=None),
            diagnostic_only=True,
        )

    report = generate_calibration_report(
        strategy_results=analysis.strategy_results,
        factor_results=analysis.factor_results,
        industry_map=mapping,
        as_of=analysis.as_of,
        industry_evidence=evidence,
        population=CalibrationPopulation(
            broad_listing_count=len(analysis.outcome.securities),
            prefilter_count=len(population_state.listing_prefilter_symbols),
            research_count=len(population_state.research_symbols),
            research_ratio=round(
                len(population_state.research_symbols)
                / len(analysis.outcome.securities),
                4,
            )
            if analysis.outcome.securities
            else 0.0,
            universe_config_digest=universe_config.digest()[:12],
            min_average_turnover_20d=universe_config.min_average_turnover_20d,
            min_listing_days=universe_config.min_listing_days,
            factor_versions=tuple(
                (config.name, config.version) for config in factor_configs
            ),
            strategy_versions=tuple(
                (scanner.config.id, scanner.config.version) for scanner in scanners
            ),
        ),
        require_full_industry_coverage=requires_full_coverage,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = analysis.as_of.strftime("%Y-%m-%d")
    json_path = output_dir / f"{date_str}-candidate-calibration.json"
    md_path = output_dir / f"{date_str}-candidate-calibration.md"

    json_path.write_text(render_json(report), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    typer.echo("Calibration report written:")
    typer.echo(f"  {json_path}")
    typer.echo(f"  {md_path}")


def calibrate_qualification_impact(
    as_of: Annotated[
        str,
        typer.Option(
            "--as-of",
            help="Trade date, YYYY-MM-DD.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Directory where the qualification impact audit will be written.",
        ),
    ],
) -> None:
    """Audit the six production qualification rules against stored snapshots.

    This command is strictly read-only:

    - reads the stored FACTOR and STRATEGY snapshots;
    - loads the strict canonical qualifiers;
    - never calls a provider, never recomputes factors/strategies, and never
      writes a Snapshot / Watchlist / Job / Candidate record.

    It writes only ``qualification-impact-YYYY-MM-DD.json`` and
    ``qualification-impact-YYYY-MM-DD.md`` under ``--output-dir``. A missing
    snapshot fails loudly instead of producing an empty report.
    """
    day = _as_of(as_of)
    factor_results = _snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
    strategy_results = _snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)

    if not factor_results:
        typer.echo(
            f"no FACTOR snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)
    if not strategy_results:
        typer.echo(
            f"no STRATEGY snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)

    factor_names = frozenset(config.name for config in _factor_configs())
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    report = build_qualification_impact(
        factor_results=factor_results,
        strategy_results=strategy_results,
        qualifiers=qualifiers,
        as_of=day,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = day.strftime("%Y-%m-%d")
    json_path = output_dir / f"qualification-impact-{date_str}.json"
    md_path = output_dir / f"qualification-impact-{date_str}.md"

    json_path.write_text(render_impact_json(report), encoding="utf-8")
    md_path.write_text(render_impact_markdown(report), encoding="utf-8")

    typer.echo("Qualification impact audit written:")
    typer.echo(f"  {json_path}")
    typer.echo(f"  {md_path}")


def calibrate_market_signal_readiness(
    as_of: Annotated[
        str,
        typer.Option(
            "--as-of",
            help="Trade date, YYYY-MM-DD.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Directory where the market signal readiness report will be written.",
        ),
    ],
) -> None:
    """Audit market regime and signal readiness against stored snapshots.

    Strictly read-only:
    - reads stored FACTOR and STRATEGY snapshots;
    - evaluates dual qualification using canonical approved qualifiers;
    - calculates technical metric distributions for qualified stocks;
    - writes market-signal-readiness-YYYY-MM-DD.json and .md under output_dir.
    """
    day = _as_of(as_of)
    factor_results = _snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
    strategy_results = _snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)

    if not factor_results:
        typer.echo(
            f"no FACTOR snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)
    if not strategy_results:
        typer.echo(
            f"no STRATEGY snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)

    factor_names = frozenset(config.name for config in _factor_configs())
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    qualifications = compute_strategy_qualifications(
        strategy_results=strategy_results,
        factor_results=factor_results,
        qualifiers=qualifiers,
    )

    report = build_market_signal_readiness(
        as_of=day,
        qualifications=qualifications,
        factor_results=factor_results,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = day.strftime("%Y-%m-%d")
    json_path = output_dir / f"market-signal-readiness-{date_str}.json"
    md_path = output_dir / f"market-signal-readiness-{date_str}.md"

    json_path.write_text(render_readiness_json(report), encoding="utf-8")
    md_path.write_text(render_readiness_markdown(report), encoding="utf-8")

    typer.echo("Market & signal readiness report written:")
    typer.echo(f"  {json_path}")
    typer.echo(f"  {md_path}")


def calibrate_candidate_v2_impact_cmd(
    as_of: Annotated[
        str,
        typer.Option(
            "--as-of",
            help="Trade date, YYYY-MM-DD.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Directory where the candidate v2 impact audit report will be written.",
        ),
    ],
) -> None:
    """Audit Candidate v2 5D market evidence and signal impact on qualified candidates.

    Strictly read-only:
    - reads stored FACTOR and STRATEGY snapshots;
    - reads normalized bars and industry landing files if present;
    - audits 5D evidence availability and signal breakdown distributions;
    - writes candidate-v2-impact-YYYY-MM-DD.json and .md under output_dir.
    """
    from astock_lens.calibration.candidate_v2_impact import (
        compute_candidate_v2_impact,
        render_candidate_v2_impact_markdown,
    )

    day = _as_of(as_of)
    factor_results = _snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
    strategy_results = _snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)

    if not factor_results:
        typer.echo(
            f"no FACTOR snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)
    if not strategy_results:
        typer.echo(
            f"no STRATEGY snapshot for {day.date().isoformat()}: run "
            "`astock daily` to produce it first",
            err=True,
        )
        raise typer.Exit(code=1)

    factor_names = frozenset(config.name for config in _factor_configs())
    qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)

    qualifications = compute_strategy_qualifications(
        strategy_results=strategy_results,
        factor_results=factor_results,
        qualifiers=qualifiers,
    )

    outcome = stages.normalize_stage(
        csv_root=_csv_root(),
        as_of=day,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )
    bars = outcome.bars.daily_bars

    industry_file = _csv_root() / "industry" / f"{day.date().isoformat()}.csv"
    mapped_symbols: set[str] = set()
    if industry_file.is_file():
        from astock_lens.data.sync import read_industry_memberships

        try:
            memberships = read_industry_memberships(industry_file)
            mapped_symbols = {m.symbol for m in memberships}
        except (OSError, ValueError):
            mapped_symbols = set()

    benchmark_available = False

    report = compute_candidate_v2_impact(
        qualifications=qualifications,
        factors=factor_results,
        bars=bars,
        industry_mapped_symbols=mapped_symbols,
        benchmark_available=benchmark_available,
        as_of=day,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = day.strftime("%Y-%m-%d")
    json_path = output_dir / f"candidate-v2-impact-{date_str}.json"
    md_path = output_dir / f"candidate-v2-impact-{date_str}.md"

    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(
        render_candidate_v2_impact_markdown(report),
        encoding="utf-8",
    )

    typer.echo("Candidate v2 impact audit report written:")
    typer.echo(f"  {json_path}")
    typer.echo(f"  {md_path}")


def register(calibrate_app: typer.Typer) -> None:
    calibrate_app.command("candidates")(calibrate_candidates)
    calibrate_app.command("qualification-impact")(calibrate_qualification_impact)
    calibrate_app.command("market-signal-readiness")(calibrate_market_signal_readiness)
    calibrate_app.command("candidate-v2-impact")(calibrate_candidate_v2_impact_cmd)
