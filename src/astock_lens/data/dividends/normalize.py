"""分红派息事件归一化。

将 neodata 的分红送配详细文本解析为规范的 DividendEvent 领域模型。
保持源站逐字信息，严禁计算 TTM 股息率、严禁年化、严禁与股价对齐。
"""

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from astock_lens.data.dividends.models import DividendEvent
from astock_lens.data.markdown import parse_tables

SHANGHAI = ZoneInfo("Asia/Shanghai")
A_SHARE_CLOSE_HOUR = 15

MISSING_MARKERS: frozenset[str] = frozenset(
    {"--", "-", "", "暂无数据", "暂无", "nan", "none", "null"}
)

SYMBOL_SECTION_PATTERN = re.compile(r"##\s*.*?（标的代码[：:]\s*([0-9]{6}\.[A-Z]{2})）")
CURRENCY_PATTERN = re.compile(r"货币单位[：:]\s*([^\s\n\r|]+)")
CASH_DIVIDEND_PATTERN = re.compile(
    r"(?:10派|每10股派|派现)?\s*([0-9]+(?:\.[0-9]+)?)\s*元?"
)


def _parse_date(text: str) -> date | None:
    cleaned = text.strip()
    if not cleaned or cleaned in MISSING_MARKERS:
        return None
    # 支持 YYYY-MM-DD 或 YYYY/MM/DD
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", cleaned)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # 支持 YYYYMMDD
    if len(cleaned) == 8 and cleaned.isdigit():
        return date(int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8]))
    return None


def _parse_cash_dividend(text: str) -> float | None:
    cleaned = text.strip()
    if not cleaned or cleaned in MISSING_MARKERS or "不分配" in cleaned:
        return None
    m = re.search(CASH_DIVIDEND_PATTERN, cleaned)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def normalize_dividend_events(
    content: str,
    *,
    default_as_of: datetime | None = None,
) -> tuple[DividendEvent, ...]:
    """解析文本内容中的全部标的分红事件。"""
    events: list[DividendEvent] = []

    # 按二级标题划分标的段落
    lines = content.splitlines(keepends=True)
    sections: list[tuple[str, str]] = []
    current_symbol: str | None = None
    current_lines: list[str] = []

    for line in lines:
        match = SYMBOL_SECTION_PATTERN.search(line)
        if match:
            if current_symbol is not None:
                sections.append((current_symbol, "".join(current_lines)))
            current_symbol = match.group(1)
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_symbol is not None:
        sections.append((current_symbol, "".join(current_lines)))

    if not sections:
        # 尝试全文找 symbol
        m = re.search(r"([0-9]{6}\.[A-Z]{2})", content)
        if m:
            sections = [(m.group(1), content)]

    for symbol, sec_text in sections:
        currency_match = CURRENCY_PATTERN.search(sec_text)
        currency = currency_match.group(1) if currency_match else None
        if not currency and ("CNY" in sec_text or "人民币" in sec_text):
            currency = "CNY"

        tables = parse_tables(sec_text)
        for table in tables:
            cols = list(table.columns)
            ann_idx = next(
                (
                    i
                    for i, c in enumerate(cols)
                    if any(k in c for k in ("公告日期", "公告日", "预案日", "实施日"))
                ),
                None,
            )
            status_idx = next(
                (
                    i
                    for i, c in enumerate(cols)
                    if any(k in c for k in ("方案进度", "实施状态", "状态", "进度"))
                ),
                None,
            )
            scheme_idx = next(
                (
                    i
                    for i, c in enumerate(cols)
                    if i != status_idx
                    and any(
                        k in c
                        for k in (
                            "分红方案",
                            "每10股派息",
                            "派息",
                            "分红明细",
                            "分红",
                            "金额",
                        )
                    )
                ),
                None,
            )
            reg_idx = next(
                (
                    i
                    for i, c in enumerate(cols)
                    if any(k in c for k in ("股权登记日", "登记日"))
                ),
                None,
            )
            ex_idx = next(
                (
                    i
                    for i, c in enumerate(cols)
                    if any(k in c for k in ("除权除息日", "除权日", "除息日"))
                ),
                None,
            )

            # 如果这表没有分红/方案相关列，可能不是分红明细表
            if scheme_idx is None and status_idx is None and ex_idx is None:
                continue

            for row in table.rows:
                ann_date = (
                    _parse_date(row[ann_idx])
                    if ann_idx is not None and ann_idx < len(row)
                    else None
                )
                reg_date = (
                    _parse_date(row[reg_idx])
                    if reg_idx is not None and reg_idx < len(row)
                    else None
                )
                ex_date = (
                    _parse_date(row[ex_idx])
                    if ex_idx is not None and ex_idx < len(row)
                    else None
                )

                status = ""
                if status_idx is not None and status_idx < len(row):
                    status = row[status_idx].strip()
                if not status and scheme_idx is not None and scheme_idx < len(row):
                    # 如果状态列不存在，尝试从方案列识别
                    if "预案" in row[scheme_idx]:
                        status = "预案"
                    elif "实施" in row[scheme_idx]:
                        status = "实施"

                cash_div = None
                if scheme_idx is not None and scheme_idx < len(row):
                    cash_div = _parse_cash_dividend(row[scheme_idx])

                if ann_date is not None:
                    available_at = datetime(
                        ann_date.year,
                        ann_date.month,
                        ann_date.day,
                        A_SHARE_CLOSE_HOUR,
                        tzinfo=SHANGHAI,
                    )
                elif default_as_of is not None:
                    available_at = default_as_of
                else:
                    available_at = datetime.now(UTC)

                source_text = " | ".join(row)

                events.append(
                    DividendEvent(
                        symbol=symbol,
                        announcement_date=ann_date,
                        registration_date=reg_date,
                        ex_date=ex_date,
                        implementation_status=status,
                        cash_dividend_per_10_shares=cash_div,
                        currency=currency,
                        available_at=available_at,
                        source_text=source_text,
                    )
                )

    return tuple(events)
