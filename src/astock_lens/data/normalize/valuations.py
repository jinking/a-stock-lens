"""把 neodata 的估值块归一化为规范估值观测。

neodata 的「统一估值查询」块由两部分组成：一段 `**字段**: 值` 的键值头（最新 PE/PB、
历史分位、相对行业标签），和一张逐日时序表（动态 PE、滚动 PS、滚动市现率、股息率、EV、PEG）。
两部分的值都要，缺一不可：

- **时序表给出估值日期**，因此表里的指标天然带时点，可以直接做 point-in-time 选值；
- **键值头只有"最新"**，没有日期。日期按以下顺序取：时序表里的最新一天；没有表时
  （例如板块查询返回"暂无数据"）用查询日——服务端给的本来就是"最新值"，
  以查询日为其估值日期是如实的，`dated_from_query` 会记录有多少条是这样来的。

缺失标记（`--`、`暂无数据`）一律成为"没有值"，绝不变成 0；分类标签进 `text_value`，
只作证据，不参与排名。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from astock_lens.data.contracts import RawDataset
from astock_lens.data.markdown import Table, parse_key_values, parse_tables
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord, ValuationObservation

SHANGHAI = ZoneInfo("Asia/Shanghai")
A_SHARE_CLOSE_HOUR = 15

# neodata 的栏目名固定，但写法里带全角括号与中文，因此映射必须逐字对应。
SYMBOL_LABEL = "标的代码（统一输出字段名）"
NAME_LABEL = "标的名称"
VALUATION_TABLE = "个股历史估值时序数据列表（仅股票历史模式）"
DATE_COLUMN = "估值日期（YYYYMMDD）"

MISSING_MARKERS: frozenset[str] = frozenset(
    {"--", "-", "", "暂无数据", "nan", "none", "null"}
)

BLOCK_TYPE = "统一估值查询"


@dataclass(frozen=True)
class ValuationMetric:
    """一个规范估值指标：栏目名、单位，以及它出现在键值头还是时序表里。"""

    metric: str
    label: str
    unit: str
    in_table: bool = False


# 键值头里的指标（只有"最新"，日期由时序表或查询日推定）。
HEADER_METRICS: tuple[ValuationMetric, ...] = (
    ValuationMetric("pe_ttm", "滚动市盈率（倍）", "x"),
    ValuationMetric("pe_percentile", "市盈率历史分位数（%）", "%"),
    ValuationMetric("pb", "市净率（倍）", "x"),
    ValuationMetric("pb_percentile", "市净率历史分位数（%）", "%"),
)

# 键值头里的分类标签：只用作文本证据。
HEADER_LABELS: Mapping[str, str] = {"industry_relative_label": "相对行业平均估值标签"}

# 时序表里的指标（每行一个交易日）。
TABLE_METRICS: tuple[ValuationMetric, ...] = (
    ValuationMetric("pe_dynamic", "动态市盈率（倍）", "x", True),
    ValuationMetric("pe_ttm_deducted", "扣非后滚动市盈率（倍）", "x", True),
    ValuationMetric("ps_ttm", "滚动市销率（倍）", "x", True),
    ValuationMetric("ps_dynamic", "动态市销率（倍）", "x", True),
    ValuationMetric("pcf_operating_ttm", "滚动市现率-经营现金流（倍）", "x", True),
    ValuationMetric("pcf_net_ttm", "动态市现率-现金流净额（倍）", "x", True),
    ValuationMetric("dividend_yield_static", "静态股息率（%）", "%", True),
    ValuationMetric("dividend_yield_ttm", "滚动股息率（%）", "%", True),
    ValuationMetric("enterprise_value", "企业价值（亿元）", "亿元", True),
    ValuationMetric("peg", "PEG（市盈率相对盈利增长比率）", "x", True),
)

ALL_METRICS: tuple[ValuationMetric, ...] = HEADER_METRICS + TABLE_METRICS


class ValuationFailure(DomainRecord):
    """一条读不出来的估值单元格或整块。"""

    label: str
    raw_value: str
    reason: str
    symbol: str | None = None
    metric: str | None = None


class ValuationNormalizeOutcome(DomainRecord):
    """一个数据集的估值归一化结果。"""

    dataset: str
    as_of: datetime
    source_status: DataStatus
    observations: tuple[ValuationObservation, ...] = ()
    failures: tuple[ValuationFailure, ...] = ()
    absent_metrics: tuple[str, ...] = ()
    dated_from_query: int = 0


class NeodataValuationNormalizer:
    """把 neodata 的估值内容块转成规范估值观测。"""

    def __init__(self, source: str = "neodata") -> None:
        self._source = source

    def normalize(
        self, dataset: RawDataset, *, as_of: datetime
    ) -> ValuationNormalizeOutcome:
        """逐块解析；每个块只贡献它确实带有的指标。"""
        payload = dataset.payload
        if payload is None or not payload.rows:
            return ValuationNormalizeOutcome(
                dataset=dataset.dataset, as_of=as_of, source_status=dataset.status
            )

        observations: list[ValuationObservation] = []
        failures: list[ValuationFailure] = []
        seen_metrics: set[str] = set()
        dated_from_query = 0

        for block_type, _, content in payload.rows:
            if block_type != BLOCK_TYPE:
                continue
            symbol = parse_key_values(content).get(SYMBOL_LABEL, "").strip()
            if not symbol:
                failures.append(
                    ValuationFailure(
                        label=SYMBOL_LABEL,
                        raw_value="",
                        reason="这个内容块没有标明标的代码，无法归属",
                    )
                )
                continue

            header = parse_key_values(content)
            tables = parse_tables(content)
            table = _valuation_table(tables)
            latest = _latest_date(table)

            for metric in HEADER_METRICS:
                raw = header.get(metric.label)
                if raw is None:
                    continue
                if latest is None:
                    # 没有时序表（板块查询）时，服务端给的"最新值"以查询日为日期。
                    dated_from_query += 1
                observations.append(
                    self._observation(
                        symbol=symbol,
                        metric=metric,
                        raw_value=raw,
                        valuation_date=latest or as_of.date(),
                        as_of=as_of,
                        failures=failures,
                    )
                )
                seen_metrics.add(metric.metric)

            for metric_name, label in HEADER_LABELS.items():
                raw = header.get(label)
                if raw is None or raw.strip().lower() in MISSING_MARKERS:
                    continue
                observations.append(
                    ValuationObservation(
                        symbol=symbol,
                        metric=metric_name,
                        valuation_date=latest or as_of.date(),
                        available_at=_close_of(latest or as_of.date()),
                        as_of=as_of,
                        source=self._source,
                        text_value=raw,
                    )
                )
                seen_metrics.add(metric_name)

            if table is None:
                continue
            positions = {column: index for index, column in enumerate(table.columns)}
            for row in table.rows:
                day = _row_date(row, positions)
                if day is None:
                    failures.append(
                        ValuationFailure(
                            label=DATE_COLUMN,
                            raw_value=row[positions[DATE_COLUMN]]
                            if DATE_COLUMN in positions
                            else "",
                            reason="这一行没有可读的估值日期，不能进入时点计算",
                            symbol=symbol,
                        )
                    )
                    continue
                for metric in TABLE_METRICS:
                    index = positions.get(metric.label)
                    if index is None or index >= len(row):
                        continue
                    observations.append(
                        self._observation(
                            symbol=symbol,
                            metric=metric,
                            raw_value=row[index],
                            valuation_date=day,
                            as_of=as_of,
                            failures=failures,
                        )
                    )
                    seen_metrics.add(metric.metric)

        absent = tuple(
            metric.metric for metric in ALL_METRICS if metric.metric not in seen_metrics
        )
        return ValuationNormalizeOutcome(
            dataset=dataset.dataset,
            as_of=as_of,
            source_status=dataset.status,
            observations=tuple(observations),
            failures=tuple(failures),
            absent_metrics=absent,
            dated_from_query=dated_from_query,
        )

    def _observation(
        self,
        *,
        symbol: str,
        metric: ValuationMetric,
        raw_value: str,
        valuation_date: date,
        as_of: datetime,
        failures: list[ValuationFailure],
    ) -> ValuationObservation:
        text = raw_value.strip()
        if text.lower() in MISSING_MARKERS:
            value: float | None = None
        else:
            try:
                value = float(text.replace(",", ""))
            except ValueError:
                failures.append(
                    ValuationFailure(
                        label=metric.label,
                        raw_value=text,
                        reason=f"{text!r} 不是数字",
                        symbol=symbol,
                        metric=metric.metric,
                    )
                )
                value = None

        return ValuationObservation(
            symbol=symbol,
            metric=metric.metric,
            valuation_date=valuation_date,
            available_at=_close_of(valuation_date),
            as_of=as_of,
            source=self._source,
            value=value,
            unit=metric.unit,
        )


def _valuation_table(tables: tuple[Table, ...]) -> Table | None:
    """找出逐日估值表：以估值日期为第一列的那张。"""
    for table in tables:
        if DATE_COLUMN in table.columns:
            return table
    return None


def _latest_date(table: Table | None) -> date | None:
    """时序表里最新的一天，作为键值头指标的日期。"""
    if table is None:
        return None
    if DATE_COLUMN not in table.columns:
        return None
    index = table.columns.index(DATE_COLUMN)
    days = [
        day
        for day in (_parse_day(row[index]) for row in table.rows if index < len(row))
        if day is not None
    ]
    return max(days) if days else None


def _row_date(row: tuple[str, ...], positions: Mapping[str, int]) -> date | None:
    index = positions.get(DATE_COLUMN)
    if index is None or index >= len(row):
        return None
    return _parse_day(row[index])


def _parse_day(raw: str) -> date | None:
    """估值日期是 `YYYYMMDD`（例如 20260916）。"""
    text = raw.strip()
    if len(text) != 8 or not text.isdigit():
        return None
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _close_of(day: date) -> datetime:
    """估值可用时点：交易日收盘（15:00 +08:00），保守取值。"""
    return datetime(day.year, day.month, day.day, A_SHARE_CLOSE_HOUR, tzinfo=SHANGHAI)
