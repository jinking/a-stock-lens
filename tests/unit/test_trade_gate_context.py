from datetime import UTC, datetime

from astock_lens.domain.enums import SnapshotKind
from astock_lens.trade_gate.context import (
    TradeContextBuilder,
    TradeGateSnapshotNotPublishedError,
)
from astock_lens.trade_gate.models import TradeMarketOverlay

NOW = datetime(2026, 9, 22, tzinfo=UTC)


class Store:
    def __init__(self, candidate=()) -> None:
        self.candidate = candidate

    def read(self, kind, as_of):
        return self.candidate if kind is SnapshotKind.CANDIDATE else ()

    def dates(self, kind):
        return (NOW.date().isoformat(),) if kind is SnapshotKind.CANDIDATE else ()


def test_eod_snapshot_does_not_invent_intraday_facts() -> None:
    context = TradeContextBuilder(Store()).build(symbol="603991.SH", as_of=NOW)
    assert context.overlay is None
    assert context.stock_return_1d is None
    assert context.sector_return_1d is None
    assert context.confirmation_met is None
    assert context.candidate_status == "not_selected"


def test_overlay_facts_are_explicitly_carried() -> None:
    overlay = TradeMarketOverlay(
        captured_at=NOW,
        stock_return_1d=0.01,
        sector_return_1d=0.02,
        confirmation_met=True,
    )
    context = TradeContextBuilder(Store()).build(
        symbol="603991.SH", as_of=NOW, overlay=overlay
    )
    assert context.stock_return_1d == 0.01
    assert context.confirmation_met is True


def test_missing_all_snapshots_is_distinguished() -> None:
    class EmptyStore(Store):
        def dates(self, kind):
            return ()

    try:
        TradeContextBuilder(EmptyStore()).build(symbol="603991.SH", as_of=NOW)
    except TradeGateSnapshotNotPublishedError:
        pass
    else:
        raise AssertionError("missing snapshot should be explicit")
