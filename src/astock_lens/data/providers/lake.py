"""数据湖日线 Provider（本地 Parquet）。

用途（2026-09-25 数据源替代切片）：把已经建好的 `a-share-data-lake_v1` 数据湖
接成系统的一个日线来源，替代"每次全市场扫描都去敲腾讯"的批量路径。动机不是
省一次调用，而是拆依赖——WeStock CLI、neodata、AkShare 日线的底层都是腾讯，
集中风险需要一条正交的本地通道。

它只做一件事：读本地 Parquet，按现有 Raw 契约吐出日线。**不碰名单**——数据湖
主档给不出归一层必填且非空的 `is_st / is_delisting_board`（ST 只有当前快照名，
不是 PIT），硬接就是把 ST 规则建立在猜值上，这条红线不越。名单仍走 AkShare。

单位与既有 Raw 字段一致（`docs/DATA_SOURCES.md` §6）：数据湖的 `volume` 就是
「股」、`amount` 就是「元」，与 WeStock 路径（kline 手 ×100 落 Raw）同口径，
所以这里不换算、不缩放，原样落到 Raw 单元格。归一化与单位判断永远是下游的事。

数据湖没有换手率列。换手率没有任何因子消费（流动性因子读的是 `amount`），
归一层会把缺失读成 `None`——因此这里留空字符串（= 缺失），绝不静默补 0。

三种"没取到"被刻意分开，且都如实报告：

- **调用方错误**（未知数据集、没给标的、给了空名单）抛 `ValueError`；
- **数据源问题**（Parquet 不存在、读失败、缺必要列）返回 `SOURCE_ERROR`，
  行数为 0、不落地任何伪造行；
- **覆盖缺口**（请求了、但那天/那段没有这只标的的行）如实进 `missing_symbols`，
  由 bootstrap 的逐标的补缺继续处理，而不是当作"批量已覆盖"。
"""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from astock_lens.data.bootstrap_sources import (
    BatchFetchResult,
    BootstrapBatchRequest,
)
from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.data.providers.westock_bars import BAR_EMIT_COLUMNS
from astock_lens.domain.enums import DataStatus

if TYPE_CHECKING:
    import pyarrow as pa  # type: ignore[import-untyped]

__all__ = ["BAR_PATH_ENV", "LakeProvider"]

# 数据湖合并日线 parquet 的位置。默认不猜：没配就是没接，health 如实报缺，
# 而不是悄悄指向某个可能不存在或已经过期的兄弟目录。
BAR_PATH_ENV = "ASTOCK_LAKE_DAILY_PATH"

# 数据湖日线里本 Provider 要读的列，以及它们在合并 parquet 中的名字。
_LAKE_CODE_COLUMN = "code"
_LAKE_DATE_COLUMN = "date"
_LAKE_VALUE_COLUMNS = ("open", "high", "low", "close", "volume", "amount")
_REQUIRED_LAKE_COLUMNS = (_LAKE_CODE_COLUMN, _LAKE_DATE_COLUMN, *_LAKE_VALUE_COLUMNS)


def _fmt(value: "float | None") -> str:
    """把一个浮点单元格转成不带科学计数法的十进制字符串。

    Raw 单元格必须是字符串，但归一化之前不能被格式器改写：NaN / None 一律留空
    （缺失），整数值去掉多余的 `.0`，其余用定点小数并剥掉尾随零。
    """
    if value is None:
        return ""
    # 不用 `value != value` 之外的 NaN 判法：float64 的 NaN 是唯一 self-unequal 的值。
    if value != value:  # noqa: PLR0124 - NaN 检测就是自反不等的语义
        return ""
    if float(value).is_integer() and abs(value) < 1e16:
        return str(int(value))
    text = format(float(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


class LakeProvider:
    """从本地数据湖 Parquet 读日线，既做单日批量、也做冷启动的批量补缺来源。"""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        provider: str = "lake",
        version: str = "v1",
    ) -> None:
        import os

        configured = path if path is not None else os.getenv(BAR_PATH_ENV)
        self._path = Path(configured) if configured else None
        self._provider = provider
        self._version = version

    def health(self) -> ProviderHealth:
        """只报告 Parquet 在不在，不读内容——`doctor` 保持只读与快速。"""
        checked_at = datetime.now(UTC)
        if self._path is None:
            return ProviderHealth(
                provider=self._provider,
                healthy=False,
                status=DataStatus.SOURCE_ERROR,
                checked_at=checked_at,
                message=f"未配置数据湖日线路径；请设置 {BAR_PATH_ENV} 或传入 path",
            )
        if not self._path.is_file():
            return ProviderHealth(
                provider=self._provider,
                healthy=False,
                status=DataStatus.SOURCE_ERROR,
                checked_at=checked_at,
                message=f"数据湖日线 Parquet 不存在：{self._path}",
            )
        return ProviderHealth(
            provider=self._provider,
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=checked_at,
            message=f"数据湖日线就绪：{self._path}；可用性由真实取数证明",
        )

    # --- 单日批量（对齐 sync / land_raw 的 daily_bars 契约） ----------------

    def fetch(
        self,
        request: FetchRequest,
        *,
        prior_landed: int = 0,
    ) -> RawDataset:
        """取 `as_of` 单日、给定标的的日线。已落地的跳过由调用方负责。"""
        del prior_landed  # 本地 Parquet 读没有逐标的进度回调
        if request.dataset != "daily_bars":
            raise ValueError(
                f"LakeProvider 只服务 'daily_bars'，收到 {request.dataset!r}"
            )
        if request.symbols is None:
            raise ValueError("daily_bars 需要显式给出标的名单")
        if not request.symbols:
            raise ValueError("daily_bars 收到空的标的名单")

        fetched_at = datetime.now(UTC)
        symbols = tuple(dict.fromkeys(request.symbols))
        day = request.as_of.date()
        rows, returned, error = self._scan(symbols, day, day)

        if error is not None:
            return self._emptied(
                request.dataset,
                fetched_at,
                DataStatus.SOURCE_ERROR,
                error,
                missing=symbols,
            )
        if not rows:
            return self._emptied(
                request.dataset,
                fetched_at,
                DataStatus.NULL,
                "数据湖在请求交易日没有任何标的的行",
                missing=symbols,
            )

        emitted = self._order(rows, symbols, returned)
        missing = tuple(symbol for symbol in symbols if symbol not in returned)
        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=DataStatus.VALUE,
            row_count=len(emitted),
            missing_symbols=missing,
            trade_date=day,
            payload=RawPayload(columns=BAR_EMIT_COLUMNS, rows=emitted),
        )

    # --- 批量补缺（解锁冷启动 / 研究池历史，替代 batch_source=None） ---------

    def fetch_recent_bars(self, request: BootstrapBatchRequest) -> BatchFetchResult:
        """一次返回整段时间窗口内的日线；按 `symbol` 列的归行由 bootstrap 负责。"""
        symbols = tuple(dict.fromkeys(request.symbols))
        rows, returned, error = self._scan(
            symbols, request.start_date, request.end_date
        )
        missing = tuple(symbol for symbol in symbols if symbol not in returned)
        fetched_at = datetime.now(UTC)

        if error is not None:
            dataset = self._emptied(
                "daily_bars",
                fetched_at,
                DataStatus.SOURCE_ERROR,
                error,
                missing=symbols,
            )
            return BatchFetchResult(
                datasets=(dataset,), missing_symbols=missing, source_name=self._provider
            )
        if not rows:
            dataset = self._emptied(
                "daily_bars",
                fetched_at,
                DataStatus.NULL,
                "数据湖在该窗口没有任何标的的行",
                missing=symbols,
            )
            return BatchFetchResult(
                datasets=(dataset,), missing_symbols=missing, source_name=self._provider
            )

        emitted = self._order(rows, symbols, returned)
        dataset = RawDataset(
            provider=self._provider,
            dataset="daily_bars",
            fetched_at=fetched_at,
            provider_version=self._version,
            status=DataStatus.VALUE,
            row_count=len(emitted),
            missing_symbols=missing,
            payload=RawPayload(columns=BAR_EMIT_COLUMNS, rows=emitted),
        )
        return BatchFetchResult(
            datasets=(dataset,), missing_symbols=missing, source_name=self._provider
        )

    # --- 逐标的补缺（让选到 lake 时整条 bootstrap 链路保持本地） -------------

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        """单只标的在窗口内的日线；数据湖没有它就返回 NULL，不伪造、不联网回退。"""
        del as_of  # 时间窗口由 start_date / end_date 决定
        fetched_at = datetime.now(UTC)
        rows, returned, error = self._scan((symbol,), start_date, end_date)

        if error is not None:
            return self._emptied(
                "daily_bars",
                fetched_at,
                DataStatus.SOURCE_ERROR,
                error,
                missing=(symbol,),
            )
        if not rows:
            return self._emptied(
                "daily_bars",
                fetched_at,
                DataStatus.NULL,
                "数据湖在该窗口没有该标的的行",
                missing=(symbol,),
            )
        emitted = self._order(rows, (symbol,), returned)
        return RawDataset(
            provider=self._provider,
            dataset="daily_bars",
            fetched_at=fetched_at,
            provider_version=self._version,
            status=DataStatus.VALUE,
            row_count=len(emitted),
            payload=RawPayload(columns=BAR_EMIT_COLUMNS, rows=emitted),
        )

    # --- 内部：读 Parquet --------------------------------------------------

    def _scan(
        self, symbols: tuple[str, ...], start_date: date, end_date: date
    ) -> tuple[dict[tuple[str, str], tuple[str, ...]], set[str], str | None]:
        """读请求标的在 [start, end] 内的行。

        返回 `(按 (symbol, trade_date) 归键的行, 出现过的标的集合, 错误)`。
        读失败或必要列缺失时第三项是原因字符串，调用方据此落 `SOURCE_ERROR`——
        Parquet 不存在绝不等于"这个市场没有行情"。
        """
        if self._path is None:
            return {}, set(), f"未配置数据湖日线路径（{BAR_PATH_ENV}）"
        if not self._path.is_file():
            return {}, set(), f"数据湖日线 Parquet 不存在：{self._path}"

        try:
            import pyarrow.dataset as ds  # type: ignore[import-untyped]
        except ImportError:  # pragma: no cover - 由 uv extra `data` 提供
            return {}, set(), "读取 Parquet 需要 pyarrow：uv sync --extra data"

        start = start_date.isoformat()
        end = end_date.isoformat()
        expression = (
            (ds.field(_LAKE_DATE_COLUMN) >= start)
            & (ds.field(_LAKE_DATE_COLUMN) <= end)
            & ds.field(_LAKE_CODE_COLUMN).isin(list(symbols))
        )
        try:
            dataset = ds.dataset(self._path, format="parquet")
            columns = set(dataset.schema.names)
            missing_columns = [
                name for name in _REQUIRED_LAKE_COLUMNS if name not in columns
            ]
            if missing_columns:
                return {}, set(), f"数据湖日线缺少必要列：{missing_columns}"
            table = dataset.to_table(
                columns=list(_REQUIRED_LAKE_COLUMNS), filter=expression
            )
        except Exception as error:  # noqa: BLE001 - 本地 IO + 引擎异常种类繁多，一律当数据源问题
            return {}, set(), f"读取数据湖日线失败：{error}"

        return self._rows_from_table(table)

    @staticmethod
    def _rows_from_table(
        table: "pa.Table",
    ) -> tuple[dict[tuple[str, str], tuple[str, ...]], set[str], str | None]:
        """把过滤后的表转成 Raw 行（全部单元格是字符串），同日同标的去重取最后一条。"""
        codes = table[_LAKE_CODE_COLUMN].to_pylist()
        days = table[_LAKE_DATE_COLUMN].to_pylist()
        values = {name: table[name].to_pylist() for name in _LAKE_VALUE_COLUMNS}

        rows: dict[tuple[str, str], tuple[str, ...]] = {}
        returned: set[str] = set()
        for position, code in enumerate(codes):
            symbol = str(code)
            trade_date = str(days[position])
            # 输出顺序严格对齐 BAR_EMIT_COLUMNS：
            # symbol, trade_date, open, high, low, close, volume, amount, turnover_rate
            row = (
                symbol,
                trade_date,
                _fmt(values["open"][position]),
                _fmt(values["high"][position]),
                _fmt(values["low"][position]),
                _fmt(values["close"][position]),
                _fmt(values["volume"][position]),
                _fmt(values["amount"][position]),
                "",  # 数据湖无换手率 → 缺失
            )
            rows[(symbol, trade_date)] = row  # 同日重复取后一条（确定性）
            returned.add(symbol)
        return rows, returned, None

    @staticmethod
    def _order(
        rows: dict[tuple[str, str], tuple[str, ...]],
        symbols: tuple[str, ...],
        returned: set[str],
    ) -> tuple[tuple[str, ...], ...]:
        """按请求顺序、再按交易日排序展开行，保证同样的输入落同样的行序。"""
        by_symbol: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
        for (code, day), row in rows.items():
            by_symbol.setdefault(code, []).append((day, row))
        emitted: list[tuple[str, ...]] = []
        for symbol in symbols:
            if symbol not in returned:
                continue
            for _day, row in sorted(
                by_symbol.get(symbol, []), key=lambda item: item[0]
            ):
                emitted.append(row)
        return tuple(emitted)

    def _emptied(
        self,
        dataset: str,
        fetched_at: datetime,
        status: DataStatus,
        message: str,
        *,
        missing: tuple[str, ...] = (),
    ) -> RawDataset:
        """构造"什么都没落地"的元数据记录，行数为 0、payload 为 None。"""
        return RawDataset(
            provider=self._provider,
            dataset=dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=status,
            row_count=0,
            missing_symbols=missing,
            message=message,
        )
