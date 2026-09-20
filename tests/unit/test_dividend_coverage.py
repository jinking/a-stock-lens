"""分红事件覆盖审计测试 (Plan B Task 4).

验证：
- 分母必须显式来自研究池（空名单抛出 ValueError）；
- 预案与实施事件严格分开统计；
- 各覆盖统计（任意事件、已实施现金分红、除权日、登记日）精确吻合；
- 能够确定性渲染 JSON 与 Markdown 格式报告；
- 证明审计过程严格只读。
"""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from astock_lens.calibration.dividend_coverage import (
    audit_dividend_coverage,
    render_dividend_coverage_json,
    render_dividend_coverage_markdown,
)
from astock_lens.data.dividends.models import DividendEvent

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=SHANGHAI)


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
        available_at=datetime(2026, 6, 20, 15, 0, tzinfo=SHANGHAI),
        source_text="source row",
    )


def test_explicit_universe_denominator_required() -> None:
    """Step 1: 分母必须显式给出，空名单必须抛错。"""
    with pytest.raises(ValueError, match="分母"):
        audit_dividend_coverage(events=(), universe=(), as_of=AS_OF)


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

    report = audit_dividend_coverage(events=events, universe=universe, as_of=AS_OF)

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
    report = audit_dividend_coverage(events=events, universe=universe, as_of=AS_OF)

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
