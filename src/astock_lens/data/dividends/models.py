"""分红事件领域模型。"""

from datetime import date, datetime

from astock_lens.domain.models import DomainRecord


class DividendEvent(DomainRecord):
    """单次分红派息事件证据。

    保留源站逐字信息，不作派息率推导，不合流，预案与实施明确区分。
    """

    symbol: str
    announcement_date: date | None
    registration_date: date | None
    ex_date: date | None
    implementation_status: str
    cash_dividend_per_10_shares: float | None
    currency: str | None
    available_at: datetime
    source_text: str
