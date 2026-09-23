"""数据同步、健康检查与外部数据命令。"""

import csv
import json
import platform
import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from astock_lens.calendar.china import get_calendar
from astock_lens.calibration.dividend_coverage import (
    audit_dividend_coverage,
    render_dividend_coverage_json,
    render_dividend_coverage_markdown,
)
from astock_lens.calibration.valuation_coverage import valuation_coverage
from astock_lens.data.bootstrap import (
    bootstrap_liquidity_history,
    bootstrap_strategy_history,
    liquidity_bootstrap_requirement,
    strategy_history_requirement,
)
from astock_lens.data.contracts import FetchRequest
from astock_lens.data.health import raw_datasets
from astock_lens.data.industry import (
    WestockSectorSource,
    build_industry_map,
    load_supplemental_industry_memberships,
)
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.providers.neodata import NeodataProvider
from astock_lens.data.providers.westock import FINANCIAL_DATASETS, WestockCliProvider
from astock_lens.data.storage.paths import resolve_storage_paths
from astock_lens.data.sync import (
    DONE_STATUSES,
    INDUSTRY_ROOT,
    DatasetLanding,
    land_financial_statements,
    land_industry_memberships,
    land_neodata_blocks,
    land_raw,
    land_securities_listing,
    read_industry_memberships,
    read_raw_rows,
    read_universe_symbols,
)
from astock_lens.pipelines import stages
from astock_lens.pipelines.analysis import compute_research_universe
from astock_lens.settings import load_app_config
from astock_lens.strategies.config import load_strategy_config
from astock_lens.universe.config import load_universe_config
from astock_lens.universe.prefilter import prefilter_listing

from .runtime import (
    AS_OF_OPTION,
    MINIMUM_PYTHON,
    STRATEGY_CONFIG_PATH,
    _as_of,
    _benchmark_subset,
    _bulk_provider,
    _configured_config_path,
    _covered_dividend_symbols,
    _covered_valuation_symbols,
    _csv_root,
    _dataset,
    _factor_configs,
    _financial_provider,
    _HeartbeatSink,
    _land_financials,
    _land_valuation,
    _load_dividend_events,
    _neodata_provider,
    _securities_dataset,
    _symbol_bar_provider,
    _today_close,
    _universe_config_path,
    _valuation_strategy_configs,
)


def doctor() -> None:
    """Check local configuration and runtime health.

    This command only reads local files. It never fetches market data, never
    contacts a provider, and never creates the DuckDB file.
    """
    failures: list[str] = []

    current = sys.version_info
    python_ok = (current.major, current.minor) >= MINIMUM_PYTHON
    typer.echo(
        f"Python {platform.python_version()} [{'ok' if python_ok else 'unsupported'}]"
    )
    if not python_ok:
        failures.append(
            f"Python >= 3.12 is required, found {platform.python_version()}"
        )

    config_path = _configured_config_path()
    try:
        config = load_app_config(config_path)
        paths = resolve_storage_paths(config_path=config_path)
    except (OSError, ValueError, ValidationError) as error:
        typer.echo(f"config {config_path} [failed]", err=True)
        typer.echo(f"  {error}", err=True)
        failures.append(f"configuration could not be loaded from {config_path}")
    else:
        typer.echo(f"config {config_path} [ok]")
        typer.echo(f"app.name: {config.app.name}")
        # Missing paths are reported, not created: bootstrap must not write.
        # 来源（env / config / default）与路径一起打印：一个"生效了但没人知道
        # 它从哪来"的路径，等于没有生效。
        for label, path in (
            ("storage.database", paths.database),
            ("storage.normalized_root", paths.normalized_root),
            ("storage.snapshot_root", paths.snapshot_root),
            ("storage.watchlist_root", paths.watchlist_root),
            ("storage.job_root", paths.job_root),
        ):
            presence = "present" if path.exists() else "absent"
            origin = paths.sources[label.removeprefix("storage.")]
            typer.echo(f"{label}: {path} [{presence}] ({origin})")

    try:
        configured = _factor_configs()
    except (OSError, ValueError, ValidationError) as error:
        typer.echo("factor configs [failed]", err=True)
        typer.echo(f"  {error}", err=True)
        failures.append("factor configuration could not be loaded")
    else:
        typer.echo(f"factors: {', '.join(config.name for config in configured)}")

    strategy_path = STRATEGY_CONFIG_PATH
    try:
        strategy = load_strategy_config(strategy_path)
    except (OSError, ValueError, ValidationError) as error:
        typer.echo(f"strategy {strategy_path} [failed]", err=True)
        typer.echo(f"  {error}", err=True)
        failures.append(
            f"strategy configuration could not be loaded from {strategy_path}"
        )
    else:
        weights = (
            "none reviewed, a scan will not rank"
            if not strategy.weights
            else ", ".join(
                f"{name}={value}" for name, value in strategy.weights.items()
            )
        )
        typer.echo(f"strategy {strategy.id} {strategy.version} [ok]")
        typer.echo(f"  weights: {weights}")

    # Data Health (`docs/DATA_SOURCES.md` §4): what a scan would read, and how
    # fresh it is. This reads local files only — it never fetches, so it cannot
    # turn a health check into a data-pipeline run.
    csv_root = _csv_root()
    presence = "ok" if csv_root.is_dir() else "missing"
    typer.echo(f"provider local-csv: {csv_root} [{presence}]")
    datasets = raw_datasets(csv_root)
    if not datasets:
        typer.echo("  datasets: none landed under this root")
    for freshness in datasets:
        span = (
            f"{freshness.first_trade_date} .. {freshness.last_trade_date}"
            if freshness.covers_dates
            else "no trade_date column"
        )
        unreadable = (
            f", {freshness.unreadable_trade_dates} unreadable trade dates"
            if freshness.unreadable_trade_dates
            else ""
        )
        typer.echo(f"  {freshness.dataset}: {freshness.rows} rows, {span}{unreadable}")

    provider_health = _bulk_provider().health()
    provider_state = "ok" if provider_health.healthy else "unavailable"
    detail = f" ({provider_health.message})" if provider_health.message else ""
    typer.echo(f"provider {provider_health.provider} [{provider_state}]{detail}")

    # The financial-statement source (design spec §24). Reported without being
    # run: `doctor` stays read-only, and liveness is only proven by a fetch.
    westock_health = WestockCliProvider().health()
    westock_state = "ok" if westock_health.healthy else "unavailable"
    westock_detail = f" ({westock_health.message})" if westock_health.message else ""
    typer.echo(f"provider {westock_health.provider} [{westock_state}]{westock_detail}")

    # 语义数据源（规格 §24 补遗，2026-09-17 修订）：估值、行业与语义维度的主数据源，
    # 同时是财报的交叉验证源。凭证 12 小时过期且只能由平台刷新，因此状态必须一眼可见。
    neodata_health = NeodataProvider().health()
    neodata_state = "ok" if neodata_health.healthy else "unavailable"
    neodata_detail = f" ({neodata_health.message})" if neodata_health.message else ""
    typer.echo(f"provider {neodata_health.provider} [{neodata_state}]{neodata_detail}")

    if failures:
        typer.echo("doctor found problems:", err=True)
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)


def calendar_is_open(
    date: Annotated[
        str,
        typer.Option(
            "--date",
            help="Target date to inspect, formatted as YYYY-MM-DD.",
        ),
    ],
) -> None:
    """Check if a date is an active A-Share trading day."""
    day = _as_of(date)
    cal = get_calendar()
    is_open = cal.is_trade_date(day.date())
    if is_open:
        typer.echo(f"{day.date().isoformat()} is OPEN (trading day)")
    else:
        typer.echo(
            f"{day.date().isoformat()} is CLOSED (non-trading day / weekend / holiday)"
        )


def calendar_latest(
    date: Annotated[
        str,
        typer.Option(
            "--date",
            help="Reference date, formatted as YYYY-MM-DD.",
        ),
    ],
) -> None:
    """Find the latest effective trade date on or before the target date."""
    day = _as_of(date)
    cal = get_calendar()
    latest = cal.get_latest_trade_date(day.date())
    typer.echo(f"latest trade date: {latest.isoformat()}")


def sync_industry(as_of: Annotated[str, AS_OF_OPTION]) -> None:
    """Land the canonical industry catalog and its memberships.

    Catalog first, then one call per board: what lands is a per-fetch-day file
    whose every row says which board it came from and when it was asked for.
    The catalog is the authority — this never invents a board list.
    """
    day = _as_of(as_of)
    landing = land_industry_memberships(
        source=WestockSectorSource(), root=_csv_root(), as_of=day
    )
    typer.echo(f"industry {landing.status.value}: {landing.rows_written} memberships")
    typer.echo(f"written to {landing.path}")
    if landing.note is not None:
        typer.echo(f"note: {landing.note}", err=True)


def industry_export_map(
    as_of: Annotated[str, AS_OF_OPTION],
    output: Annotated[
        Path, typer.Option("--output", help="写出的 symbol,industry CSV 路径。")
    ],
) -> None:
    """Write the `symbol,industry` CSV the calibration command consumes.

    Only the named output file is written: Snapshot / Watchlist / Job state is
    untouched, so exporting a map can never change what the system believes.
    """
    day = _as_of(as_of)
    path = _csv_root() / INDUSTRY_ROOT / f"{day.date().isoformat()}.csv"
    memberships = read_industry_memberships(path)
    if not memberships:
        typer.echo(
            f"no landed industry memberships at {path}; run `astock sync-industry` "
            "first",
            err=True,
        )
        raise typer.Exit(code=1)

    supplements = load_supplemental_industry_memberships(as_of=day)
    mapping = build_industry_map((*memberships, *supplements), as_of=day)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("symbol", "industry"))
        for symbol in sorted(mapping):
            writer.writerow((symbol, mapping[symbol]))
    typer.echo(f"industry map: {len(mapping)} symbols written to {output}")


def valuation_coverage_command(
    as_of: Annotated[str, AS_OF_OPTION],
    universe: Annotated[
        Path,
        typer.Option(
            "--universe",
            help="研究池名单：JSON 的 research_symbols，或 CSV 的 symbol 列。",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="把完整报告写成 JSON；不写则只打印摘要。"),
    ] = None,
) -> None:
    """核对估值字段与策略估值侧因子在研究池上的覆盖（只读）。

    分母是 `--universe` 给出的研究池名单。缺名单直接报错：拿"已落地的标的"
    当分母会把覆盖率算成 100%，那正是这份报告要防的错觉。
    """
    day = _as_of(as_of)
    try:
        symbols = read_universe_symbols(universe)
    except (OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    inputs = stages.valuation_inputs(_csv_root(), as_of=day)
    try:
        report = valuation_coverage(
            inputs.observations,
            as_of=day,
            universe=symbols,
            strategy_configs=_valuation_strategy_configs(),
            factor_configs=_factor_configs(),
        )
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"as_of: {day.isoformat()}")
    typer.echo(
        f"source: {inputs.source_file if inputs.source_file else '未落地任何估值数据'}"
    )
    typer.echo(f"研究池: {report.universe_size} 只")
    typer.echo(
        f"有任意估值: {len(report.covered_symbols)} / {report.universe_size}"
        f"（缺口 {len(report.uncovered_symbols)} 只）"
    )
    for metric in report.metrics:
        typer.echo(
            f"  字段 {metric.metric}: {len(metric.symbols_with_value)} 只"
            f"（{metric.ratio:.4f}）"
        )
    for factor in report.factors:
        typer.echo(
            f"  因子 {factor.factor}: {len(factor.symbols_with_value)} 只"
            f"（{factor.ratio:.4f}）"
        )
    for strategy in report.strategies:
        if not strategy.valuation_factors:
            continue
        blocking = "、".join(
            f"{name} 缺 {count}" for name, count in strategy.blocking_factors
        )
        typer.echo(
            f"  策略 {strategy.strategy_id}: 估值侧可打分 {len(strategy.scoreable_symbols)}"
            f" / {report.universe_size}；缺口按因子：{blocking}"
        )

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report.to_payload(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"report: {output}")


def sync_valuation(
    as_of: Annotated[str, AS_OF_OPTION],
    universe: Annotated[
        Path,
        typer.Option(
            "--universe",
            help="研究池名单：JSON 的 research_symbols，或 CSV 的 symbol 列。",
        ),
    ],
    max_rounds: Annotated[
        int,
        typer.Option(
            "--max-rounds",
            help="最多补抓几轮；每轮只请求仍然缺的标的。技术上限，不是产品阈值。",
        ),
    ] = 2,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            help=(
                "一次请求最多带几只标的。实测源的响应被截到 1–2 个内容块，"
                "因此带多带少不改变每次回几块；默认 5（实测每次命中最高）。"
            ),
        ),
    ] = 5,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="只处理名单前 N 只，用于小规模探针。"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="把本轮清单写成 JSON（含剩余缺口）。"),
    ] = None,
) -> None:
    """按缺口批量补抓估值：多轮、可重跑、缺口显式。

    实测源端一批只回 1–2 只，因此补齐必须分多轮。三条纪律写在这里：

    - 每轮只请求"仍缺"的标的，已覆盖的不会重复问；
    - 落地按块身份合并，后一轮不会冲掉前一轮（见 `land_neodata_blocks`）；
    - 一轮没有带来任何新标的就停下，并把剩余缺口原样报出——缺口不是成功。
    """
    day = _as_of(as_of)
    if max_rounds <= 0:
        raise typer.BadParameter("--max-rounds 必须为正")
    if batch_size <= 0:
        raise typer.BadParameter("--batch-size 必须为正")
    if limit is not None and limit <= 0:
        raise typer.BadParameter("--limit 必须为正")

    try:
        wanted = read_universe_symbols(universe)
    except (OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    if limit is not None:
        wanted = wanted[:limit]

    provider = _neodata_provider(batch_size=batch_size)
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    typer.echo(f"研究池: {len(wanted)} 只（as_of {day.date().isoformat()}）")
    rounds: list[dict[str, object]] = []
    stopped = "max_rounds"
    for index in range(1, max_rounds + 1):
        covered = _covered_valuation_symbols(day)
        missing = tuple(symbol for symbol in wanted if symbol not in covered)
        if not missing:
            stopped = "covered"
            typer.echo(f"round {index}: 已全覆盖，无需请求")
            break

        landing = land_neodata_blocks(
            provider=provider,
            root=_csv_root(),
            dataset="valuation",
            values=missing,
            as_of=day,
        )
        after = _covered_valuation_symbols(day)
        landed = tuple(symbol for symbol in missing if symbol in after)
        still_missing = tuple(symbol for symbol in wanted if symbol not in after)
        rounds.append(
            {
                "round": index,
                "requested": len(missing),
                "landed": len(landed),
                "missing": len(still_missing),
                "status": landing.status.value,
                "note": landing.note,
            }
        )
        typer.echo(
            f"round {index}: 请求 {len(missing)} 只，落地 {len(landed)} 只，"
            f"仍缺 {len(still_missing)} 只（{landing.status.value}）"
        )
        if landing.note:
            typer.echo(f"  note: {landing.note}", err=True)
        if not landed:
            stopped = "no_progress"
            typer.echo("本轮没有带来任何新标的，停止继续请求", err=True)
            break
    else:
        stopped = "max_rounds"

    covered = _covered_valuation_symbols(day)
    missing_symbols = tuple(symbol for symbol in wanted if symbol not in covered)
    typer.echo(
        f"覆盖: {len(wanted) - len(missing_symbols)} / {len(wanted)}；"
        f"缺口 {len(missing_symbols)} 只；停止原因 {stopped}"
    )

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "dataset": "valuation",
                    "as_of": day.isoformat(),
                    "requested_symbols": list(wanted),
                    "covered_symbols": [
                        symbol
                        for symbol in wanted
                        if symbol not in set(missing_symbols)
                    ],
                    "missing_symbols": list(missing_symbols),
                    "stop_reason": stopped,
                    "rounds": rounds,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        typer.echo(f"report: {output}")

    if missing_symbols:
        raise typer.Exit(code=1)


def sync_dividends(
    as_of: Annotated[str, AS_OF_OPTION],
    universe: Annotated[
        Path,
        typer.Option(
            "--universe",
            help="研究池名单：JSON 的 research_symbols，或 CSV 的 symbol 列。",
        ),
    ],
    max_rounds: Annotated[
        int,
        typer.Option(
            "--max-rounds",
            help="最多补抓几轮；每轮只请求仍然缺的标的。技术上限，不是产品阈值。",
        ),
    ] = 2,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            help="一次请求最多带几只标的；默认 5。",
        ),
    ] = 5,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="只处理名单前 N 只，用于小规模探针。"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="把本轮清单写成 JSON（含剩余缺口）。"),
    ] = None,
) -> None:
    """按缺口批量补抓分红派息事件历史：多轮、可重跑、缺口显式。

    落盘目标严格为 data/raw/neodata/dividend_history/YYYY-MM-DD.csv。
    落地按块身份合并，后一轮不会冲掉前一轮。
    一轮没有带来任何新标的就停下，并把剩余缺口原样报出。
    """
    day = _as_of(as_of)
    if max_rounds <= 0:
        raise typer.BadParameter("--max-rounds 必须为正")
    if batch_size <= 0:
        raise typer.BadParameter("--batch-size 必须为正")
    if limit is not None and limit <= 0:
        raise typer.BadParameter("--limit 必须为正")

    try:
        wanted = read_universe_symbols(universe)
    except (OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    if limit is not None:
        wanted = wanted[:limit]

    provider = _neodata_provider(batch_size=batch_size)
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    typer.echo(f"分红同步研究池: {len(wanted)} 只（as_of {day.date().isoformat()}）")
    rounds: list[dict[str, object]] = []
    stopped = "max_rounds"
    for index in range(1, max_rounds + 1):
        covered = _covered_dividend_symbols(day)
        missing = tuple(symbol for symbol in wanted if symbol not in covered)
        if not missing:
            stopped = "covered"
            typer.echo(f"round {index}: 已全覆盖，无需请求")
            break

        landing = land_neodata_blocks(
            provider=provider,
            root=_csv_root(),
            dataset="dividend_history",
            values=missing,
            as_of=day,
        )
        after = _covered_dividend_symbols(day)
        landed = tuple(symbol for symbol in missing if symbol in after)
        still_missing = tuple(symbol for symbol in wanted if symbol not in after)
        rounds.append(
            {
                "round": index,
                "requested": len(missing),
                "landed": len(landed),
                "missing": len(still_missing),
                "status": landing.status.value,
                "note": landing.note,
            }
        )
        typer.echo(
            f"round {index}: 请求 {len(missing)} 只，落地 {len(landed)} 只，"
            f"仍缺 {len(still_missing)} 只（{landing.status.value}）"
        )
        if landing.note:
            typer.echo(f"  note: {landing.note}", err=True)
        if not landed:
            stopped = "no_progress"
            typer.echo("本轮没有带来任何新标的，停止继续请求", err=True)
            break
    else:
        stopped = "max_rounds"

    covered = _covered_dividend_symbols(day)
    missing_symbols = tuple(symbol for symbol in wanted if symbol not in covered)
    typer.echo(
        f"分红覆盖: {len(wanted) - len(missing_symbols)} / {len(wanted)}；"
        f"缺口 {len(missing_symbols)} 只；停止原因 {stopped}"
    )
    if missing_symbols:
        typer.echo(f"剩余缺口: {', '.join(missing_symbols[:20])}")
        if len(missing_symbols) > 20:
            typer.echo(f"  … 及其余 {len(missing_symbols) - 20} 只")

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "dataset": "dividend_history",
                    "as_of": day.isoformat(),
                    "requested_symbols": list(wanted),
                    "covered_symbols": [
                        symbol
                        for symbol in wanted
                        if symbol not in set(missing_symbols)
                    ],
                    "missing_symbols": list(missing_symbols),
                    "stop_reason": stopped,
                    "rounds": rounds,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        typer.echo(f"report: {output}")

    if missing_symbols:
        raise typer.Exit(code=1)


def dividend_coverage_command(
    as_of: Annotated[str, AS_OF_OPTION],
    universe: Annotated[
        Path,
        typer.Option(
            "--universe",
            help="研究池名单：JSON 的 research_symbols，或 CSV 的 symbol 列。",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", help="把报告写入文件（.json 为 JSON，其它为 Markdown）。"
        ),
    ] = None,
) -> None:
    """核对分红事件在研究池上的覆盖情况（只读）。

    分母是 `--universe` 给出的研究池名单。缺名单直接报错：拿'已有分红事件的标的'
    当分母会把覆盖率算成 100%，那是假全覆盖。
    """
    day = _as_of(as_of)
    try:
        symbols = read_universe_symbols(universe)
    except (OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    events = _load_dividend_events(day)
    try:
        report = audit_dividend_coverage(events, symbols, day)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"as_of: {day.isoformat()}")
    typer.echo(f"研究池: {report.universe_size} 只")
    typer.echo(
        f"有任意分红事件: {report.symbols_with_any_event} / {report.universe_size}"
        f"（缺口 {len(report.missing_symbols)} 只）"
    )
    typer.echo(
        f"有已实施现金分红: {report.symbols_with_implemented_cash_event} / {report.universe_size}"
    )
    typer.echo(
        f"具备除权除息日: {report.symbols_with_ex_date} / {report.universe_size}"
    )
    typer.echo(
        f"具备股权登记日: {report.symbols_with_registration_date} / {report.universe_size}"
    )
    typer.echo(
        f"事件分布: 有效总计 {report.event_count} 条，"
        f"实施 {report.implemented_count} 条，预案 {report.proposal_count} 条"
    )

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix.lower() == ".json":
            content = render_dividend_coverage_json(report)
        else:
            content = render_dividend_coverage_markdown(report)
        output.write_text(content, encoding="utf-8")
        typer.echo(f"report: {output}")


def sync_research(
    as_of: Annotated[str, AS_OF_OPTION],
    financials: Annotated[
        bool,
        typer.Option(
            "--financials",
            help="只为研究股票池刷新 WeStock 三大表。",
        ),
    ] = False,
    batch_size: Annotated[
        int,
        typer.Option(
            "--chunk-size",
            help="一次批量请求最多覆盖多少只标的；技术默认 100，不是产品阈值。",
        ),
    ] = 100,
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            help=(
                "并发取数的上限（in-flight）；默认 1（串行），"
                "并发需所有者批准后显式传入。"
            ),
        ),
    ] = 1,
) -> None:
    """Enrich the Research Universe only, with resumable chunking.

    The expensive layer — strategy-length price history, and optionally the
    financial statements — is fetched for the research population and nobody
    else. Valuation stays blocked: this command will not issue ~2,500
    single-symbol neodata calls, and reports the block instead.
    """
    day = _as_of(as_of)
    cal = get_calendar()
    if not cal.is_trade_date(day.date()):
        typer.echo(
            f"{day.date().isoformat()} is a non-trading day (weekend/holiday). Skipping market data sync."
        )
        if not financials:
            return

    provider = _bulk_provider()
    health = provider.health()

    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    factor_configs = _factor_configs()
    state = compute_research_universe(
        csv_root=_csv_root(),
        as_of=day,
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=factor_configs,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )
    required_bars = strategy_history_requirement(factor_configs)

    typer.echo(f"listing: {len(state.excluded) + len(state.research_symbols)} counted")
    typer.echo(f"listing prefilter: {len(state.listing_prefilter_symbols)} symbols")
    typer.echo(f"research universe: {len(state.research_symbols)} symbols")
    typer.echo(f"price history required: {required_bars} bars per symbol")

    result = bootstrap_strategy_history(
        # Task 3 的只读探测结论是 `NO_BATCH_PRIMARY_AVAILABLE`：
        # 没有经过证据背书的批量行情来源，就不接线、不发明。
        batch_source=None,
        fallback_source=_symbol_bar_provider(provider),
        root=_csv_root(),
        as_of=day,
        symbols=state.research_symbols,
        required_price_bars=required_bars,
        end_date=day.date(),
        batch_size=batch_size,
        max_inflight=workers,
        progress=_HeartbeatSink(),
    )
    typer.echo(f"price history satisfied: {len(result.satisfied_symbols)}")
    typer.echo(f"price history short: {len(result.short_symbols)}")
    typer.echo(f"could not be fetched: {len(result.failed_symbols)}")

    if financials:
        statements = land_financial_statements(
            provider=_financial_provider(),
            root=_csv_root(),
            as_of=day,
            symbols=state.research_symbols,
            datasets=tuple(sorted(FINANCIAL_DATASETS)),
        )
        for landing in statements.landings:
            typer.echo(
                f"{landing.dataset} {landing.status.value}: "
                f"{landing.rows_written} rows written"
            )

    typer.echo("valuation enrichment: BLOCKED_PENDING_INDUSTRY_PATH")

    if result.failed_symbols:
        raise typer.Exit(code=1)


def sync_bootstrap(
    as_of: Annotated[str, AS_OF_OPTION],
    batch_size: Annotated[
        int,
        typer.Option(
            "--chunk-size",
            help=(
                "一次批量请求最多覆盖多少只标的。技术默认 50，可按源站限速调整；"
                "它不是产品阈值，不写入 configs/。"
            ),
        ),
    ] = 50,
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            help=(
                "并发取数的上限（in-flight）。默认 1（串行）——设计文档把限速与并发策略列为 "
                "Deferred，因此并发必须由资源所有者显式批准后传入，不是默认行为。"
            ),
        ),
    ] = 1,
    limit_symbols: Annotated[
        int | None,
        typer.Option(
            "--limit-symbols",
            help=(
                "基准/运维专用：只对确定性抽样后的前 N 只标的取历史。默认不限制；"
                "它不改变产品 Universe 语义，也不是产品阈值。"
            ),
        ),
    ] = None,
) -> None:
    """Land the least price history a cold start needs, resumably.

    The listing lands first, the listing-only prefilter decides which symbols
    deserve history, and only those symbols are fetched. How much history is
    enough comes from the configured liquidity factor's window and is measured
    in valid bars, never in calendar days.

    Every completed chunk is persisted before the next one starts, so an
    interrupted run resumes at the missing coverage instead of from zero. A
    symbol the source could not answer for is reported; no row is invented.
    """
    day = _as_of(as_of)
    provider = _bulk_provider()
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    root = _csv_root()
    dataset = _securities_dataset()
    landing = land_securities_listing(
        provider=provider, root=root, as_of=day, dataset=dataset
    )
    typer.echo(
        f"securities {landing.status.value}: {landing.rows_total} rows "
        f"in {landing.path}"
    )
    if landing.status not in DONE_STATUSES:
        typer.echo(
            "the listing did not land, so a prefilter would be judging an "
            f"incomplete market: {landing.note or landing.status.value}",
            err=True,
        )
        raise typer.Exit(code=1)

    raw = LocalCsvProvider(root).fetch(
        FetchRequest(dataset=dataset, as_of=day, symbols=None)
    )
    profiles = CsvSecurityNormalizer().normalize(raw, as_of=day).securities
    universe_config = load_universe_config(_universe_config_path())
    prefiltered = prefilter_listing(profiles, config=universe_config, as_of=day)
    requirement = liquidity_bootstrap_requirement(_factor_configs())

    typer.echo(f"listing: {len(profiles)} symbols")
    typer.echo(f"prefilter: {len(prefiltered.included)} symbols pass listing rules")
    typer.echo(
        f"bootstrap: {requirement.required_valid_bars} valid bars of "
        f"{requirement.factor_name} per symbol, window read from configs/factors"
    )

    population = prefiltered.included
    if limit_symbols is not None:
        population = _benchmark_subset(population, limit=limit_symbols)
        typer.echo(
            f"benchmark subset: {len(population)} of {len(prefiltered.included)} "
            "prefiltered symbols (operator-only; product Universe unchanged)"
        )

    result = bootstrap_liquidity_history(
        # 同上：批量来源没有证据背书，接线为 None，补缺逐标的进行。
        batch_source=None,
        fallback_source=_symbol_bar_provider(provider),
        root=root,
        as_of=day,
        symbols=population,
        requirement=requirement,
        end_date=day.date(),
        batch_size=batch_size,
        max_inflight=workers,
        progress=_HeartbeatSink(),
    )

    _, bar_rows = read_raw_rows(root / f"{_dataset()}.csv")
    typer.echo(f"satisfied: {len(result.satisfied_symbols)}")
    typer.echo(f"short of history: {len(result.short_symbols)}")
    typer.echo(f"could not be fetched: {len(result.failed_symbols)}")
    typer.echo(f"bars landed: {len(bar_rows)} rows")

    if result.failed_symbols:
        raise typer.Exit(code=1)


def sync(
    as_of: Annotated[
        str | None,
        typer.Option(
            "--as-of", help="Trade date, YYYY-MM-DD; defaults to today's close."
        ),
    ] = None,
    symbol: Annotated[
        list[str] | None,
        typer.Option("--symbol", help="Limit the sync to these symbols."),
    ] = None,
    financials: Annotated[
        bool,
        typer.Option(
            "--financials",
            help="Also land the three financial statements from the WeStock CLI.",
        ),
    ] = False,
    statements_only: Annotated[
        bool,
        typer.Option(
            "--statements-only",
            help=(
                "Land only the financial statements, using the listing already "
                "on disk. This is the quarterly whole-market refresh: it skips "
                "the per-symbol daily-bar fetch entirely."
            ),
        ),
    ] = False,
    valuation: Annotated[
        bool,
        typer.Option(
            "--valuation",
            help=(
                "同时取 neodata 估值（PE/PB/PS/历史分位/PEG…）。"
                "需要 --symbol：估值批量覆盖极低（实测 10 只只回 1–2 只），"
                "且 neodata 不做标的枚举。"
            ),
        ),
    ] = False,
) -> None:
    """Land raw data for one date, skipping what is already there.

    Symbols already carrying the target date are not fetched again, which is
    the incremental rule `spec §15` requires. Without `--symbol`, the listing
    decides which symbols to fetch, so the scan covers the market it claims to.
    """
    day = _as_of(as_of) if as_of is not None else _today_close()
    # 调用方错误先报，再去做昂贵的事：脚本化的入口更该 fail fast，
    # 而不是先抓几十秒行情、再告诉使用者参数不对。
    if valuation and not symbol:
        typer.echo(
            "取估值需要 --symbol：neodata 不做标的枚举，且估值批量覆盖极低"
            "（实测 10 只只回 1–2 只）",
            err=True,
        )
        raise typer.Exit(code=1)

    provider = _bulk_provider()
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    landings: list[DatasetLanding] = []
    failed: list[str] = []
    if not statements_only:
        result = land_raw(
            provider=provider,
            root=_csv_root(),
            as_of=day,
            symbols=tuple(symbol) if symbol else None,
        )
        landings.extend(result.landings)
        failed.extend(result.failed_datasets)

    if financials or statements_only:
        financial_result = _land_financials(day, symbols=symbol)
        landings.extend(financial_result.landings)
        failed.extend(financial_result.failed_datasets)

    if valuation:
        landings.append(_land_valuation(day, symbols=symbol))

    for landing in landings:
        typer.echo(
            f"{landing.dataset} {landing.status}: {landing.rows_written} rows "
            f"written, {landing.rows_total} in {landing.path}"
        )
        if landing.symbols_skipped:
            typer.echo(
                f"  skipped {len(landing.symbols_skipped)} symbols already "
                "landed for this date"
            )
        if landing.symbols_missing:
            typer.echo(
                f"  {len(landing.symbols_missing)} symbols were requested but "
                "the source returned nothing for them"
            )
        if landing.note is not None:
            typer.echo(f"  {landing.note}")

    if failed:
        typer.echo(f"sync incomplete: {', '.join(failed)}", err=True)
        raise typer.Exit(code=1)


def register_doctor(app: typer.Typer) -> None:
    app.command()(doctor)


def register_commands(
    app: typer.Typer, industry_app: typer.Typer, calendar_app: typer.Typer
) -> None:
    calendar_app.command("is-open")(calendar_is_open)
    calendar_app.command("latest")(calendar_latest)
    app.command("sync-industry")(sync_industry)
    industry_app.command("export-map")(industry_export_map)
    app.command("valuation-coverage")(valuation_coverage_command)
    app.command("sync-valuation")(sync_valuation)
    app.command("sync-dividends")(sync_dividends)
    app.command("dividend-coverage")(dividend_coverage_command)
    app.command("sync-research")(sync_research)
    app.command("sync-bootstrap")(sync_bootstrap)
    app.command()(sync)
