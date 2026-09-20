"""China A-Share market trading calendar implementation."""

from collections.abc import Iterable
from datetime import date, timedelta

# 中国 A 股已知法定休市日（落在周一至周五的工作日部分，周末默认自动休市）
# 覆盖 2024 ~ 2027 年已知法定节假日休市
KNOWN_CHINA_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2024
        date(2024, 1, 1),
        date(2024, 2, 9),
        date(2024, 2, 12),
        date(2024, 2, 13),
        date(2024, 2, 14),
        date(2024, 2, 15),
        date(2024, 2, 16),
        date(2024, 4, 4),
        date(2024, 4, 5),
        date(2024, 5, 1),
        date(2024, 5, 2),
        date(2024, 5, 3),
        date(2024, 6, 10),
        date(2024, 9, 16),
        date(2024, 9, 17),
        date(2024, 10, 1),
        date(2024, 10, 2),
        date(2024, 10, 3),
        date(2024, 10, 4),
        date(2024, 10, 7),
        # 2025
        date(2025, 1, 1),
        date(2025, 1, 28),
        date(2025, 1, 29),
        date(2025, 1, 30),
        date(2025, 1, 31),
        date(2025, 2, 3),
        date(2025, 2, 4),
        date(2025, 4, 4),
        date(2025, 5, 1),
        date(2025, 5, 2),
        date(2025, 5, 5),
        date(2025, 5, 30),
        date(2025, 10, 1),
        date(2025, 10, 2),
        date(2025, 10, 3),
        date(2025, 10, 6),
        date(2025, 10, 7),
        date(2025, 10, 8),
        # 2026
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 2, 16),
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 2, 19),
        date(2026, 2, 20),
        date(2026, 4, 6),
        date(2026, 5, 1),
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 6, 19),
        date(2026, 9, 25),
        date(2026, 10, 1),
        date(2026, 10, 2),
        date(2026, 10, 5),
        date(2026, 10, 6),
        date(2026, 10, 7),
    }
)


class ChinaTradingCalendar:
    """中国 A 股交易日历判定与计算。"""

    def __init__(
        self,
        *,
        trade_dates: Iterable[date] | None = None,
        holidays: Iterable[date] | None = None,
    ) -> None:
        """初始化交易日历。

        若指定了 trade_dates，则严格以该集合作为合法交易日。
        否则以工作日（周一至周五）剔除已知法定节假日进行判定。
        """
        self._trade_dates: frozenset[date] | None = (
            frozenset(trade_dates) if trade_dates is not None else None
        )
        self._holidays: frozenset[date] = (
            frozenset(holidays) if holidays is not None else KNOWN_CHINA_HOLIDAYS
        )

    def is_trade_date(self, target: date) -> bool:
        """检查给定日期是否为 A 股交易日。"""
        if self._trade_dates is not None:
            return target in self._trade_dates

        # 周末（周六=5, 周日=6）一律休市
        if target.weekday() >= 5:
            return False

        # 工作日但属于法定休市日
        return target not in self._holidays

    def get_latest_trade_date(self, target: date) -> date:
        """获取不晚于 target 的最近有效交易日。"""
        current = target
        for _ in range(60):  # 最多往前回溯 60 天（覆盖长假如春节/国庆）
            if self.is_trade_date(current):
                return current
            current -= timedelta(days=1)
        return target

    def get_next_trade_date(self, target: date) -> date:
        """获取晚于 target 的下一个有效交易日。"""
        current = target + timedelta(days=1)
        for _ in range(60):
            if self.is_trade_date(current):
                return current
            current += timedelta(days=1)
        return current


_DEFAULT_CALENDAR: ChinaTradingCalendar | None = None


def get_calendar() -> ChinaTradingCalendar:
    """获取全局共享的中国 A 股交易日历实例。"""
    global _DEFAULT_CALENDAR
    if _DEFAULT_CALENDAR is None:
        _DEFAULT_CALENDAR = ChinaTradingCalendar()
    return _DEFAULT_CALENDAR
