"""NormalizedDataset 分红事件契约测试。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from astock_lens.data.contracts import NormalizedDataset
from astock_lens.data.dividends.models import DividendEvent

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SHANGHAI)


def test_normalized_dataset_supports_dividend_events() -> None:
    """NormalizedDataset 默认 dividend_events 为空元组，并支持载入 DividendEvent。"""
    ds_empty = NormalizedDataset(dataset="test", as_of=AS_OF)
    assert hasattr(ds_empty, "dividend_events")
    assert ds_empty.dividend_events == ()

    event = DividendEvent(
        symbol="601398.SH",
        announcement_date=date(2026, 6, 25),
        registration_date=date(2026, 7, 15),
        ex_date=date(2026, 7, 16),
        implementation_status="实施",
        cash_dividend_per_10_shares=3.06,
        currency="CNY",
        available_at=AS_OF,
        source_text="10派3.06元",
    )

    ds_with_events = NormalizedDataset(
        dataset="test",
        as_of=AS_OF,
        dividend_events=(event,),
    )
    assert len(ds_with_events.dividend_events) == 1
    assert ds_with_events.dividend_events[0].symbol == "601398.SH"
    assert ds_with_events.dividend_events[0].cash_dividend_per_10_shares == 3.06
