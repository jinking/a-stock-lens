"""分红事件归一化测试 (Plan B Task 2).

验证：
- 已实施分红事件正确解析每10股派息、除权日、登记日等字段；
- 预案事件状态保留源状态（不被升格为实施）；
- 缺失日期保留为 None；
- source_text 完整保留源证据；
- 不进行任何 TTM 聚合或年化计算。
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from astock_lens.data.dividends.normalize import normalize_dividend_events

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=SHANGHAI)

SAMPLE_IMPLEMENTED_CONTENT = """## 贵州茅台（标的代码：600519.SH）

货币单位：人民币元
| 公告日期 | 分红方案 | 股权登记日 | 除权除息日 | 方案进度 |
| :---: | :---: | :---: | :---: | :---: |
| 2026-06-20 | 10派300.00元(含税) | 2026-07-05 | 2026-07-06 | 实施 |
| 2025-12-15 | 10派200.00元(含税) | 2025-12-28 | 2025-12-29 | 实施 |
"""

SAMPLE_PROPOSAL_CONTENT = """## 工商银行（标的代码：601398.SH）

| 公告日期 | 方案进度 | 分红方案 | 股权登记日 | 除权除息日 |
| --- | --- | --- | --- | --- |
| 2026-08-29 | 董事会预案 | 10派1.511元 | -- | -- |
| 2026-05-07 | 实施 | 10派1.689元 | 2026-06-18 | 2026-06-19 |
"""

SAMPLE_MISSING_DATES_CONTENT = """## 测试标的（标的代码：000001.SZ）

| 公告日期 | 分红方案 | 股权登记日 | 除权除息日 | 实施状态 |
| --- | --- | --- | --- | --- |
| -- | 10派1.00元 | -- | -- | 股东大会预案 |
"""


def test_parse_implemented_dividend_event() -> None:
    """Step 1: 已实施事件解析，每10股派息与除权日齐备。"""
    events = normalize_dividend_events(SAMPLE_IMPLEMENTED_CONTENT, default_as_of=AS_OF)
    assert len(events) == 2

    ev1 = events[0]
    assert ev1.symbol == "600519.SH"
    assert ev1.announcement_date == date(2026, 6, 20)
    assert ev1.registration_date == date(2026, 7, 5)
    assert ev1.ex_date == date(2026, 7, 6)
    assert ev1.implementation_status == "实施"
    assert ev1.cash_dividend_per_10_shares == 300.00
    assert ev1.currency in ("CNY", "人民币元")
    assert ev1.available_at == datetime(2026, 6, 20, 15, 0, tzinfo=SHANGHAI)
    assert "10派300.00元" in ev1.source_text


def test_parse_proposal_event_preserves_source_status() -> None:
    """Step 2: 预案状态必须保持源站状态，严禁升格为实施。"""
    events = normalize_dividend_events(SAMPLE_PROPOSAL_CONTENT, default_as_of=AS_OF)
    assert len(events) == 2

    proposal = events[0]
    assert proposal.symbol == "601398.SH"
    assert proposal.announcement_date == date(2026, 8, 29)
    assert proposal.implementation_status == "董事会预案"
    assert proposal.cash_dividend_per_10_shares == 1.511
    assert proposal.ex_date is None
    assert proposal.registration_date is None

    implemented = events[1]
    assert implemented.implementation_status == "实施"
    assert implemented.ex_date == date(2026, 6, 19)


def test_missing_dates_remain_none() -> None:
    """Step 3: 缺失日期原样保持 None，不瞎猜。"""
    events = normalize_dividend_events(
        SAMPLE_MISSING_DATES_CONTENT, default_as_of=AS_OF
    )
    assert len(events) == 1
    ev = events[0]
    assert ev.symbol == "000001.SZ"
    assert ev.announcement_date is None
    assert ev.registration_date is None
    assert ev.ex_date is None
    assert ev.cash_dividend_per_10_shares == 1.00
    assert ev.implementation_status == "股东大会预案"
    assert ev.available_at == AS_OF


def test_source_evidence_preservation() -> None:
    """Step 4: source_text 完整保留该行的原始文本证据。"""
    events = normalize_dividend_events(SAMPLE_IMPLEMENTED_CONTENT, default_as_of=AS_OF)
    for ev in events:
        assert ev.source_text
        assert ev.symbol in SAMPLE_IMPLEMENTED_CONTENT
        assert str(int(ev.cash_dividend_per_10_shares or 0)) in ev.source_text
