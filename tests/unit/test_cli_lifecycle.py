"""CLI lifecycle tests.

`spec §17` requires the CLI to be a first-class surface, usable from cron and
from coding agents without the Web UI. These tests cover the commands that
make the lifecycle reachable: tracking a symbol, reading a stock profile out
of the stored snapshots, running one scanner, running the daily pipeline, and
handing a research request to the adapter boundary.

Every one of them follows the same rule: a command that cannot do what it was
asked reports why and exits non-zero rather than printing a reassuring line.
"""

import json
import shlex
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import Result
from typer.testing import CliRunner

from astock_lens.cli.app import app
from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.domain.enums import DataStatus

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
DAY = "2026-09-04"
LONG_DATASET = "daily_bars_long"
SHORT_DATASET = "daily_bars"

RESEARCH_RESPONDER = shlex.join(
    [
        sys.executable,
        "-c",
        (
            "import json,sys;"
            "payload=json.load(sys.stdin);"
            "request=payload.get('request') or {};"
            "print(json.dumps({"
            "'job_id': 'job-' + (request.get('thesis') or request.get('symbol') or 'x'),"
            "'symbol': request.get('symbol') or 'unknown',"
            "'submitted_at': '2026-09-04T15:05:00+00:00'}))"
        ),
    ]
)


class StubProvider:
    """A bulk provider that answers from memory, so no test needs the network."""

    def __init__(self) -> None:
        self.requests: list[FetchRequest] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="stub",
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=datetime(2026, 9, 4, 15, 5, tzinfo=UTC),
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        self.requests.append(request)
        if request.dataset == "securities":
            return self._dataset(
                request,
                ("symbol", "name", "exchange", "list_date"),
                (("600519.SH", "Moutai", "SSE", "2001-08-27"),),
            )
        symbols: Sequence[str] = request.symbols or ()
        return self._dataset(
            request,
            ("symbol", "trade_date", "close"),
            tuple((symbol, DAY, "10.5") for symbol in symbols),
        )

    @staticmethod
    def _dataset(
        request: FetchRequest,
        columns: tuple[str, ...],
        rows: Sequence[tuple[str, ...]],
    ) -> RawDataset:
        return RawDataset(
            provider="stub",
            dataset=request.dataset,
            fetched_at=datetime(2026, 9, 4, 15, 5, tzinfo=UTC),
            provider_version="v1",
            status=DataStatus.VALUE if rows else DataStatus.NULL,
            row_count=len(rows),
            payload=RawPayload(columns=columns, rows=tuple(rows)),
        )


class StubFinancialProvider:
    """A WeStock-shaped provider that answers from memory."""

    def __init__(self, *, healthy: bool = True) -> None:
        self.requests: list[FetchRequest] = []
        self._healthy = healthy

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="westock-cli",
            healthy=self._healthy,
            status=DataStatus.VALUE if self._healthy else DataStatus.SOURCE_ERROR,
            checked_at=datetime(2026, 9, 4, 15, 5, tzinfo=UTC),
            message=None if self._healthy else "binary missing",
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        self.requests.append(request)
        symbols: Sequence[str] = request.symbols or ()
        rows = tuple(
            (f"sh{symbol[:6]}", "2026-06-30", "2026-08-15", "100.0")
            for symbol in symbols
        )
        return RawDataset(
            provider="westock-cli",
            dataset=request.dataset,
            fetched_at=datetime(2026, 9, 4, 15, 5, tzinfo=UTC),
            provider_version="v1",
            status=DataStatus.VALUE if rows else DataStatus.NULL,
            row_count=len(rows),
            missing_symbols=(),
            payload=RawPayload(
                columns=("code", "EndDate", "InfoPublDate", "OperatingRevenue"),
                rows=rows,
            ),
        )


def _env(
    local_tmp: Path, *, dataset: str = LONG_DATASET, **extra: str
) -> dict[str, str]:
    return {
        "ASTOCK_CSV_ROOT": str(CSV_ROOT),
        "ASTOCK_SNAPSHOT_ROOT": str(local_tmp / "snapshots"),
        "ASTOCK_WATCHLIST_ROOT": str(local_tmp / "watchlist"),
        "ASTOCK_JOB_ROOT": str(local_tmp / "jobs"),
        "ASTOCK_DATASET": dataset,
    } | extra


def _invoke(
    local_tmp: Path, *args: str, dataset: str = LONG_DATASET, **extra: str
) -> Result:
    return CliRunner().invoke(
        app, list(args), env=_env(local_tmp, dataset=dataset, **extra)
    )


def _formal_run(local_tmp: Path) -> None:
    """产生正式快照的唯一入口：`daily`。

    `scan` 是预览，它不再写正式快照，所以需要快照的测试必须以 `daily` 铺底。
    """
    result = _invoke(local_tmp, "daily", "--as-of", DAY, "--allow-incomplete")
    assert result.exit_code == 0, result.output


# --- watch -----------------------------------------------------------------


def test_watch_creates_an_entry_at_discovered(local_tmp: Path) -> None:
    result = _invoke(
        local_tmp,
        "watch",
        "600519.SH",
        "--thesis",
        "brand moat",
        dataset=SHORT_DATASET,
    )

    assert result.exit_code == 0
    assert "600519.SH" in result.stdout
    assert "DISCOVERED" in result.stdout
    assert "brand moat" in result.stdout
    assert (local_tmp / "watchlist" / "600519.SH.json").is_file()


def test_watch_records_questions_risks_and_what_it_waits_for(
    local_tmp: Path,
) -> None:
    result = _invoke(
        local_tmp,
        "watch",
        "600519.SH",
        "--key-question",
        "is volume still falling?",
        "--risk-condition",
        "channel inventory rebuild",
        "--waiting-for",
        "Q3 report",
        dataset=SHORT_DATASET,
    )

    assert result.exit_code == 0
    assert "is volume still falling?" in result.stdout
    assert "channel inventory rebuild" in result.stdout
    assert "Q3 report" in result.stdout


def test_watch_lists_what_is_tracked(local_tmp: Path) -> None:
    _invoke(local_tmp, "watch", "600519.SH", dataset=SHORT_DATASET)
    _invoke(local_tmp, "watch", "000001.SZ", dataset=SHORT_DATASET)

    result = _invoke(local_tmp, "watch", dataset=SHORT_DATASET)

    assert result.exit_code == 0
    assert "600519.SH" in result.stdout
    assert "000001.SZ" in result.stdout


def test_an_empty_watchlist_says_so(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "watch", dataset=SHORT_DATASET)

    assert result.exit_code == 0
    assert "empty" in result.stdout


def test_watch_walks_the_confirmed_path_and_records_the_timeline(
    local_tmp: Path,
) -> None:
    for state in ("WATCH", "DEEP_RESEARCH", "TRACK_SIGNAL"):
        result = _invoke(
            local_tmp,
            "watch",
            "600519.SH",
            "--state",
            state,
            "--note",
            "reviewed",
            dataset=SHORT_DATASET,
        )
        assert result.exit_code == 0, result.output
        assert state in result.stdout

    listed = _invoke(local_tmp, "watch", dataset=SHORT_DATASET)
    assert "TRACK_SIGNAL" in listed.stdout


def test_watch_refuses_a_reserved_state(local_tmp: Path) -> None:
    result = _invoke(
        local_tmp, "watch", "600519.SH", "--state", "HOLDING", dataset=SHORT_DATASET
    )

    assert result.exit_code == 1
    assert "HOLDING" in result.output
    assert not (local_tmp / "watchlist" / "600519.SH.json").exists()


def test_watch_refuses_a_skipped_state(local_tmp: Path) -> None:
    result = _invoke(
        local_tmp,
        "watch",
        "600519.SH",
        "--state",
        "DEEP_RESEARCH",
        dataset=SHORT_DATASET,
    )

    assert result.exit_code == 1
    assert "WATCH" in result.output


def test_watch_rejects_a_state_that_is_not_a_state(local_tmp: Path) -> None:
    result = _invoke(
        local_tmp, "watch", "600519.SH", "--state", "MAYBE", dataset=SHORT_DATASET
    )

    assert result.exit_code != 0
    assert "MAYBE" in result.output


# --- stock -----------------------------------------------------------------


def test_stock_profile_reads_the_stored_evidence(local_tmp: Path) -> None:
    _formal_run(local_tmp)

    result = _invoke(local_tmp, "stock", "300750.SZ", "--as-of", DAY)

    assert result.exit_code == 0, result.output
    assert "300750.SZ" in result.stdout
    assert "included" in result.stdout
    assert "momentum" in result.stdout
    assert "ret_20d" in result.stdout
    # 候选资格规则未批准，所以当天不会有 CANDIDATE 快照，Profile 必须直说。
    assert "candidate: none stored" in result.stdout
    assert "lineage" in result.stdout


def test_stock_profile_names_the_rule_that_excluded_a_symbol(
    local_tmp: Path,
) -> None:
    _formal_run(local_tmp)

    result = _invoke(local_tmp, "stock", "000002.SZ", "--as-of", DAY)

    assert result.exit_code == 0, result.output
    assert "000002.SZ" in result.stdout
    assert "ST" in result.stdout


def test_stock_profile_reports_a_watchlist_entry(local_tmp: Path) -> None:
    _formal_run(local_tmp)
    _invoke(local_tmp, "watch", "300750.SZ", "--thesis", "structural growth")

    result = _invoke(local_tmp, "stock", "300750.SZ", "--as-of", DAY)

    assert result.exit_code == 0
    assert "structural growth" in result.stdout
    assert "DISCOVERED" in result.stdout


def test_stock_profile_refuses_a_date_with_no_snapshot(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "stock", "300750.SZ", "--as-of", "2020-01-02")

    assert result.exit_code == 1
    assert "2020-01-02" in result.output


# --- strategy run ----------------------------------------------------------


def test_strategy_run_prints_one_ranking_for_the_named_scanner(
    local_tmp: Path,
) -> None:
    result = _invoke(local_tmp, "strategy", "run", "momentum", "--as-of", DAY)

    assert result.exit_code == 0, result.output
    assert "300750.SZ" in result.stdout
    assert "momentum" in result.stdout
    ranked = [line for line in result.stdout.splitlines() if line.startswith("  ")]
    assert len(ranked) == 7


def test_strategy_run_refuses_a_scanner_that_has_no_implementation(
    local_tmp: Path,
) -> None:
    result = _invoke(local_tmp, "strategy", "run", "industry_trend", "--as-of", DAY)

    assert result.exit_code == 1
    assert "industry_trend" in result.output
    assert "no implementation" in result.output


def test_strategy_run_reports_eligibility_for_a_scanner_without_reviewed_weights(
    local_tmp: Path,
) -> None:
    """Value 的估值数据接进来了，但权重尚未评审，因此只给资格判定。"""
    result = _invoke(local_tmp, "strategy", "run", "value", "--as-of", DAY)

    assert result.exit_code == 0, result.output
    assert "strategy value" in result.stdout
    # 这个 fixture 里没有任何估值数据，因此全部标为不合格，且没有分数。
    assert "no score" in result.stdout
    assert "not eligible" in result.stdout


def test_strategy_run_refuses_an_unknown_id(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "strategy", "run", "nonsense", "--as-of", DAY)

    assert result.exit_code != 0
    assert "nonsense" in result.output


# --- daily -----------------------------------------------------------------


def test_daily_reports_every_stage_and_its_verdict(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "daily", "--as-of", DAY)

    assert result.exit_code == 1
    for stage in (
        "SYNC_DATA",
        "NORMALIZE",
        "COMPUTE_FACTORS",
        "BUILD_UNIVERSE",
        "RUN_STRATEGIES",
        "BUILD_CANDIDATES",
        "DETECT_REGIME",
        "MARKET_VALIDATE",
        "RUN_SIGNALS",
        "UPDATE_WATCHLIST",
        "GENERATE_DAILY_SNAPSHOT",
    ):
        assert stage in result.stdout, stage
    assert "BLOCKED" in result.stdout
    assert "SKIPPED" in result.stdout
    assert (local_tmp / "jobs" / "2026-09-04.json").is_file()


def test_daily_can_be_allowed_to_finish_incomplete(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "daily", "--as-of", DAY, "--allow-incomplete")

    assert result.exit_code == 0, result.output
    assert "BLOCKED" in result.stdout


def test_daily_lands_raw_data_first_when_asked(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import astock_lens.cli.app as cli_module

    provider = StubProvider()
    monkeypatch.setattr(cli_module, "_bulk_provider", lambda: provider)

    raw_root = local_tmp / "raw"
    result = CliRunner().invoke(
        app,
        ["daily", "--as-of", DAY, "--sync", "--allow-incomplete"],
        env=_env(local_tmp) | {"ASTOCK_CSV_ROOT": str(raw_root)},
    )

    assert result.exit_code == 0, result.output
    assert "SYNC_DATA SUCCEEDED" in result.stdout
    assert provider.requests
    assert (raw_root / "daily_bars.csv").is_file()


# --- sync ------------------------------------------------------------------


def test_sync_lands_raw_data_and_reports_what_it_wrote(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import astock_lens.cli.app as cli_module

    raw_root = local_tmp / "raw"
    monkeypatch.setattr(cli_module, "_bulk_provider", StubProvider)

    result = CliRunner().invoke(
        app,
        ["sync", "--as-of", DAY],
        env=_env(local_tmp) | {"ASTOCK_CSV_ROOT": str(raw_root)},
    )

    assert result.exit_code == 0, result.output
    assert (raw_root / "securities.csv").is_file()
    assert (raw_root / "daily_bars.csv").is_file()
    assert "daily_bars" in result.stdout
    assert "securities" in result.stdout


class ListingProvider(StubProvider):
    """一份能过预筛的上市列表 + 逐标的行情，全部来自内存。"""

    def __init__(self, *, count: int = 30) -> None:
        super().__init__()
        self.symbols = tuple(f"{index:06d}.SZ" for index in range(count))
        self.symbol_requests: list[str] = []

    def fetch(self, request: FetchRequest) -> RawDataset:
        if request.dataset != "securities":
            return super().fetch(request)
        self.requests.append(request)
        rows = (
            *(
                (symbol, f"name{index}", "SZSE", "2015-01-05", "False", "False", "")
                for index, symbol in enumerate(self.symbols)
            ),
        )
        return self._dataset(
            request,
            (
                "symbol",
                "name",
                "exchange",
                "list_date",
                "is_st",
                "is_delisting_board",
                "suspended_trading_days",
            ),
            rows,
        )

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date,
        end_date,
    ) -> RawDataset:
        self.symbol_requests.append(symbol)
        return RawDataset(
            provider="stub",
            dataset="daily_bars",
            fetched_at=datetime(2026, 9, 4, 15, 5, tzinfo=UTC),
            provider_version="v1",
            status=DataStatus.VALUE,
            row_count=1,
            payload=RawPayload(
                columns=("symbol", "trade_date", "close", "amount"),
                rows=((symbol, DAY, "10.5", "30000000"),),
            ),
        )


def test_sync_bootstrap_can_be_limited_to_a_deterministic_benchmark_subset(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """基准子集只决定"这次取哪几只"，不改变产品 Universe 语义。"""
    import astock_lens.cli.app as cli_module

    provider = ListingProvider(count=30)
    monkeypatch.setattr(cli_module, "_bulk_provider", lambda: provider)
    raw_root = local_tmp / "raw"

    result = CliRunner().invoke(
        app,
        ["sync-bootstrap", "--as-of", DAY, "--limit-symbols", "10"],
        env=_env(local_tmp) | {"ASTOCK_CSV_ROOT": str(raw_root)},
    )

    expected = cli_module._benchmark_subset(provider.symbols, limit=10)
    assert result.exit_code == 0, result.output
    assert "benchmark subset: 10 of 30" in result.stdout, result.stdout
    assert len(expected) == 10
    assert set(provider.symbol_requests) == set(expected), (
        "只应对基准子集内的标的取历史；多出来的是 "
        f"{sorted(set(provider.symbol_requests) - set(expected))[:5]}"
    )
    # 预筛本身仍跑在全量列表上：30 只都进了 prefilter，只有取数被限制。
    assert "prefilter: 30 symbols pass listing rules" in result.stdout, result.stdout


def test_benchmark_subset_is_deterministic_and_spread_across_the_listing() -> None:
    import astock_lens.cli.app as cli_module

    symbols = tuple(f"{index:06d}.SZ" for index in range(1000))

    first = cli_module._benchmark_subset(symbols, limit=100)
    again = cli_module._benchmark_subset(symbols, limit=100)

    assert first == again, "同样的输入必须得到同样的子集"
    assert len(first) == 100
    assert first != symbols[:100], "抽样要跨整份列表，不是只取代码最小的 100 只"
    assert first[0] == symbols[0] and first[-1] != symbols[99]

    with pytest.raises(ValueError, match="limit"):
        cli_module._benchmark_subset(symbols, limit=0)


class _RecordingStdout:
    """记录写入与 flush 次数的假 stdout。"""

    def __init__(self) -> None:
        self.text = ""
        self.flushes = 0

    def write(self, chunk: str) -> int:
        self.text += chunk
        return len(chunk)

    def flush(self) -> None:
        self.flushes += 1


def test_the_heartbeat_is_flushed_so_a_redirected_log_shows_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stdout 被重定向时按块缓冲：不 flush 就等于没有心跳。

    2026-09-18 真实 100 只门禁实测：日志里 0 行心跳，进度全躺在 8 KB 缓冲区里。
    """
    import astock_lens.cli.app as cli_module
    from astock_lens.data.bootstrap_progress import BootstrapProgress

    stream = _RecordingStdout()
    monkeypatch.setattr(cli_module.sys, "stdout", stream)

    cli_module._HeartbeatSink().emit(
        BootstrapProgress(
            total=100,
            processed=40,
            satisfied=39,
            failed=1,
            pending=60,
            inflight=6,
            elapsed_seconds=12.0,
            throughput_per_second=3.3,
        )
    )

    assert "processed 40/100" in stream.text
    assert stream.flushes >= 1, "心跳必须逐行 flush，否则重定向日志里看不到进度"


def test_sync_can_also_land_the_financial_statements(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import astock_lens.cli.app as cli_module

    raw_root = local_tmp / "raw"
    financial = StubFinancialProvider()
    monkeypatch.setattr(cli_module, "_bulk_provider", StubProvider)
    monkeypatch.setattr(cli_module, "_financial_provider", lambda: financial)

    result = CliRunner().invoke(
        app,
        ["sync", "--as-of", DAY, "--financials"],
        env=_env(local_tmp) | {"ASTOCK_CSV_ROOT": str(raw_root)},
    )

    assert result.exit_code == 0, result.output
    for name in ("financial_income", "financial_balance", "financial_cashflow"):
        assert (raw_root / f"{name}.csv").is_file(), name
    assert "financial_income" in result.stdout
    # The listing decided the symbols: the stub listing carries one instrument.
    assert {
        symbol for request in financial.requests for symbol in request.symbols or ()
    } == {"600519.SH"}


def test_sync_financials_refuses_an_unusable_provider(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import astock_lens.cli.app as cli_module

    monkeypatch.setattr(cli_module, "_bulk_provider", StubProvider)
    monkeypatch.setattr(
        cli_module, "_financial_provider", lambda: StubFinancialProvider(healthy=False)
    )

    result = CliRunner().invoke(
        app,
        ["sync", "--as-of", DAY, "--financials"],
        env=_env(local_tmp) | {"ASTOCK_CSV_ROOT": str(local_tmp / "raw")},
    )

    assert result.exit_code == 1
    assert "not usable" in result.output


def test_sync_financials_needs_a_symbol_list(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import astock_lens.cli.app as cli_module

    class NoListingProvider(StubProvider):
        def fetch(self, request: FetchRequest) -> RawDataset:
            self.requests.append(request)
            return RawDataset(
                provider="stub",
                dataset=request.dataset,
                fetched_at=datetime(2026, 9, 4, 15, 5, tzinfo=UTC),
                provider_version="v1",
                status=DataStatus.NULL,
                row_count=0,
            )

    monkeypatch.setattr(cli_module, "_bulk_provider", NoListingProvider)
    monkeypatch.setattr(
        cli_module, "_financial_provider", lambda: StubFinancialProvider()
    )

    result = CliRunner().invoke(
        app,
        ["sync", "--as-of", DAY, "--financials"],
        env=_env(local_tmp) | {"ASTOCK_CSV_ROOT": str(local_tmp / "raw")},
    )

    assert result.exit_code == 1
    assert "no symbols" in result.output


def test_statements_only_skips_the_daily_bar_fetch(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The quarterly whole-market refresh must not re-fetch 5000 bar series.

    The listing still decides the symbols, so it is read from disk rather than
    fetched: the run touches the market only for the statements.
    """
    import astock_lens.cli.app as cli_module

    raw_root = local_tmp / "raw"
    raw_root.mkdir()
    (raw_root / "securities.csv").write_text(
        "symbol,name,exchange,list_date\n600519.SH,Moutai,SSE,2001-08-27\n",
        encoding="utf-8",
    )
    bulk = StubProvider()
    financial = StubFinancialProvider()
    monkeypatch.setattr(cli_module, "_bulk_provider", lambda: bulk)
    monkeypatch.setattr(cli_module, "_financial_provider", lambda: financial)

    result = CliRunner().invoke(
        app,
        ["sync", "--as-of", DAY, "--statements-only"],
        env=_env(local_tmp) | {"ASTOCK_CSV_ROOT": str(raw_root)},
    )

    assert result.exit_code == 0, result.output
    assert bulk.requests == []  # no listing fetch, no bar fetch
    assert (raw_root / "financial_income.csv").is_file()
    assert not (raw_root / "daily_bars.csv").exists()


def test_sync_lands_valuation_for_the_named_symbols(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """估值落地一天一个文件；这一步让 Value / GARP 在真实运行里有证据可用。"""
    import astock_lens.cli.app as cli_module
    from astock_lens.data.contracts import (
        FetchRequest,
        ProviderHealth,
        RawDataset,
        RawPayload,
    )

    class StubNeodata:
        def health(self) -> ProviderHealth:
            return ProviderHealth(
                provider="neodata",
                healthy=True,
                status=DataStatus.VALUE,
                checked_at=datetime(2026, 9, 4, 15, 5, tzinfo=UTC),
            )

        def fetch(self, request: FetchRequest) -> RawDataset:
            rows = (
                (
                    "统一估值查询",
                    "统一估值查询",
                    "**标的代码（统一输出字段名）**: 600519.SH",
                ),
            )
            return RawDataset(
                provider="neodata",
                dataset=request.dataset,
                fetched_at=datetime(2026, 9, 4, 15, 5, tzinfo=UTC),
                provider_version="v1",
                status=DataStatus.VALUE,
                row_count=len(rows),
                payload=RawPayload(columns=("type", "desc", "content"), rows=rows),
            )

    raw_root = local_tmp / "raw"
    monkeypatch.setattr(cli_module, "_neodata_provider", StubNeodata)
    # 名单与日线走桩：这个测试只关心估值落地，不该真的去抓全市场名单。
    monkeypatch.setattr(cli_module, "_bulk_provider", StubProvider)

    result = CliRunner().invoke(
        app,
        ["sync", "--as-of", DAY, "--valuation", "--symbol", "600519.SH"],
        env=_env(local_tmp) | {"ASTOCK_CSV_ROOT": str(raw_root)},
    )

    assert result.exit_code == 0, result.output
    landed = raw_root / "neodata" / "valuation" / "2026-09-04.csv"
    assert landed.is_file()
    assert "valuation" in result.stdout


def test_sync_valuation_refuses_to_guess_a_symbol_list(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """neodata 不做标的枚举，且估值批量覆盖极低，因此不拿整份名单硬跑。"""
    result = _invoke(local_tmp, "sync", "--as-of", DAY, "--valuation")

    assert result.exit_code == 1
    assert "需要 --symbol" in result.output


# --- research --------------------------------------------------------------


def test_research_refuses_when_no_adapter_is_configured(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "research", "600519.SH")

    assert result.exit_code == 1
    assert "ASTOCK_DEEP_RESEARCH_CMD" in result.output


def test_research_submits_a_request_built_from_the_watchlist(
    local_tmp: Path,
) -> None:
    _invoke(
        local_tmp, "watch", "600519.SH", "--thesis", "brand moat", dataset=SHORT_DATASET
    )

    result = _invoke(
        local_tmp,
        "research",
        "600519.SH",
        ASTOCK_DEEP_RESEARCH_CMD=RESEARCH_RESPONDER,
    )

    assert result.exit_code == 0, result.output
    assert "job-brand moat" in result.stdout


def test_research_polls_a_job_status(local_tmp: Path) -> None:
    responder = shlex.join(
        [
            sys.executable,
            "-c",
            (
                "import json,sys;"
                "payload=json.load(sys.stdin);"
                "print(json.dumps({'job_id': payload['job_id'],"
                " 'state': 'InProgress',"
                " 'observed_at': '2026-09-04T15:06:00+00:00'}))"
            ),
        ]
    )

    result = _invoke(
        local_tmp,
        "research",
        "--status",
        "job-1",
        ASTOCK_DEEP_RESEARCH_CMD=responder,
    )

    assert result.exit_code == 0, result.output
    assert "InProgress" in result.stdout


def test_research_reports_a_failing_command(local_tmp: Path) -> None:
    failing = shlex.join(
        [sys.executable, "-c", "import sys; sys.stderr.write('no token'); sys.exit(2)"]
    )

    result = _invoke(
        local_tmp,
        "research",
        "600519.SH",
        ASTOCK_DEEP_RESEARCH_CMD=failing,
    )

    assert result.exit_code == 1
    assert "no token" in result.output


# --- doctor ----------------------------------------------------------------


def test_doctor_reports_dataset_freshness(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "doctor", dataset=SHORT_DATASET)

    assert result.exit_code == 0, result.output
    assert "daily_bars" in result.stdout
    assert "2026-09-04" in result.stdout


def test_doctor_reports_the_provider_it_would_use_for_bulk_data() -> None:
    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "akshare" in result.stdout.lower()


def test_doctor_reports_the_financial_statement_provider(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The WeStock CLI is an external command, so doctor must say where it is."""
    import astock_lens.data.providers.westock as westock_module

    binary = local_tmp / "westock"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("ASTOCK_WESTOCK_BIN", str(binary))

    configured = CliRunner().invoke(app, ["doctor"])

    assert configured.exit_code == 0, configured.output
    assert "westock-cli [ok]" in configured.stdout

    monkeypatch.delenv("ASTOCK_WESTOCK_BIN")
    # 没有环境变量时 provider 用仓库内的默认路径 `tools/bin/westock`：本机装好
    # 二进制后那个文件就存在，doctor 会如实报 [ok]。因此这里把默认路径显式指到
    # 一个不存在的文件，才能断言"找不到二进制"这条分支——否则这条断言实际测的
    # 是开发机有没有装二进制，而不是 provider 的行为。
    monkeypatch.setattr(
        westock_module, "DEFAULT_BINARY", local_tmp / "absent" / "westock"
    )
    missing = CliRunner().invoke(app, ["doctor"])

    assert missing.exit_code == 0, missing.output
    assert "westock-cli [unavailable]" in missing.stdout
    assert "ASTOCK_WESTOCK_BIN" in missing.stdout


def test_doctor_reports_the_semantic_source_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """neodata 的凭证 12 小时过期，doctor 必须让它一眼可见。"""
    monkeypatch.setenv("ASTOCK_NEODATA_TOKEN", "dummy")

    configured = CliRunner().invoke(app, ["doctor"])

    assert configured.exit_code == 0, configured.output
    assert "neodata [ok]" in configured.stdout

    monkeypatch.delenv("ASTOCK_NEODATA_TOKEN")
    monkeypatch.setattr(
        "astock_lens.data.providers.neodata.token_candidates", lambda: ()
    )
    missing = CliRunner().invoke(app, ["doctor"])

    assert missing.exit_code == 0, missing.output
    assert "neodata [unavailable]" in missing.stdout
    assert "凭证" in missing.stdout


def test_the_watchlist_root_can_be_pointed_elsewhere(local_tmp: Path) -> None:
    """No test writes to the repository's real watchlist directory."""
    _invoke(local_tmp, "watch", "600519.SH", dataset=SHORT_DATASET)

    assert not (ROOT / "data" / "watchlist" / "600519.SH.json").exists()
    payload = json.loads(
        (local_tmp / "watchlist" / "600519.SH.json").read_text(encoding="utf-8")
    )
    assert payload["symbol"] == "600519.SH"
