"""交易纪律描述性统计，不推断因果关系。"""

from collections.abc import Sequence

from astock_lens.domain.models import DomainRecord
from astock_lens.trade_gate.models import ExecutionRecord, TradeReview


class DisciplineGroup(DomainRecord):
    count: int
    reviewed: int
    win_rate: float | None
    avg_pnl_pct: float | None


class TradeDisciplineSummary(DomainRecord):
    eligible_executions: int
    override_executions: int
    override_rate: float
    pass_group: DisciplineGroup
    overridden_group: DisciplineGroup


def summarize_trade_discipline(
    executions: Sequence[ExecutionRecord], reviews: Sequence[TradeReview]
) -> TradeDisciplineSummary:
    by_execution = {review.execution_id: review for review in reviews}
    passed = [e for e in executions if e.discipline_status == "PASS"]
    overridden = [e for e in executions if e.discipline_status == "OVERRIDDEN"]

    def group(items: list[ExecutionRecord]) -> DisciplineGroup:
        reviewed = [by_execution[item.id] for item in items if item.id in by_execution]
        return DisciplineGroup(
            count=len(items),
            reviewed=len(reviewed),
            win_rate=(
                sum(review.pnl_pct > 0 for review in reviewed) / len(reviewed)
                if reviewed
                else None
            ),
            avg_pnl_pct=(
                sum(review.pnl_pct for review in reviewed) / len(reviewed)
                if reviewed
                else None
            ),
        )

    return TradeDisciplineSummary(
        eligible_executions=len(executions),
        override_executions=len(overridden),
        override_rate=len(overridden) / len(executions) if executions else 0.0,
        pass_group=group(passed),
        overridden_group=group(overridden),
    )
