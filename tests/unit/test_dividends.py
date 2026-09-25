"""分红域（覆盖率、事件归一化、股息率因子、归一化数据集）长尾用例。

本文件由 Task 12「文件合并」把以下 4 个同域小文件整体搬入：
    - tests/unit/test_dividend_coverage.py（4 例）
    - tests/unit/test_dividend_event_normalizer.py（4 例）
    - tests/unit/test_dividend_yield_factor.py（2 例）
    - tests/unit/test_normalized_dataset_dividends.py（1 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from astock_lens.calibration.dividend_coverage import (
    audit_dividend_coverage,
    render_dividend_coverage_json,
    render_dividend_coverage_markdown,
)
from astock_lens.data.contracts import NormalizedDataset
from astock_lens.data.dividends.models import DividendEvent
from astock_lens.data.dividends.normalize import normalize_dividend_events
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DailyBar
from astock_lens.factors.builtin import build_factor
from astock_lens.factors.config import FactorConfig
from astock_lens.factors.contracts import FactorContext

# ===========================================================================
# 来源：tests/unit/test_dividend_coverage.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 分红事件覆盖审计测试 (Plan B Task 4).
#
# 验证：
# - 分母必须显式来自研究池（空名单抛出 ValueError）；
# - 预案与实施事件严格分开统计；
# - 各覆盖统计（任意事件、已实施现金分红、除权日、登记日）精确吻合；
# - 能够确定性渲染 JSON 与 Markdown 格式报告；
# - 证明审计过程严格只读。
# """
#


COVERAGE_SHANGHAI = ZoneInfo("Asia/Shanghai")


COV_AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=COVERAGE_SHANGHAI)


def _ev(
    symbol: str,
    *,
    status: str = "实施",
    cash: float | None = 10.0,
    ex_date: date | None = date(2026, 7, 6),
    reg_date: date | None = date(2026, 7, 5),
    ann_date: date | None = date(2026, 6, 20),
) -> DividendEvent:
    return DividendEvent(
        symbol=symbol,
        announcement_date=ann_date,
        registration_date=reg_date,
        ex_date=ex_date,
        implementation_status=status,
        cash_dividend_per_10_shares=cash,
        currency="CNY",
        available_at=datetime(2026, 6, 20, 15, 0, tzinfo=COVERAGE_SHANGHAI),
        source_text="source row",
    )


def test_explicit_universe_denominator_required() -> None:
    """Step 1: 分母必须显式给出，空名单必须抛错。"""
    with pytest.raises(ValueError, match="分母"):
        audit_dividend_coverage(events=(), universe=(), as_of=COV_AS_OF)


def test_status_split_and_coverage_metrics() -> None:
    """Step 2: 预案与实施独立计数，各覆盖标的精确统计。"""
    universe = ("600519.SH", "601398.SH", "000001.SZ", "000858.SZ")

    events = (
        # 600519.SH: 两个实施事件，均有现金派息与日期
        _ev(
            "600519.SH",
            status="实施",
            cash=300.0,
            ex_date=date(2026, 7, 6),
            reg_date=date(2026, 7, 5),
        ),
        _ev(
            "600519.SH",
            status="实施",
            cash=200.0,
            ex_date=date(2025, 12, 29),
            reg_date=date(2025, 12, 28),
        ),
        # 601398.SH: 一个预案（无除权/登记日），一个实施
        _ev("601398.SH", status="董事会预案", cash=1.511, ex_date=None, reg_date=None),
        _ev(
            "601398.SH",
            status="实施",
            cash=1.689,
            ex_date=date(2026, 6, 19),
            reg_date=date(2026, 6, 18),
        ),
        # 000001.SZ: 仅有一个预案，且 cash 为 None（不分配）
        _ev("000001.SZ", status="股东大会预案", cash=None, ex_date=None, reg_date=None),
        # 999999.SH: 不在 universe 内，不计入统计
        _ev("999999.SH", status="实施", cash=5.0),
    )

    report = audit_dividend_coverage(events=events, universe=universe, as_of=COV_AS_OF)

    assert report.universe_size == 4
    assert report.event_count == 5  # 999999.SH 排除
    assert report.symbols_with_any_event == 3  # 600519, 601398, 000001
    assert report.symbols_with_implemented_cash_event == 2  # 600519, 601398
    assert report.symbols_with_ex_date == 2  # 600519, 601398
    assert report.symbols_with_registration_date == 2  # 600519, 601398
    assert report.proposal_count == 2  # 601398 预案 + 000001 预案
    assert report.implemented_count == 3  # 600519 2个 + 601398 1个
    assert report.missing_symbols == ("000858.SZ",)


def test_deterministic_report_rendering() -> None:
    """Step 3: 确定性渲染 JSON 与 Markdown。"""
    universe = ("600519.SH", "000001.SZ")
    events = (_ev("600519.SH", status="实施", cash=300.0),)
    report = audit_dividend_coverage(events=events, universe=universe, as_of=COV_AS_OF)

    # JSON 渲染
    json_text = render_dividend_coverage_json(report)
    assert '"universe_size": 2' in json_text
    assert '"symbols_with_implemented_cash_event": 1' in json_text
    assert '"000001.SZ"' in json_text

    # Markdown 渲染
    md_text = render_dividend_coverage_markdown(report)
    assert "# 分红事件覆盖审计报告" in md_text
    assert "600519.SH" in md_text or "000001.SZ" in md_text
    assert "2" in md_text


def test_dividend_coverage_cli_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 4: 证明 CLI 过程严格只读，支持 JSON 与 Markdown 输出。"""
    from typer.testing import CliRunner

    from astock_lens.cli.app import app

    runner = CliRunner()

    # 准备假 universe
    uni_path = tmp_path / "universe.json"
    uni_content = '{"research_symbols": ["600519.SH", "000001.SZ"]}'
    uni_path.write_text(uni_content, encoding="utf-8")

    # 准备假 raw 数据
    import csv

    raw_root = tmp_path / "raw"
    div_dir = raw_root / "neodata" / "dividend_history"
    div_dir.mkdir(parents=True)
    csv_file = div_dir / "2026-09-19.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["dataset", "batch", "content", "status", "as_of"])
        writer.writerow(
            [
                "dividend_history",
                "0",
                (
                    "## 贵州茅台（标的代码：600519.SH）\n\n"
                    "| 公告日期 | 分红方案 | 股权登记日 | 除权除息日 | 方案进度 |\n"
                    "| :--- | :--- | :--- | :--- | :--- |\n"
                    "| 2026-06-20 | 10派300元 | 2026-07-05 | 2026-07-06 | 实施 |\n"
                ),
                "VALUE",
                "2026-09-19T15:00:00+08:00",
            ]
        )
    initial_csv = csv_file.read_bytes()
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(raw_root))

    out_json = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "dividend-coverage",
            "--as-of",
            "2026-09-19",
            "--universe",
            str(uni_path),
            "--output",
            str(out_json),
        ],
    )
    assert result.exit_code == 0
    assert "研究池: 2 只" in result.output
    assert "已实施现金分红: 1 / 2" in result.output
    assert out_json.is_file()

    # 验证只读：原始 CSV 与 Universe 文件哈希未发生变动
    assert uni_path.read_text(encoding="utf-8") == uni_content
    assert csv_file.read_bytes() == initial_csv


# ===========================================================================
# 来源：tests/unit/test_dividend_event_normalizer.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 分红事件归一化测试 (Plan B Task 2).
#
# 验证：
# - 已实施分红事件正确解析每10股派息、除权日、登记日等字段；
# - 预案事件状态保留源状态（不被升格为实施）；
# - 缺失日期保留为 None；
# - source_text 完整保留源证据；
# - 不进行任何 TTM 聚合或年化计算。
# """
#


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


# ===========================================================================
# 来源：tests/unit/test_dividend_yield_factor.py（2 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# DividendYieldTTMFactor 单元测试 (Plan D Task 2).
#
# 验证项目所有者批准的口径：
# - A1: TTM 窗口按除权日 (ex_date) 在 [as_of - 365d, as_of] 内；
# - B1: 严格排除预案，仅聚合已实施分红；
# - C1: 以 as_of 当日收盘价为分母，单位为 %；
# - 边界：停牌/缺价返回 NULL，无分红记录返回 NOT_APPLICABLE，有记录但过去一年派息为0返回 0.0。
# """
#


YIELD_FACTOR_SHANGHAI = ZoneInfo("Asia/Shanghai")


YIELD_FACTOR_AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=YIELD_FACTOR_SHANGHAI)


def _config() -> FactorConfig:
    return FactorConfig(
        name="dividend_yield_ttm",
        domain="VALUATION",
        description="Trailing dividend yield, in percent.",
        inputs=("dividend_yield_ttm",),
        frequency="DAILY",
        direction="HIGHER_MEANS_MORE_INCOME_RETURNED",
        null_policy="NULL_UNLESS_THE_METRIC_HAS_A_PUBLISHED_VALUE",
        version="v1",
    )


def _bar(symbol: str, trade_date: date, close: float) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000000.0,
        amount=5000000.0,
    )


def _event(
    symbol: str,
    ex_date: date | None,
    status: str,
    per_10: float | None,
    available_at: datetime = YIELD_FACTOR_AS_OF,
) -> DividendEvent:
    return DividendEvent(
        symbol=symbol,
        announcement_date=ex_date - timedelta(days=20) if ex_date else date(2026, 8, 1),
        registration_date=ex_date - timedelta(days=1) if ex_date else None,
        ex_date=ex_date,
        implementation_status=status,
        cash_dividend_per_10_shares=per_10,
        currency="CNY",
        available_at=available_at,
        source_text=f"10派{per_10}元" if per_10 else "不分配",
    )


def _dataset(
    symbol: str, close: float, events: tuple[DividendEvent, ...]
) -> NormalizedDataset:
    """按原用例的构造方式装配输入：as_of 当日一根日线 + 给定分红事件。"""
    return NormalizedDataset(
        dataset="test",
        as_of=YIELD_FACTOR_AS_OF,
        daily_bars=(_bar(symbol, YIELD_FACTOR_AS_OF.date(), close),),
        dividend_events=events,
    )


# 测试 1–4（取值口径）四行：行序与原用例一致，label 即原测试名，
# 原 docstring 与算式注释逐字保留为行注释；unit 为 None 表示该行不断言单位。
YIELD_VALUE_CASES = (
    # test_dividend_yield_ttm_standard_annual_distribution:
    #   测试 1: 正常单次已实施分红计算股息率 (A1 + B1 + C1).
    #   股价 5.00 元；2026-07-15 除权，每 10 股派 2.50 元 (每股 0.25 元)
    #   0.25 / 5.00 * 100 = 5.00%
    (
        "test_dividend_yield_ttm_standard_annual_distribution",
        "601398.SH",
        5.00,
        (_event("601398.SH", date(2026, 7, 15), "实施", 2.50),),
        5.0000,
        "%",
    ),
    # test_dividend_yield_ttm_multiple_distributions_within_year:
    #   测试 2: 一年多次分红 (中报+年报) 累加派息.
    #   两次派息都在 365 天内；每股 19.106 / 每股 30.876
    #   (19.106 + 30.876) / 1500.0 * 100 = 49.982 / 1500 * 100 = 3.332133...%
    (
        "test_dividend_yield_ttm_multiple_distributions_within_year",
        "600519.SH",
        1500.0,
        (
            _event("600519.SH", date(2025, 12, 20), "实施", 191.06),
            _event("600519.SH", date(2026, 6, 25), "实施", 308.76),
        ),
        round((49.982 / 1500.0) * 100.0, 4),
        None,
    ),
    # test_dividend_yield_ttm_excludes_proposals:
    #   测试 3: 严格排除预案事件 (B1 口径).
    #   预案派息 5.00 元，已实施派息 2.50 元；仅计入实施的 2.50 (每股 0.25) -> 5.0%
    (
        "test_dividend_yield_ttm_excludes_proposals",
        "601398.SH",
        5.00,
        (
            _event("601398.SH", date(2026, 7, 15), "实施", 2.50),
            _event("601398.SH", date(2026, 8, 20), "预案", 5.00),
        ),
        5.0000,
        None,
    ),
    # test_dividend_yield_ttm_excludes_events_outside_window:
    #   测试 4: 排除超过 365 天与晚于 as_of 的分红 (A1 口径).
    #   超过 365 天 / 窗口内 / 晚于 as_of
    (
        "test_dividend_yield_ttm_excludes_events_outside_window",
        "601398.SH",
        5.00,
        (
            _event("601398.SH", date(2025, 9, 10), "实施", 3.00),
            _event("601398.SH", date(2026, 7, 15), "实施", 2.50),
            _event(
                "601398.SH",
                date(2026, 9, 25),
                "实施",
                4.00,
                available_at=YIELD_FACTOR_AS_OF + timedelta(days=5),
            ),
        ),
        5.0000,
        None,
    ),
)


def test_dividend_yield_ttm_value_cases() -> None:
    """测试 1–4：TTM 窗口、已实施口径与 as_of 当日收盘价分母的取值断言。"""
    wrong = []
    for label, symbol, close, events, expected_value, unit in YIELD_VALUE_CASES:
        result = build_factor(_config()).compute(
            FactorContext(
                symbol=symbol,
                as_of=YIELD_FACTOR_AS_OF,
                dataset=_dataset(symbol, close, events),
            )
        )
        if result.status is not DataStatus.VALUE:
            wrong.append(f"{label}: status={result.status!r}，期望 VALUE")
        elif result.raw_value is None:
            wrong.append(f"{label}: raw_value 为 None，期望 {expected_value!r}")
        elif round(result.raw_value, 4) != expected_value:
            wrong.append(
                f"{label}: raw_value={result.raw_value!r}，期望 {expected_value!r}"
            )
        if unit is not None and result.unit != unit:
            wrong.append(f"{label}: unit={result.unit!r}，期望 {unit!r}")
    assert not wrong, "股息率取值口径未按预期:\n" + "\n".join(wrong)


# 测试 5–7（边界状态）三行：行序与原用例一致，label 即原测试名，
# 原 docstring 与注释逐字保留；expected_value 为 None 时要求 raw_value 就是 None，
# 否则按原用例的精确相等比较（0.0 不经过四舍五入）。
YIELD_STATUS_CASES = (
    # test_dividend_yield_ttm_missing_price_returns_null:
    #   测试 5: 缺少日线价格或停牌时返回 NULL，不捏造 0.
    #   无行情
    (
        "test_dividend_yield_ttm_missing_price_returns_null",
        "601398.SH",
        (),
        (_event("601398.SH", date(2026, 7, 15), "实施", 2.50),),
        DataStatus.NULL,
        None,
        None,
    ),
    # test_dividend_yield_ttm_no_events_returns_not_applicable:
    #   测试 6: 无任何分红记录返回 NOT_APPLICABLE.
    #   该股票无分红事件
    (
        "test_dividend_yield_ttm_no_events_returns_not_applicable",
        "688001.SH",
        (_bar("688001.SH", YIELD_FACTOR_AS_OF.date(), 20.00),),
        (),
        DataStatus.NOT_APPLICABLE,
        None,
        None,
    ),
    # test_dividend_yield_ttm_has_history_but_zero_in_past_year_returns_zero_value:
    #   测试 7: 标的有分红历史记录但过去 365 天无已实施派息，返回 VALUE 0.0%.
    #   分红除权在 500 天前
    (
        "test_dividend_yield_ttm_has_history_but_zero_in_past_year_returns_zero_value",
        "600000.SH",
        (_bar("600000.SH", YIELD_FACTOR_AS_OF.date(), 10.00),),
        (_event("600000.SH", date(2025, 4, 1), "实施", 1.50),),
        DataStatus.VALUE,
        0.0,
        "%",
    ),
)


def test_dividend_yield_ttm_status_boundaries() -> None:
    """测试 5–7：缺价 / 无分红记录 / 一年内零派息的状态与取值。"""
    wrong = []
    for (
        label,
        symbol,
        bars,
        events,
        expected_status,
        expected_value,
        unit,
    ) in YIELD_STATUS_CASES:
        result = build_factor(_config()).compute(
            FactorContext(
                symbol=symbol,
                as_of=YIELD_FACTOR_AS_OF,
                dataset=NormalizedDataset(
                    dataset="test",
                    as_of=YIELD_FACTOR_AS_OF,
                    daily_bars=bars,
                    dividend_events=events,
                ),
            )
        )
        if result.status is not expected_status:
            wrong.append(f"{label}: status={result.status!r}，期望 {expected_status!r}")
        elif expected_value is None:
            if result.raw_value is not None:
                wrong.append(f"{label}: raw_value={result.raw_value!r}，期望 None")
        elif result.raw_value != expected_value:
            wrong.append(
                f"{label}: raw_value={result.raw_value!r}，期望 {expected_value!r}"
            )
        if unit is not None and result.unit != unit:
            wrong.append(f"{label}: unit={result.unit!r}，期望 {unit!r}")
    assert not wrong, "股息率边界状态未按预期:\n" + "\n".join(wrong)


# ===========================================================================
# 来源：tests/unit/test_normalized_dataset_dividends.py（1 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# NormalizedDataset 分红事件契约测试。"""
#


ND_SHANGHAI = ZoneInfo("Asia/Shanghai")


NORMALIZED_DATASET_AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=ND_SHANGHAI)


def test_normalized_dataset_supports_dividend_events() -> None:
    """NormalizedDataset 默认 dividend_events 为空元组，并支持载入 DividendEvent。"""
    ds_empty = NormalizedDataset(dataset="test", as_of=NORMALIZED_DATASET_AS_OF)
    assert ds_empty.dividend_events == ()

    event = DividendEvent(
        symbol="601398.SH",
        announcement_date=date(2026, 6, 25),
        registration_date=date(2026, 7, 15),
        ex_date=date(2026, 7, 16),
        implementation_status="实施",
        cash_dividend_per_10_shares=3.06,
        currency="CNY",
        available_at=NORMALIZED_DATASET_AS_OF,
        source_text="10派3.06元",
    )

    ds_with_events = NormalizedDataset(
        dataset="test",
        as_of=NORMALIZED_DATASET_AS_OF,
        dividend_events=(event,),
    )
    assert len(ds_with_events.dividend_events) == 1
    assert ds_with_events.dividend_events[0].symbol == "601398.SH"
    assert ds_with_events.dividend_events[0].cash_dividend_per_10_shares == 3.06
