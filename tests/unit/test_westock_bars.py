"""WeStock bar mapping and failure semantics against recorded CLI responses."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest
from astock_lens.data.providers.westock import CommandResult
from astock_lens.domain.enums import DataStatus

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "westock"
AS_OF = datetime(2026, 9, 22, 15, 0, tzinfo=UTC)


class ReplayRunner:
    def __init__(self, *, kline: str, quote: str) -> None:
        self.responses = {"kline": kline, "quote": quote}
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        call = list(argv)
        self.calls.append(call)
        return CommandResult(returncode=0, stdout=self.responses[call[1]], stderr="")


def _recording(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _bars_provider(runner: ReplayRunner):
    from astock_lens.data.providers.westock_bars import WestockBarsProvider

    return WestockBarsProvider(binary="/opt/westock", runner=runner)


def test_merges_recorded_data_using_the_existing_akshare_units() -> None:
    runner = ReplayRunner(
        kline=_recording("kline_sh600519_sz000001_sz300750_2026-09-22.md"),
        quote=_recording("quote_sh600519_sz000001_sz300750_2026-09-22.md"),
    )

    result = _bars_provider(runner).fetch(
        FetchRequest(
            dataset="daily_bars",
            as_of=AS_OF,
            symbols=("600519.SH", "000001.SZ", "300750.SZ"),
        )
    )

    assert result.status is DataStatus.VALUE
    assert result.missing_symbols == ()
    assert result.payload is not None
    assert result.payload.columns == (
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover_rate",
    )
    assert result.payload.rows[0] == (
        "600519.SH",
        "2026-09-22",
        "1252.15",
        "1265.88",
        "1248.1",
        "1253.8",
        "2457300",
        "3088526148",
        "0.002",
    )
    kline_call = next(call for call in runner.calls if call[1] == "kline")
    assert kline_call[kline_call.index("--fq") + 1] == "nofq"
    assert all(
        "--date" in call or ("--start" in call and "--end" in call)
        for call in runner.calls
    )


def test_provider_reports_progress_after_each_completed_batch() -> None:
    from astock_lens.data.providers.westock_bars import WestockBarsProvider

    runner = ReplayRunner(
        kline=_recording("kline_sh600519_sz000001_sz300750_2026-09-22.md"),
        quote=_recording("quote_sh600519_sz000001_sz300750_2026-09-22.md"),
    )
    progress: list[tuple[int, int, int]] = []

    result = WestockBarsProvider(
        binary="/opt/westock",
        batch_size=2,
        runner=runner,
        progress_callback=lambda processed, total, downloaded: progress.append(
            (processed, total, downloaded)
        ),
    ).fetch(
        FetchRequest(
            dataset="daily_bars",
            as_of=AS_OF,
            symbols=("600519.SH", "000001.SZ", "300750.SZ"),
        )
    )

    assert result.row_count == 3
    assert progress == [(2, 3, 2), (3, 3, 3)]


def test_default_batch_size_matches_requested_progress_granularity() -> None:
    from astock_lens.data.providers.westock_bars import DEFAULT_BATCH_SIZE

    assert DEFAULT_BATCH_SIZE == 100


def test_missing_data_from_either_source_is_reported_in_canonical_symbols() -> None:
    runner = ReplayRunner(
        kline=_recording("kline_mixed_valid_invalid_2026-09-22.md"),
        quote=_recording("quote_sh600519_sz000001_sz300750_2026-09-22.md"),
    )

    result = _bars_provider(runner).fetch(
        FetchRequest(
            dataset="daily_bars",
            as_of=AS_OF,
            symbols=("600519.SH", "999999.SH"),
        )
    )

    assert result.status is DataStatus.VALUE
    assert result.missing_symbols == ("999999.SH",)
    assert result.payload is not None
    assert tuple(row[0] for row in result.payload.rows) == ("600519.SH",)


def test_empty_success_is_null_and_names_all_missing_symbols() -> None:
    empty = _recording("kline_invalid_codes_2026-09-22.md")
    runner = ReplayRunner(kline=empty, quote=empty)

    result = _bars_provider(runner).fetch(
        FetchRequest(dataset="daily_bars", as_of=AS_OF, symbols=("999999.SH",))
    )

    assert result.status is DataStatus.NULL
    assert result.row_count == 0
    assert result.payload is None
    assert result.missing_symbols == ("999999.SH",)


def test_rate_limited_batch_is_source_error_without_fabricated_rows() -> None:
    limited = "LOCAL_RATE_LIMITED: try a smaller batch"
    runner = ReplayRunner(kline=limited, quote=limited)

    result = _bars_provider(runner).fetch(
        FetchRequest(dataset="daily_bars", as_of=AS_OF, symbols=("600519.SH",))
    )

    assert result.status is DataStatus.SOURCE_ERROR
    assert result.row_count == 0
    assert result.payload is None
    assert result.missing_symbols == ("600519.SH",)
    assert result.message is not None


def test_rate_limit_stops_later_batches_without_spending_more_requests() -> None:
    kline_response = _recording("kline_sh600519_sz000001_sz300750_2026-09-22.md")
    quote_response = _recording("quote_sh600519_sz000001_sz300750_2026-09-22.md")

    class RateLimitedSecondBatch:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def __call__(self, argv: Sequence[str]) -> CommandResult:
            call = list(argv)
            self.calls.append(call)
            if call[1] == "kline" and "000001" in call[2]:
                return CommandResult(
                    returncode=0,
                    stdout="LOCAL_RATE_LIMITED: try again later",
                    stderr="",
                )
            return CommandResult(
                returncode=0,
                stdout=kline_response if call[1] == "kline" else quote_response,
                stderr="",
            )

    runner = RateLimitedSecondBatch()
    from astock_lens.data.providers.westock_bars import WestockBarsProvider

    result = WestockBarsProvider(
        binary="/opt/westock", batch_size=1, runner=runner
    ).fetch(
        FetchRequest(
            dataset="daily_bars",
            as_of=AS_OF,
            symbols=("600519.SH", "000001.SZ", "300750.SZ"),
        )
    )

    assert result.row_count == 1
    assert result.missing_symbols == ("000001.SZ", "300750.SZ")
    assert result.message is not None
    assert "stopped remaining batches" in result.message
    assert [call[1] for call in runner.calls] == ["kline", "quote", "kline", "kline"]


def test_quote_from_a_different_date_is_not_landed() -> None:
    quote = _recording("quote_sh600519_sz000001_sz300750_2026-09-22.md")
    runner = ReplayRunner(
        kline=_recording("kline_sh600519_sz000001_sz300750_2026-09-22.md"),
        quote=quote.replace("2026-09-22", "2026-09-21"),
    )

    result = _bars_provider(runner).fetch(
        FetchRequest(dataset="daily_bars", as_of=AS_OF, symbols=("600519.SH",))
    )

    assert result.status is DataStatus.NULL
    assert result.missing_symbols == ("600519.SH",)
    assert result.payload is None


def test_bulk_provider_defaults_to_westock_and_keeps_akshare_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from astock_lens.cli.runtime import _bulk_provider
    from astock_lens.data.providers.akshare_provider import AkShareProvider
    from astock_lens.data.providers.westock_bars import WestockBarsProvider

    monkeypatch.delenv("ASTOCK_BULK_PROVIDER", raising=False)
    assert isinstance(_bulk_provider(), WestockBarsProvider)

    monkeypatch.setenv("ASTOCK_BULK_PROVIDER", "akshare")
    assert isinstance(_bulk_provider(), AkShareProvider)


def test_bulk_provider_logs_download_progress_to_the_console(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from astock_lens.cli import runtime

    options: dict[str, object] = {}

    def make_provider(**kwargs: object) -> object:
        options.update(kwargs)
        return object()

    monkeypatch.delenv("ASTOCK_BULK_PROVIDER", raising=False)
    monkeypatch.setattr(runtime, "WestockBarsProvider", make_provider)

    runtime._bulk_provider()
    progress_callback = options["progress_callback"]
    progress_callback(100, 5568, 97)

    output = capsys.readouterr().err
    assert "日线下载进度" in output
    assert "100/5568" in output
    assert "成功 97" in output
    assert "缺失 3" in output
    assert "待处理 5468" in output


def test_bulk_provider_rejects_an_unknown_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import typer

    from astock_lens.cli.runtime import _bulk_provider

    monkeypatch.setenv("ASTOCK_BULK_PROVIDER", "unknown")

    with pytest.raises(typer.BadParameter, match="ASTOCK_BULK_PROVIDER"):
        _bulk_provider()


def test_daily_sync_reads_cached_listing_and_fetches_bars_from_westock(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from astock_lens.cli import runtime
    from tests.unit.test_raw_sync import StubProvider

    (local_tmp / "securities.csv").write_text(
        "symbol,name,exchange,list_date\n600519.SH,Kweichow Moutai,SSE,2001-08-27\n",
        encoding="utf-8",
    )
    bars_provider = StubProvider()
    monkeypatch.setattr(runtime, "_csv_root", lambda: local_tmp)
    monkeypatch.setattr(runtime, "_bulk_provider", lambda: bars_provider)

    runtime._land(AS_OF)

    assert [request.dataset for request in bars_provider.requests] == ["daily_bars"]
    _, bar_rows = runtime.read_raw_rows(local_tmp / "daily_bars.csv")
    assert bar_rows[0][0] == "600519.SH"
