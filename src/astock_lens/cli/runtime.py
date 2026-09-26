"""CLI 共用运行时：配置、存储与 Provider 组合。"""

import csv
import hashlib
import os
import re
import sys
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import typer
from pydantic import BaseModel

from astock_lens.candidates.policy import RepresentativeCandidatePolicy
from astock_lens.data.benchmark import BENCHMARK_BARS_ENV, read_benchmark_bars
from astock_lens.data.bootstrap_progress import BootstrapProgress, render_progress
from astock_lens.data.bootstrap_sources import (
    BatchMarketBarSource,
    SymbolBarFallbackSource,
)
from astock_lens.data.contracts import DataProvider
from astock_lens.data.dividends.models import DividendEvent
from astock_lens.data.dividends.normalize import normalize_dividend_events
from astock_lens.data.providers.akshare_provider import AkShareProvider
from astock_lens.data.providers.lake import LakeProvider
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.providers.neodata import NeodataProvider
from astock_lens.data.providers.westock import FINANCIAL_DATASETS, WestockCliProvider
from astock_lens.data.providers.westock_bars import WestockBarsProvider
from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.data.storage.paths import StoragePaths, resolve_storage_paths
from astock_lens.data.sync import (
    DatasetLanding,
    SyncResult,
    land_financial_statements,
    land_neodata_blocks,
    land_raw,
    read_raw_rows,
    read_symbols,
)
from astock_lens.domain.enums import SnapshotKind
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.jobs.models import StageOutcome
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines import stages
from astock_lens.pipelines.analysis import (
    AnalysisState,
    FactorState,
    compute_factor_state,
    run_analysis,
)
from astock_lens.pipelines.daily import DailyRunResult, run_daily
from astock_lens.qualifications import (
    QualificationRuleNotConfigured,
    load_canonical_qualifiers,
)
from astock_lens.settings import resolve_config_path
from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.registry import (
    RegisteredStrategy,
    StrategyNotImplementedError,
    load_scanners,
    strategy_paths,
)
from astock_lens.universe.config import load_universe_config
from astock_lens.watchlist.store import WatchlistStore, resolve_watchlist_store

MINIMUM_PYTHON = (3, 12)
CSV_ROOT_ENV = "ASTOCK_CSV_ROOT"
DATASET_ENV = "ASTOCK_DATASET"
SECURITIES_DATASET_ENV = "ASTOCK_SECURITIES_DATASET"
WATCHLIST_BACKEND_ENV = "ASTOCK_WATCHLIST_BACKEND"
FACTOR_CONFIG_DIR_ENV = "ASTOCK_FACTOR_CONFIG_DIR"
UNIVERSE_CONFIG_ENV = "ASTOCK_UNIVERSE_CONFIG"
STRATEGY_CONFIG_DIR_ENV = "ASTOCK_STRATEGY_CONFIG_DIR"
DEFAULT_CSV_ROOT = Path("data/raw")
DEFAULT_DATASET = "daily_bars"
DEFAULT_SECURITIES_DATASET = "securities"
DEFAULT_FACTOR_CONFIG_DIR = Path("configs/factors")
DEFAULT_UNIVERSE_CONFIG = Path("configs/universe.yaml")
DEFAULT_STRATEGY_CONFIG_DIR = Path("configs/strategies")
STRATEGY_CONFIG_PATH = Path("configs/strategies/momentum.yaml")
LOW_COVERAGE_WARNING_RATIO = 0.90
SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE_HOUR = 15
AS_OF_OPTION = typer.Option("--as-of", help="Trade date, YYYY-MM-DD.")


def _configured_config_path() -> Path:
    return resolve_config_path()


def _as_of(value: str) -> datetime:
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(
            f"--as-of must be YYYY-MM-DD, got {value!r}"
        ) from error
    return datetime(day.year, day.month, day.day, CLOSE_HOUR, tzinfo=SHANGHAI)


def _factor_configs() -> tuple[FactorConfig, ...]:
    directory = Path(os.getenv(FACTOR_CONFIG_DIR_ENV, str(DEFAULT_FACTOR_CONFIG_DIR)))
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        typer.echo(f"no factor configuration found under {directory}", err=True)
        raise typer.Exit(code=1)
    return tuple(load_factor_config(path) for path in paths)


def _csv_root() -> Path:
    return Path(os.getenv(CSV_ROOT_ENV, str(DEFAULT_CSV_ROOT)))


def _dataset() -> str:
    return os.getenv(DATASET_ENV, DEFAULT_DATASET)


def _securities_dataset() -> str:
    return os.getenv(SECURITIES_DATASET_ENV, DEFAULT_SECURITIES_DATASET)


def _benchmark_bars_path() -> Path:
    configured_path = os.getenv(BENCHMARK_BARS_ENV)
    return (
        Path(configured_path) if configured_path else _csv_root() / "benchmark_bars.csv"
    )


def _storage_paths() -> StoragePaths:
    return resolve_storage_paths()


def _store() -> SnapshotStore:
    paths = _storage_paths()
    return resolve_snapshot_store(paths.snapshot_root, database=paths.database)


def _factor_state(as_of_value: str) -> FactorState:
    return compute_factor_state(
        csv_root=_csv_root(),
        as_of=_as_of(as_of_value),
        factor_configs=_factor_configs(),
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )


def _analysis(
    as_of_value: str, *, scanners: Sequence[RegisteredStrategy]
) -> AnalysisState:
    return run_analysis(
        csv_root=_csv_root(),
        as_of=_as_of(as_of_value),
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=_factor_configs(),
        scanners=scanners,
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
    )


def _universe_state(as_of_value: str) -> AnalysisState:
    return _analysis(as_of_value, scanners=())


def _preview_state(as_of_value: str) -> AnalysisState:
    return _analysis(as_of_value, scanners=load_scanners(_strategy_dir()))


def _universe_config_path() -> Path:
    return Path(os.getenv(UNIVERSE_CONFIG_ENV, str(DEFAULT_UNIVERSE_CONFIG)))


def _strategy_dir() -> Path:
    return Path(os.getenv(STRATEGY_CONFIG_DIR_ENV, str(DEFAULT_STRATEGY_CONFIG_DIR)))


def _watchlist_store() -> WatchlistStore:
    paths = _storage_paths()
    return resolve_watchlist_store(paths.watchlist_root, database=paths.database)


def _job_store() -> JsonJobStore:
    return JsonJobStore(_storage_paths().job_root)


def _financial_provider() -> WestockCliProvider:
    return WestockCliProvider()


def _neodata_provider(batch_size: int | None = None) -> NeodataProvider:
    return (
        NeodataProvider()
        if batch_size is None
        else NeodataProvider(batch_size=batch_size)
    )


def _bulk_provider() -> DataProvider:
    selected = os.getenv("ASTOCK_BULK_PROVIDER", "westock").strip().lower()
    if selected == "westock":
        return WestockBarsProvider(progress_callback=_report_bulk_progress)
    if selected == "akshare":
        # 复用同一个进度回调：两端用户看到的格式一致
        # （"已处理 X/Y 只，缺失 X 只，待处理 X 只"）。
        # AkShareProvider 在 _fetch_bars 成功一只就打一次回调，
        # 失败让它照旧 raise（既有契约）；progress 是 best-effort。
        return AkShareProvider(progress_callback=_report_bulk_progress)
    if selected == "lake":
        # 数据湖日线：本地 Parquet 读，无需进度回调（全市场单日 <1s），
        # 底层不依赖腾讯，是 westock/akshare 的正交替代。
        return LakeProvider()
    raise typer.BadParameter(
        f"ASTOCK_BULK_PROVIDER must be 'westock', 'akshare', or 'lake', "
        f"got {selected!r}"
    )


def _report_bulk_progress(processed: int, total: int, downloaded: int) -> None:
    missing = processed - downloaded
    pending = total - processed
    typer.echo(
        f"日线下载进度：已处理 {processed}/{total} 只，成功 {downloaded} 只，"
        f"缺失 {missing} 只，待处理 {pending} 只",
        err=True,
    )
    # 与 _HeartbeatSink 同纪律：进度可见必须落到磁盘/管道。
    # 重定向时 stderr 是块缓冲的（macOS ~4 KB），不 flush 的话一行心跳要等几十行
    # 之后才可见，cron 场景下等于"没实现"。
    sys.stderr.flush()


def _symbol_bar_fallback(provider: DataProvider) -> SymbolBarFallbackSource:
    if isinstance(provider, SymbolBarFallbackSource):
        return provider
    return AkShareProvider()


def _batch_source(provider: DataProvider) -> BatchMarketBarSource | None:
    """把批量补缺来源接进 bootstrap：只有真正实现了批量契约的源才接。

    2026-09-18 探测的 `NO_BATCH_PRIMARY_AVAILABLE` 结论对 westock/akshare 仍然成立，
    它们没有批量接口，`batch_source` 就该是诚实的 `None`（缺口全走逐标的补缺）。
    数据湖是第一个经过证据背书、能整段窗口一次返回的批量日线源：选中它时把
    它自己接上，冷启动就不再逐只 ~1 秒地抠。判据是"有没有 `fetch_recent_bars`"，
    不是类型名单——新批量源无需改这里。
    """
    if hasattr(provider, "fetch_recent_bars"):
        return cast("BatchMarketBarSource", provider)
    return None


def _listing_provider(provider: DataProvider) -> DataProvider:
    # westock / 数据湖都只服务日线，不做标的枚举：名单一律走 AkShare。
    if isinstance(provider, WestockBarsProvider | LakeProvider):
        return AkShareProvider()
    return provider


def _snapshot_records[T: BaseModel](
    kind: SnapshotKind, as_of: datetime, model: type[T]
) -> tuple[T, ...]:
    return tuple(model.model_validate(record) for record in _store().read(kind, as_of))


def _value_text(value: float | None, status: object) -> str:
    return "no value" if value is None else f"{value} ({status})"


class _HeartbeatSink:
    """把进度快照打成一行。

    冷启动命令自己输出进度（设计文档 §3.6）：外部 watcher 只是第二块屏幕上的便利工具，
    不再是判断"还在动"的唯一途径。这一行里的每个数字都来自本次 invocation。

    必须**逐行 flush**：stdout 被重定向到日志文件时是按块缓冲的（8 KB），不 flush 的话
    一行心跳要等几十行之后才落盘——2026-09-18 真实 100 只门禁里实测：日志里 0 行心跳，
    而缓冲区里正躺着刚打印的进度，"进度可见"在 cron/重定向场景下等于没实现。
    """

    def emit(self, progress: BootstrapProgress) -> None:
        typer.echo(render_progress(progress))
        sys.stdout.flush()


def _benchmark_subset(symbols: Sequence[str], *, limit: int) -> tuple[str, ...]:
    """基准/运维专用：从预筛结果里确定性地取 `limit` 只标的。

    **不是产品规则**，因此不进 `configs/`，也不改变 Universe 语义：预筛仍然在全市场列表上
    跑，这里只决定"这次真正去取历史的是哪几只"，用于在跑全市场之前先用小样本验证真实链路。
    抽样等距跨越整份列表，避免"只取代码最小的 100 只"把交易所与板块偏差带进基准；同样的输入
    永远得到同样的子集。
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    ordered = tuple(dict.fromkeys(symbols))
    if limit >= len(ordered):
        return ordered
    stride = len(ordered) // limit
    return tuple(ordered[::stride][:limit])


def _today_close() -> datetime:
    """The A-share close on the current date in Shanghai."""
    today = datetime.now(SHANGHAI).date()
    return datetime(today.year, today.month, today.day, CLOSE_HOUR, tzinfo=SHANGHAI)


def _strategy_config(strategy_id: str) -> StrategyConfig:
    """Load one scanner's configuration, refusing an id nobody configured."""
    for path in strategy_paths(_strategy_dir()):
        config = load_strategy_config(path)
        if config.id == strategy_id:
            return config
    configured = sorted(
        load_strategy_config(path).id for path in strategy_paths(_strategy_dir())
    )
    raise StrategyNotImplementedError(
        f"strategy {strategy_id!r} has no configuration under "
        f"{_strategy_dir()}; configured scanners are {configured}"
    )


def _ranked(results: tuple[StrategyResult, ...]) -> tuple[StrategyResult, ...]:
    """Order a scanner's results from best to worst, unscored ones last."""
    return tuple(
        sorted(results, key=lambda item: (item.score is None, -(item.score or 0.0)))
    )


def _run_daily(day: datetime, *, land: bool) -> DailyRunResult:
    """Run the daily pipeline with the configured paths."""
    scanners = load_scanners(_strategy_dir())
    factor_configs = _factor_configs()
    factor_names = frozenset(config.name for config in factor_configs)
    try:
        qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
    except QualificationRuleNotConfigured:
        qualifiers = None
    candidate_policy = (
        RepresentativeCandidatePolicy(version="v1") if qualifiers else None
    )
    benchmark_path = _benchmark_bars_path()
    benchmark_bars = read_benchmark_bars(
        path=benchmark_path,
        benchmark_id="000985.CSI",
        as_of=day,
    )
    industry_by_symbol = _production_industry_map(day)
    return run_daily(
        csv_root=_csv_root(),
        as_of=day,
        universe_config=load_universe_config(_universe_config_path()),
        factor_configs=factor_configs,
        scanners=scanners,
        strategy_directory=_strategy_dir(),
        store=_store(),
        job_store=_job_store(),
        dataset=_dataset(),
        securities_dataset=_securities_dataset(),
        sync=_sync_stage(day) if land else None,
        qualifiers=qualifiers,
        candidate_policy=candidate_policy,
        benchmark_id="000985.CSI",
        benchmark_bars=benchmark_bars,
        industry_by_symbol=industry_by_symbol,
    )


def _sync_stage(day: datetime) -> Callable[[], StageOutcome]:
    """Land raw data, and report the landing as a stage outcome."""

    def stage() -> StageOutcome:
        result = _land(day)
        return StageOutcome(
            rows_in=len(result.landings),
            rows_out=sum(landing.rows_written for landing in result.landings),
            note=", ".join(
                f"{landing.dataset} {landing.status.value}"
                for landing in result.landings
            ),
        )

    return stage


def _land(day: datetime) -> SyncResult:
    """Land raw data from the bulk provider, failing loudly when unusable."""
    provider = _bulk_provider()
    health = provider.health()
    if not health.healthy:
        raise RuntimeError(
            f"provider {health.provider} is not usable: {health.message}"
        )
    root = _csv_root()
    listing_path = root / f"{_securities_dataset()}.csv"
    listing_provider = (
        LocalCsvProvider(root)
        if listing_path.is_file()
        else _listing_provider(provider)
    )
    return land_raw(
        provider=provider,
        listing_provider=listing_provider,
        root=root,
        as_of=day,
    )


def _latest_industry_file(day: datetime, root: Path | None = None) -> Path:
    """按时点查找不晚于该日期的最新申万行业 CSV 文件。"""
    directory = (root or _csv_root()) / "westock" / "industry"
    target_date = day.date()
    eligible: list[tuple[date, Path]] = []
    if directory.is_dir():
        for file in directory.glob("*.csv"):
            try:
                file_date = date.fromisoformat(file.stem)
            except ValueError:
                continue
            if file_date <= target_date:
                eligible.append((file_date, file))
    if not eligible:
        raise FileNotFoundError(
            f"No eligible industry file found in {directory} for date {day.date().isoformat()}"
        )
    eligible.sort(key=lambda item: item[0])
    return eligible[-1][1]


def _production_industry_map(day: datetime, root: Path | None = None) -> dict[str, str]:
    """按时点加载生产申万二级行业映射（含权威静态补充）。"""
    from astock_lens.data.industry import load_production_industry_map

    return load_production_industry_map(day, root or _csv_root())


def _valuation_strategy_configs() -> tuple[StrategyConfig, ...]:
    """读策略目录里的全部策略配置；覆盖报告按 `required_factors` 判定，不认策略名。"""
    return tuple(
        load_strategy_config(path) for path in sorted(_strategy_dir().glob("*.yaml"))
    )


def _covered_valuation_symbols(day: datetime) -> frozenset[str]:
    """当前落地的估值里，真正带值的标的（缺值是缺值，不是 0）。"""
    inputs = stages.valuation_inputs(_csv_root(), as_of=day)
    return frozenset(
        item.symbol for item in inputs.observations if item.value is not None
    )


def _covered_dividend_symbols(
    day: datetime, root: Path | None = None
) -> frozenset[str]:
    """当前落地的分红事件数据里，真正出现的标的代码。"""
    csv_root = root if root is not None else _csv_root()
    path = csv_root / "neodata" / "dividend_history" / f"{day.date().isoformat()}.csv"
    if not path.is_file():
        return frozenset()
    _, rows = read_raw_rows(path)
    symbols: set[str] = set()
    for row in rows:
        if len(row) >= 3:
            content = row[2]
            for m in re.finditer(r"([0-9]{6}\.[A-Z]{2})", content):
                symbols.add(m.group(1))
    return frozenset(symbols)


def _load_dividend_events(
    day: datetime, root: Path | None = None
) -> tuple[DividendEvent, ...]:
    """读取已落地的分红历史原始数据并归一化为分红事件列表。"""
    csv_root = root if root is not None else _csv_root()
    path = csv_root / "neodata" / "dividend_history" / f"{day.date().isoformat()}.csv"
    if not path.is_file():
        return ()
    _, rows = read_raw_rows(path)
    events: list[DividendEvent] = []
    for row in rows:
        if len(row) >= 3:
            events.extend(normalize_dividend_events(row[2], default_as_of=day))
    return tuple(events)


def _land_financials(day: datetime, *, symbols: list[str] | None) -> SyncResult:
    """Land the three statements for the symbols the listing carries."""
    wanted = tuple(symbols) if symbols else read_symbols(_csv_root() / "securities.csv")
    if not wanted:
        typer.echo(
            "no symbols to fetch statements for: land the securities listing "
            "first, or pass --symbol",
            err=True,
        )
        raise typer.Exit(code=1)

    provider = _financial_provider()
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    return land_financial_statements(
        provider=provider,
        root=_csv_root(),
        as_of=day,
        symbols=wanted,
        datasets=tuple(sorted(FINANCIAL_DATASETS)),
    )


def _land_valuation(day: datetime, *, symbols: list[str] | None) -> DatasetLanding:
    """取并落一天的估值数据。

    必须显式给名单：neodata 不做标的枚举，而它的估值批量覆盖极低
    （实测 10 只一批只回 1–2 只），拿整份名单逐只跑是几小时级的事情。
    与其猜一个名单，不如要求调用方明确说要哪几只。
    """
    if not symbols:
        typer.echo(
            "取估值需要 --symbol：neodata 不做标的枚举，且估值批量覆盖极低"
            "（实测 10 只只回 1–2 只）",
            err=True,
        )
        raise typer.Exit(code=1)

    provider = _neodata_provider()
    health = provider.health()
    if not health.healthy:
        typer.echo(
            f"provider {health.provider} is not usable: {health.message}", err=True
        )
        raise typer.Exit(code=1)

    return land_neodata_blocks(
        provider=provider,
        root=_csv_root(),
        dataset="valuation",
        values=tuple(symbols),
        as_of=day,
    )


def _file_sha256(path: Path) -> str:
    """一份映射文件的摘要：让报告里的"用的是哪份文件"可以被复算。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _declared_mapping_as_of(value: str | None) -> datetime | None:
    """把命令行声明的映射日期解析成带时区的时间；没给就是 `None`。

    裸时间不是事实：没有时区的 ISO 串被拒绝，而不是被悄悄补上本机时区。缺省
    留 `None` 也不许拿文件 mtime 顶替——mtime 是文件系统的噪声，不是映射的时点。
    """
    if value is None:
        return None
    try:
        declared = datetime.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(
            f"--industry-map-as-of must be an ISO-8601 datetime, got {value!r}"
        ) from error
    if declared.tzinfo is None or declared.tzinfo.utcoffset(declared) is None:
        raise typer.BadParameter(
            "--industry-map-as-of needs a timezone offset (e.g. "
            f"2026-09-17T15:00:00+08:00); a bare time is not a fact, got {value!r}"
        )
    return declared


def _load_industry_map(path: Path) -> dict[str, str]:
    """Load and validate the symbol-to-industry CSV mapping."""
    if not path.is_file():
        typer.echo(f"industry map file not found: {path}", err=True)
        raise typer.Exit(code=1)

    mapping: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                typer.echo(f"industry map CSV is empty: {path}", err=True)
                raise typer.Exit(code=1)
            fields = [field.strip() for field in reader.fieldnames if field]
            if "symbol" not in fields or "industry" not in fields:
                typer.echo(
                    f"industry map CSV must have 'symbol' and 'industry' columns: {path}",
                    err=True,
                )
                raise typer.Exit(code=1)
            for row_idx, row in enumerate(reader, start=2):
                sym = (row.get("symbol") or "").strip()
                ind = (row.get("industry") or "").strip()
                if not sym or not ind:
                    typer.echo(
                        f"industry map row {row_idx} is missing symbol or industry",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                if sym in mapping:
                    typer.echo(
                        f"duplicate symbol in industry map at row {row_idx}: {sym}",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                mapping[sym] = ind
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"failed to read industry map {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not mapping:
        typer.echo(f"industry map CSV has no data rows: {path}", err=True)
        raise typer.Exit(code=1)

    return mapping
