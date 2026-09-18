"""AkShare-backed provider.

Endpoint choice (2026-09-16, proven live and recorded in the slice ledger):
this environment's proxy drops Python clients talking to eastmoney's
``push2*`` domains — requests, urllib3, and curl_cffi all fail where curl
succeeds — so akshare's eastmoney-domain daily interface is unusable here.
Daily bars come from akshare's Tencent-domain interface
(``stock_zh_a_hist_tx``), whose response carries amount in yuan and turnover,
the fields the liquidity factor needs. The listing lists come from the three
exchange domains, which are reachable; SH needs both the main board and the
STAR market, or every 688-prefixed symbol would silently vanish from the
universe.

The mapping from source columns onto the canonical raw columns is code and
carries no threshold, so the same normalizer consumes this provider and the
local CSV provider. Raw cells stay verbatim strings; type conversion and unit
decisions belong downstream. The source's turnover is a ratio (``0.0078`` =
0.78%) and its volume counts lots of 100 shares — both are preserved as
delivered, never converted here.

Failure modes, kept apart on purpose:

- a **caller** problem (no symbols on a per-symbol interface, an unknown
  exchange suffix, an unknown dataset) raises ``ValueError``;
- a **source** problem (network failure, empty response, unexpected columns)
  becomes ``RawDataset.status = SOURCE_ERROR`` with a row count matching
  reality — never a row of zeros, never a fabricated substitute;
- a **missing extra** (akshare not installed) raises a message naming the
  install command, because an uninstalled library must not read like a market
  outage.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Final

from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.domain.enums import DataStatus

if TYPE_CHECKING:
    Frame = tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]
    Transport = Callable[[str, Mapping[str, str]], "Frame"]

BAR_ENDPOINT = "stock_zh_a_hist_tx"

# Source column → canonical raw column. Everything the source carries is
# mapped; what it does not carry (pre_close, pct_change, adj_factor) is simply
# absent from the emitted columns, and the normalizer reads absent as missing.
BAR_COLUMN_MAP: Mapping[str, str] = {
    "date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
    "turnover": "turnover_rate",
}
BAR_EMIT_COLUMNS: tuple[str, ...] = (
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

# The listing each endpoint serves, the exchange it proves, and the columns it
# uses. The exchange comes from the endpoint that served the row — never
# inferred from the code prefix.
SECURITY_LISTS: tuple[tuple[str, dict[str, str], str, Mapping[str, str]], ...] = (
    (
        "stock_info_sh_name_code",
        {"symbol": "主板A股"},
        "SSE",
        {"证券代码": "symbol", "证券简称": "name", "上市日期": "list_date"},
    ),
    (
        "stock_info_sh_name_code",
        {"symbol": "科创板"},
        "SSE",
        {"证券代码": "symbol", "证券简称": "name", "上市日期": "list_date"},
    ),
    (
        "stock_info_sz_name_code",
        {"symbol": "A股列表"},
        "SZSE",
        {"A股代码": "symbol", "A股简称": "name", "A股上市日期": "list_date"},
    ),
    (
        "stock_info_bj_name_code",
        {},
        "BSE",
        {"证券代码": "symbol", "证券简称": "name", "上市日期": "list_date"},
    ),
)
SECURITY_EMIT_COLUMNS: tuple[str, ...] = (
    "symbol",
    "name",
    "exchange",
    "list_date",
    "is_st",
    "is_delisting_board",
    "suspended_trading_days",
)

# The exchange marks ST by putting ST/*ST in the short name; the substring
# check *is* the designation, not an inference about it.
_ST_MARK = "ST"

_TENCENT_PREFIX = {"SH": "sh", "SZ": "sz", "BJ": "bj"}

# The exchange identity a row carries (SSE/SZSE/BSE, matching
# `configs/universe.yaml`) and the suffix the canonical symbol carries
# (600000.SH) are two vocabularies; this maps one onto the other.
SYMBOL_SUFFIX = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}

# Ranges the source accepts when the caller sets none: its own defaults, so a
# caller that asks for no restriction gets no restriction.
_UNBOUNDED_START = date(1900, 1, 1)
_UNBOUNDED_END = date(2050, 12, 31)

_MISSING_EXTRA = (
    "akshare is not installed; run `uv sync --extra providers` to use AkShareProvider"
)

# AkShare endpoint 函数未通过本 Provider 暴露可控的连接/读取超时或取消句柄。
# fallback scheduler 必须将 live 调用置于可单独终止的工作进程；线程/Future 等待
# 仅是调用方 deadline，不能停止底层 I/O。
AKSHARE_FALLBACK_REQUIRES_PROCESS_ISOLATION: Final = (
    "AKSHARE_FALLBACK_REQUIRES_PROCESS_ISOLATION"
)


class _SourceError(Exception):
    """A source problem: network, emptiness, or an unexpected column set."""


class _MissingExtra(RuntimeError):
    """The optional akshare package is absent; never masked as a data status."""


def _live_transport(endpoint: str, params: Mapping[str, str]) -> "Frame":
    """调用 AkShare 并转为字符串帧，不宣称具备 I/O 取消能力。

    endpoint callable 自行持有网络栈，在此既未暴露 timeout 也未暴露取消句柄。
    因而 live fallback 必须置于可终止进程边界，要求由
    ``AKSHARE_FALLBACK_REQUIRES_PROCESS_ISOLATION`` 声明。
    """
    try:
        # 用动态导入而不是 `import akshare` + ignore：本机装了 akshare、轻量环境没装，
        # 静态 ignore 在其中一个环境里必然被判 "unused ignore"，两种环境不能共用一条注释。
        # ModuleNotFoundError 是 ImportError 的子类，缺失 extra 的报错路径不变。
        import importlib

        akshare = importlib.import_module("akshare")
    except ImportError as error:
        raise _MissingExtra(_MISSING_EXTRA) from error
    frame = getattr(akshare, endpoint)(**dict(params))
    columns = tuple(str(column) for column in frame.columns)
    rows = tuple(
        tuple(_cell(value) for value in row)
        for row in frame.itertuples(index=False, name=None)
    )
    return columns, rows


def _cell(value: object) -> str:
    """Render one cell, keeping every missing shape as an empty string.

    Matches what the recorded fixtures store, so the live path and the replay
    path cannot drift apart.
    """
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value)
    return "" if text in {"<NA>", "NaT"} else text


class AkShareProvider:
    """Serve ``daily_bars`` and ``securities`` through akshare.

    The transport is injectable so the contract test can replay recorded
    responses; production uses ``_live_transport``.
    """

    def __init__(
        self,
        *,
        provider: str = "akshare",
        version: str = "unversioned",
        transport: "Transport | None" = None,
    ) -> None:
        self._provider = provider
        self._version = version
        self._transport: Transport = (
            transport if transport is not None else _live_transport
        )

    @property
    def fallback_execution_requirement(self) -> str:
        """返回 live AkShare fallback 强制使用的执行边界。

        此声明特意与 scheduler deadline 分离：调用方必须把 active transport
        放进可终止的工作进程，因为等待线程不能终止 source call。
        """
        return AKSHARE_FALLBACK_REQUIRES_PROCESS_ISOLATION

    def health(self) -> ProviderHealth:
        """Report importability. Network liveness is only proven by a fetch."""
        checked_at = datetime.now(UTC)
        try:
            import importlib

            akshare = importlib.import_module("akshare")
        except ImportError:
            return ProviderHealth(
                provider=self._provider,
                healthy=False,
                status=DataStatus.SOURCE_ERROR,
                checked_at=checked_at,
                message=_MISSING_EXTRA,
            )
        return ProviderHealth(
            provider=self._provider,
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=checked_at,
            message=(
                f"akshare {getattr(akshare, '__version__', 'unknown')} importable; "
                "liveness is only proven by a fetch"
            ),
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        """Fetch one dataset, raising for caller problems only."""
        if request.dataset not in {"daily_bars", "securities"}:
            raise ValueError(
                f"unknown dataset {request.dataset!r}; this provider serves "
                "'daily_bars' and 'securities'"
            )
        # Caller validations happen before any source call so they can never
        # be mistaken for a data problem.
        codes: list[str] = []
        if request.dataset == "daily_bars":
            if request.symbols is None:
                raise ValueError(
                    "dataset 'daily_bars' requires explicit symbols: the "
                    "daily interface is per-symbol, and choosing the whole "
                    "market is a caller decision"
                )
            codes = [_tencent_code(symbol) for symbol in request.symbols]

        fetched_at = datetime.now(UTC)
        try:
            if request.dataset == "daily_bars":
                return self._fetch_bars(request, codes, fetched_at)
            return self._fetch_securities(request, fetched_at)
        except _MissingExtra:
            raise
        except Exception:  # noqa: BLE001 — any source failure is a data status
            return self._empty(request, fetched_at)

    def _empty(self, request: FetchRequest, fetched_at: datetime) -> RawDataset:
        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=DataStatus.SOURCE_ERROR,
            row_count=0,
        )

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date | None,
        end_date: date | None,
    ) -> RawDataset:
        """Fetch one symbol's bars, reporting a source problem as a status.

        The batch interface (`fetch`) fails the whole dataset when any symbol
        fails, which is the right answer for a single-date sync but useless for
        a whole-market cold start. This primitive answers for one symbol, so a
        chunked caller can keep the symbols that succeeded. A caller mistake
        still raises; only a source problem becomes a status.
        """
        code = _tencent_code(symbol)
        fetched_at = datetime.now(UTC)
        params = {
            "symbol": code,
            "start_date": (start_date or _UNBOUNDED_START).strftime("%Y%m%d"),
            "end_date": (end_date or _UNBOUNDED_END).strftime("%Y%m%d"),
            "adjust": "",
        }
        try:
            columns, source_rows = self._transport(BAR_ENDPOINT, params)
            index = _require_columns(columns, set(BAR_COLUMN_MAP), BAR_ENDPOINT)
        except _MissingExtra:
            raise
        except Exception as error:  # noqa: BLE001 — a source failure is a status
            return RawDataset(
                provider=self._provider,
                dataset="daily_bars",
                fetched_at=fetched_at,
                provider_version=self._version,
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
                message=f"{BAR_ENDPOINT} failed for {symbol!r}: {error}",
            )

        if not source_rows:
            return RawDataset(
                provider=self._provider,
                dataset="daily_bars",
                fetched_at=fetched_at,
                provider_version=self._version,
                status=DataStatus.SOURCE_ERROR,
                row_count=0,
                message=f"{BAR_ENDPOINT} returned no rows for {code!r}",
            )

        rows: list[tuple[str, ...]] = []
        for row in source_rows:
            values = {source: row[position] for source, position in index.items()}
            rows.append(
                (
                    symbol,
                    values["date"],
                    values["open"],
                    values["high"],
                    values["low"],
                    values["close"],
                    values["volume"],
                    values["amount"],
                    values["turnover"],
                )
            )
        return RawDataset(
            provider=self._provider,
            dataset="daily_bars",
            fetched_at=fetched_at,
            provider_version=self._version,
            status=DataStatus.VALUE,
            row_count=len(rows),
            trade_date=_single_date(rows, position=1),
            payload=RawPayload(columns=BAR_EMIT_COLUMNS, rows=tuple(rows)),
        )

    def _fetch_bars(
        self,
        request: FetchRequest,
        codes: Sequence[str],
        fetched_at: datetime,
    ) -> RawDataset:
        """One source call per symbol; any failure fails the whole dataset."""
        assert request.symbols is not None  # validated in `fetch`
        rows: list[tuple[str, ...]] = []

        for canonical in request.symbols:
            dataset = self.fetch_symbol_bars(
                canonical,
                as_of=request.as_of,
                start_date=request.start_date,
                end_date=request.end_date,
            )
            payload = dataset.payload
            if dataset.status is not DataStatus.VALUE or payload is None:
                # The batch contract is unchanged: one bad symbol still fails
                # the dataset. `fetch_symbol_bars` is where the single-symbol
                # verdict lives, so the chunked bootstrap can call it directly
                # and keep the other symbols' work.
                raise _SourceError(
                    dataset.message
                    or f"{BAR_ENDPOINT} returned no rows for {canonical!r}"
                )
            rows.extend(payload.rows)

        trade_date = _single_date(rows, position=1)
        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=DataStatus.VALUE,
            row_count=len(rows),
            trade_date=trade_date,
            payload=RawPayload(columns=BAR_EMIT_COLUMNS, rows=tuple(rows)),
        )

    def _fetch_securities(
        self, request: FetchRequest, fetched_at: datetime
    ) -> RawDataset:
        """Concatenate the exchange lists; identity is a snapshot, not a
        series, so a caller's date range is not forwarded to the source."""
        rows: list[tuple[str, ...]] = []

        for endpoint, params, exchange, column_map in SECURITY_LISTS:
            columns, source_rows = self._transport(endpoint, params)
            index = _require_columns(columns, set(column_map), endpoint)

            if not source_rows:
                raise _SourceError(f"{endpoint} returned no rows for {exchange}")

            target_of: dict[str, str] = {}
            for source, target in column_map.items():
                target_of[target] = source
            code_column, name_column, listed_column = (
                target_of["symbol"],
                target_of["name"],
                target_of["list_date"],
            )

            for row in source_rows:
                code = row[index[code_column]]
                name = row[index[name_column]]
                listed = row[index[listed_column]]
                rows.append(
                    (
                        f"{code}.{SYMBOL_SUFFIX[exchange]}",
                        name,
                        exchange,
                        listed,
                        "true" if _ST_MARK in name else "false",
                        # These lists enumerate currently listed exchange
                        # shares; delisting-arrangement names are served by
                        # separate lists this provider does not call.
                        "false",
                        # No list reports suspension: absent, never zero.
                        "",
                    )
                )

        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=SECURITY_EMIT_COLUMNS, rows=tuple(rows)),
        )


def _tencent_code(canonical: str) -> str:
    """Turn ``000001.SZ`` into the per-symbol code the source expects."""
    code, _, suffix = canonical.partition(".")
    prefix = _TENCENT_PREFIX.get(suffix)
    if prefix is None or not code.isdigit():
        raise ValueError(
            f"symbol {canonical!r} has no exchange suffix this provider "
            f"knows ({sorted(_TENCENT_PREFIX)})"
        )
    return f"{prefix}{code}"


def _require_columns(
    columns: tuple[str, ...],
    required: set[str],
    endpoint: str,
) -> dict[str, int]:
    """Index the required source columns; an unexpected set is a source error."""
    missing = sorted(required - set(columns))
    if missing:
        raise _SourceError(
            f"{endpoint} response is missing columns {missing}; "
            f"it declares {list(columns)}"
        )
    return {name: columns.index(name) for name in required}


def _single_date(rows: Sequence[tuple[str, ...]], *, position: int) -> date | None:
    """The column's date when every row agrees, else `None` — never a guess."""
    values = {row[position] for row in rows}
    if len(values) != 1:
        return None
    try:
        return date.fromisoformat(next(iter(values)))
    except ValueError:
        return None
