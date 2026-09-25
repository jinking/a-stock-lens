"""平台基础（设置、导入面、交易日历、文档一致性）长尾用例。

本文件由 Task 12「文件合并」把以下 4 个同域小文件整体搬入：
    - tests/unit/test_settings.py（1 例）
    - tests/unit/test_import.py（1 例）
    - tests/unit/test_trading_calendar.py（6 例）
    - tests/unit/test_docs_consistency.py（1 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from datetime import date
from pathlib import Path

import astock_lens
from astock_lens.calendar.china import ChinaTradingCalendar
from astock_lens.settings import load_app_config

# ===========================================================================
# 来源：tests/unit/test_settings.py（1 例）
# ===========================================================================


def test_load_app_config_reads_local_storage_paths() -> None:
    config = load_app_config(Path("configs/app.yaml"))

    assert config.app.name == "A-Stock Lens"
    assert config.storage.database == Path("var/astock.duckdb")
    assert config.storage.parquet_root == Path("data")


# ===========================================================================
# 来源：tests/unit/test_import.py（1 例）
# ===========================================================================


def test_package_imports() -> None:
    assert astock_lens.__version__


# ===========================================================================
# 来源：tests/unit/test_trading_calendar.py（6 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


# 逐日判定六行：行序与原用例一致，label 即原测试名，逐日注释逐字保留。
# 列 = label, day, expected；比对方式与原断言同为 `is`。
TRADE_DATE_CASES: tuple[tuple[str, date, bool], ...] = (
    # test_regular_weekday_is_trade_date:
    #   2026-09-18 是周五，正常交易日
    ("test_regular_weekday_is_trade_date", date(2026, 9, 18), True),
    # test_weekend_is_not_trade_date:
    #   2026-09-19 是周六，2026-09-20 是周日
    ("test_weekend_is_not_trade_date", date(2026, 9, 19), False),
    ("test_weekend_is_not_trade_date", date(2026, 9, 20), False),
    # test_statutory_holiday_is_not_trade_date:
    #   2026-01-01 元旦，周四，休市
    ("test_statutory_holiday_is_not_trade_date", date(2026, 1, 1), False),
    #   2026-05-01 劳动节，周五，休市
    ("test_statutory_holiday_is_not_trade_date", date(2026, 5, 1), False),
    #   2026-10-01 国庆节，周四，休市
    ("test_statutory_holiday_is_not_trade_date", date(2026, 10, 1), False),
)


def test_is_trade_date_matches_every_documented_day() -> None:
    """原 3 条逐日判定用例收表：交易日 / 周末 / 法定假日共 6 日逐日断言。"""
    calendar = ChinaTradingCalendar()
    wrong = []
    for label, day, expected in TRADE_DATE_CASES:
        actual = calendar.is_trade_date(day)
        if actual is not expected:
            wrong.append(
                f"{label}: {day.isoformat()} 得到 {actual!r}，期望 {expected!r}"
            )
    assert not wrong, "交易日判定与文档不符:\n" + "\n".join(wrong)


# 最近交易日三行：行序与原用例一致，label 即原测试名；比对方式与原断言同为 `==`。
LATEST_TRADE_DATE_CASES: tuple[tuple[str, date, date], ...] = (
    # test_latest_trade_date_on_trade_date_returns_self:
    #   2026-09-18 是周五，返回自身。
    (
        "test_latest_trade_date_on_trade_date_returns_self",
        date(2026, 9, 18),
        date(2026, 9, 18),
    ),
    # test_latest_trade_date_on_weekend_returns_previous_friday:
    #   周六、周日都回退到同一个周五。
    (
        "test_latest_trade_date_on_weekend_returns_previous_friday",
        date(2026, 9, 19),
        date(2026, 9, 18),
    ),
    (
        "test_latest_trade_date_on_weekend_returns_previous_friday",
        date(2026, 9, 20),
        date(2026, 9, 18),
    ),
)


def test_latest_trade_date_matches_every_documented_day() -> None:
    """原 2 条「最近交易日」用例收表：交易日返回自身，周末回退到前一个周五。"""
    calendar = ChinaTradingCalendar()
    wrong = []
    for label, day, expected in LATEST_TRADE_DATE_CASES:
        actual = calendar.get_latest_trade_date(day)
        if actual != expected:
            wrong.append(
                f"{label}: {day.isoformat()} 得到 {actual!r}，期望 {expected!r}"
            )
    assert not wrong, "最近交易日与文档不符:\n" + "\n".join(wrong)


def test_custom_dates_override() -> None:
    custom_dates = {date(2026, 9, 19)}  # 假设周六特殊开市
    calendar = ChinaTradingCalendar(trade_dates=custom_dates)
    assert calendar.is_trade_date(date(2026, 9, 19)) is True
    assert calendar.is_trade_date(date(2026, 9, 18)) is False


# ===========================================================================
# 来源：tests/unit/test_docs_consistency.py（1 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


# 文件 → 不得再出现的过期文案（逐字来自原先三个用例）。
STALE_CLAIMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "README.md",
        (
            "Candidate 阶段因为入选规则尚未批准而 `BLOCKED`",
            "Market Regime、Market Validation、Signal 检测器（阈值 `Deferred`）",
            "五个阶段显式 `BLOCKED`",
            "Candidate Qualification 规则（四个方案待所有者裁决）",
        ),
    ),
    (
        "docs/ROADMAP.md",
        (
            "入选规则尚未批准",
            "正式候选发布（Candidate Publishing）依然被既定产品门禁安全阻断",
            "Market Regime / Market Validation / Signal 三个模块：契约已就位，实现被上面第一节的阈值阻塞",
        ),
    ),
    (
        "docs/REMAINING_PRODUCT_BLOCKERS.md",
        (
            "Candidate 阶段因为入选规则尚未批准",
            "目前日常管线中 `BUILD_CANDIDATES` 阶段被依法**强制安全阻断**",
            "src/astock_lens/signals/ 模块尚未构建",
            "src/astock_lens/regime/ 尚未创建",
        ),
    ),
)


def test_documentation_does_not_claim_stale_status() -> None:
    """三份文档合并为一张表：任何一条过期文案都点名文件与文案。"""
    stale: list[str] = []
    for path, phrases in STALE_CLAIMS:
        text = (_repo_root() / path).read_text(encoding="utf-8")
        for phrase in phrases:
            if phrase in text:
                stale.append(f"{path}: {phrase!r}")
    assert not stale, "文档仍在声称过期状态:\n" + "\n".join(stale)
