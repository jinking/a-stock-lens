"""分红事件覆盖审计：在显式研究池分母上，核对分红事件的覆盖率与状态分布。

红线纪律：
1. 分母必须是显式传入的研究池名单，严禁使用已落地标的作为分母；
2. 预案与实施事件严格分开统计，严禁自动升格；
3. 本模块只读：不修改任何数据集、不计算 TTM 股息率、不输出推荐结论。
"""

import json
from collections.abc import Sequence
from datetime import datetime

from astock_lens.data.dividends.models import DividendEvent
from astock_lens.domain.models import DomainRecord


class DividendCoverageReport(DomainRecord):
    """分红事件在研究池分母上的覆盖审计报告。"""

    as_of: datetime
    universe_size: int
    symbols_with_any_event: int
    symbols_with_implemented_cash_event: int
    symbols_with_ex_date: int
    symbols_with_registration_date: int
    event_count: int
    proposal_count: int
    implemented_count: int
    missing_symbols: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        """输出适合 JSON 序列化的字典。"""
        return self.model_dump(mode="json")


def audit_dividend_coverage(
    events: Sequence[DividendEvent],
    universe: Sequence[str],
    as_of: datetime,
) -> DividendCoverageReport:
    """在显式研究池分母上核对分红派息事件的覆盖情况。"""
    symbols = tuple(dict.fromkeys(universe))
    if not symbols:
        raise ValueError(
            "分红覆盖审计需要显式的研究池分母名单；分母不能为空，"
            "拿已落地的标的当分母会把覆盖率算成 100%，那是假覆盖"
        )

    universe_set = set(symbols)
    valid_events = [
        ev for ev in events if ev.symbol in universe_set and ev.available_at <= as_of
    ]

    symbols_with_any = {ev.symbol for ev in valid_events}
    symbols_with_implemented_cash = {
        ev.symbol
        for ev in valid_events
        if "实施" in ev.implementation_status
        and ev.cash_dividend_per_10_shares is not None
        and ev.cash_dividend_per_10_shares > 0
    }
    symbols_with_ex_date = {ev.symbol for ev in valid_events if ev.ex_date is not None}
    symbols_with_reg_date = {
        ev.symbol for ev in valid_events if ev.registration_date is not None
    }

    proposal_count = sum(1 for ev in valid_events if "预案" in ev.implementation_status)
    implemented_count = sum(
        1 for ev in valid_events if "实施" in ev.implementation_status
    )
    missing = tuple(s for s in symbols if s not in symbols_with_any)

    return DividendCoverageReport(
        as_of=as_of,
        universe_size=len(symbols),
        symbols_with_any_event=len(symbols_with_any),
        symbols_with_implemented_cash_event=len(symbols_with_implemented_cash),
        symbols_with_ex_date=len(symbols_with_ex_date),
        symbols_with_registration_date=len(symbols_with_reg_date),
        event_count=len(valid_events),
        proposal_count=proposal_count,
        implemented_count=implemented_count,
        missing_symbols=missing,
    )


def render_dividend_coverage_json(report: DividendCoverageReport) -> str:
    """确定性渲染 JSON 格式的分红覆盖报告。"""
    return json.dumps(report.to_payload(), ensure_ascii=False, indent=2) + "\n"


def render_dividend_coverage_markdown(report: DividendCoverageReport) -> str:
    """确定性渲染 Markdown 格式的分红覆盖报告。"""
    u_size = report.universe_size
    any_ratio = report.symbols_with_any_event / u_size if u_size else 0.0
    cash_ratio = report.symbols_with_implemented_cash_event / u_size if u_size else 0.0
    ex_ratio = report.symbols_with_ex_date / u_size if u_size else 0.0
    reg_ratio = report.symbols_with_registration_date / u_size if u_size else 0.0

    lines: list[str] = [
        "# 分红事件覆盖审计报告",
        "",
        f"- **基准时间 (as_of)**: `{report.as_of.isoformat()}`",
        f"- **研究池分母 (universe_size)**: `{u_size}`",
        "",
        "## 1. 覆盖率指标",
        "",
        "| 指标 | 标的数 | 覆盖率 | 说明 |",
        "| :--- | :---: | :---: | :--- |",
        f"| 有任意分红事件 | {report.symbols_with_any_event} | {any_ratio:.2%} | 至少有一条分红记录（含预案） |",
        f"| 有已实施现金分红 | {report.symbols_with_implemented_cash_event} | {cash_ratio:.2%} | 状态为实施且每10股派息>0 |",
        f"| 具备除权除息日 | {report.symbols_with_ex_date} | {ex_ratio:.2%} | 记录包含明确的 ex_date |",
        f"| 具备股权登记日 | {report.symbols_with_registration_date} | {reg_ratio:.2%} | 记录包含明确的 registration_date |",
        "",
        "## 2. 事件状态分布",
        "",
        f"- **有效事件总数**: {report.event_count}",
        f"- **预案事件数**: {report.proposal_count}",
        f"- **已实施事件数**: {report.implemented_count}",
        "",
        "## 3. 缺失分红事件标的",
        "",
        f"- **缺失标的数**: {len(report.missing_symbols)} / {u_size}",
    ]

    if report.missing_symbols:
        lines.append("")
        sample_missing = report.missing_symbols[:30]
        lines.append(f"示例缺口标的（展示前 {len(sample_missing)} 只）：")
        lines.append("`" + ", ".join(sample_missing) + "`")
        if len(report.missing_symbols) > 30:
            lines.append(f"*(剩余 {len(report.missing_symbols) - 30} 只省略)*")
    else:
        lines.append("- 全部标的均有分红事件记录。")

    lines.append("")
    return "\n".join(lines)
