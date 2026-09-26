"""批量获取 WeStock 日线并映射到现有 Raw 行情契约。"""

import os
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.data.markdown import MalformedTable, Table, parse_tables
from astock_lens.data.providers.westock import (
    BINARY_ENV,
    DEFAULT_BINARY,
    CommandResult,
    to_westock_code,
)
from astock_lens.domain.enums import DataStatus

BAR_EMIT_COLUMNS = (
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
DEFAULT_BATCH_SIZE = 100
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_ATTEMPTS = 2

Runner = Callable[[Sequence[str]], CommandResult]
ProgressCallback = Callable[[int, int, int], None]


class WestockBarsProvider:
    """用 WeStock kline 与 quote 批量获取单日 A 股日线。"""

    def __init__(
        self,
        binary: Path | str | None = None,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        attempts: int = DEFAULT_ATTEMPTS,
        runner: Runner | None = None,
        progress_callback: ProgressCallback | None = None,
        provider: str = "westock-bars",
        version: str = "v1",
    ) -> None:
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        if attempts <= 0:
            raise ValueError(f"attempts must be positive, got {attempts}")
        configured = binary if binary is not None else os.getenv(BINARY_ENV)
        self._binary = Path(configured) if configured else DEFAULT_BINARY
        self._batch_size = batch_size
        self._timeout = timeout
        self._attempts = attempts
        self._runner = runner if runner is not None else self._run
        self._progress_callback = progress_callback
        self._provider = provider
        self._version = version

    def health(self) -> ProviderHealth:
        checked_at = datetime.now(UTC)
        if not self._binary.is_file():
            return ProviderHealth(
                provider=self._provider,
                healthy=False,
                status=DataStatus.SOURCE_ERROR,
                checked_at=checked_at,
                message=(
                    f"WeStock CLI not found at {self._binary}; install it or "
                    f"point {BINARY_ENV} at the binary"
                ),
            )
        if not os.access(self._binary, os.X_OK):
            return ProviderHealth(
                provider=self._provider,
                healthy=False,
                status=DataStatus.SOURCE_ERROR,
                checked_at=checked_at,
                message=f"{self._binary} is not executable",
            )
        return ProviderHealth(
            provider=self._provider,
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=checked_at,
            message="binary is present; liveness is only proven by a fetch",
        )

    def fetch(
        self,
        request: FetchRequest,
        *,
        prior_landed: int = 0,
    ) -> RawDataset:
        if request.dataset != "daily_bars":
            raise ValueError("WestockBarsProvider only serves 'daily_bars'")
        if request.symbols is None:
            raise ValueError("daily_bars requires an explicit symbol list")
        if not request.symbols:
            raise ValueError("daily_bars got an empty symbol list")

        symbols = tuple(dict.fromkeys(request.symbols))
        codes = {symbol: to_westock_code(symbol) for symbol in symbols}
        fetched_at = datetime.now(UTC)
        emitted: list[tuple[str, ...]] = []
        failed: list[str] = []
        returned: set[str] = set()
        processed = 0
        day = request.as_of.date().isoformat()
        # 累计口径：加上 prior_landed 后，分母=全 listing，分子=已 fetch 累计
        cumulative_total = len(symbols) + prior_landed

        def report_progress(batch_symbols: tuple[str, ...]) -> None:
            nonlocal processed
            processed += len(batch_symbols)
            if self._progress_callback is not None:
                self._progress_callback(
                    processed + prior_landed,
                    cumulative_total,
                    len(returned) + prior_landed,
                )

        for batch_number, batch_symbols in enumerate(
            _chunks(symbols, self._batch_size), start=1
        ):
            batch_codes = tuple(codes[symbol] for symbol in batch_symbols)
            kline_tables, kline_error = self._fetch_tables("kline", batch_codes, day)
            if kline_error is not None:
                failed.append(f"kline batch {batch_number}: {kline_error}")
                report_progress(batch_symbols)
                if "LOCAL_RATE_LIMITED" in kline_error:
                    failed.append("stopped remaining batches after rate limiting")
                    break
                continue

            quote_tables, quote_error = self._fetch_tables("quote", batch_codes, day)
            if quote_error is not None:
                failed.append(f"quote batch {batch_number}: {quote_error}")
                report_progress(batch_symbols)
                if "LOCAL_RATE_LIMITED" in quote_error:
                    failed.append("stopped remaining batches after rate limiting")
                    break
                continue

            kline_rows, kline_duplicates = _rows_by_code(kline_tables)
            quote_rows, quote_duplicates = _rows_by_code(quote_tables)
            for symbol, code in zip(batch_symbols, batch_codes, strict=True):
                if code in kline_duplicates or code in quote_duplicates:
                    failed.append(f"ambiguous duplicate response for {code}")
                    continue
                kline = kline_rows.get(code)
                quote = quote_rows.get(code)
                if kline is None or quote is None:
                    continue
                if kline["date"] != day or quote["time"][:10] != day:
                    continue
                try:
                    volume = _scaled(kline["volume"], Decimal(100))
                    turnover_rate = _scaled(quote["turnover_rate"], Decimal("0.01"))
                except InvalidOperation:
                    failed.append(f"invalid volume or turnover_rate for {code}")
                    continue
                emitted.append(
                    (
                        symbol,
                        day,
                        kline["open"],
                        kline["high"],
                        kline["low"],
                        quote["price"],
                        volume,
                        quote["amount"],
                        turnover_rate,
                    )
                )
                returned.add(symbol)
            report_progress(batch_symbols)

        missing = tuple(symbol for symbol in symbols if symbol not in returned)
        status = (
            DataStatus.VALUE
            if emitted
            else DataStatus.SOURCE_ERROR
            if failed
            else DataStatus.NULL
        )
        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=status,
            row_count=len(emitted),
            missing_symbols=missing,
            message="; ".join(failed) or None,
            trade_date=request.as_of.date() if emitted else None,
            payload=(
                RawPayload(columns=BAR_EMIT_COLUMNS, rows=tuple(emitted))
                if emitted
                else None
            ),
        )

    def _fetch_tables(
        self, command: str, codes: tuple[str, ...], day: str
    ) -> tuple[tuple[Table, ...], str | None]:
        argv = [str(self._binary), command, ",".join(codes)]
        if command == "kline":
            argv.extend(
                ("--period", "day", "--start", day, "--end", day, "--fq", "nofq")
            )
            required = {"code", "date", "open", "high", "low", "last", "volume"}
        else:
            argv.extend(("--date", day))
            required = {"code", "time", "price", "amount", "turnover_rate"}

        result: CommandResult | None = None
        for _ in range(self._attempts):
            try:
                result = self._runner(argv)
            except OSError as error:
                result = CommandResult(returncode=-1, stdout="", stderr=str(error))
            if result.returncode == 0 and "LOCAL_RATE_LIMITED" not in result.stdout:
                break
        if result is None:
            return (), "command runner produced no result"
        if result.returncode != 0 or "LOCAL_RATE_LIMITED" in result.stdout:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown failure"
            return (), f"{detail[:240]}"

        try:
            tables = parse_tables(result.stdout)
        except MalformedTable as error:
            return (), f"malformed table: {error}"
        if not tables:
            if "数据为空" in result.stdout:
                return (), None
            return (), "successful command returned no data table"
        if any(not required.issubset(table.columns) for table in tables):
            return (), f"response table is missing required columns for {command}"
        return tables, None

    def _run(self, argv: Sequence[str]) -> CommandResult:
        try:
            result = subprocess.run(
                list(argv),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                returncode=-1,
                stdout="",
                stderr=f"timed out after {self._timeout}s",
            )
        except OSError as error:
            return CommandResult(returncode=-1, stdout="", stderr=str(error))
        return CommandResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def _chunks(symbols: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(
        symbols[start : start + size] for start in range(0, len(symbols), size)
    )


def _rows_by_code(
    tables: tuple[Table, ...],
) -> tuple[dict[str, dict[str, str]], frozenset[str]]:
    rows: dict[str, dict[str, str]] = {}
    duplicates: set[str] = set()
    for table in tables:
        for row in table.rows:
            mapped = dict(zip(table.columns, row, strict=True))
            code = mapped["code"].lower()
            if code in rows:
                duplicates.add(code)
            rows[code] = mapped
    return rows, frozenset(duplicates)


def _scaled(value: str, multiplier: Decimal) -> str:
    number = Decimal(value)
    if not number.is_finite():
        raise InvalidOperation
    return format(number * multiplier, "f")
