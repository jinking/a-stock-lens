"""只读正式快照构建 Trade Context，不访问 Provider 或重跑 Pipeline。"""

from datetime import datetime

from astock_lens.candidates.models import Candidate
from astock_lens.data.snapshots.store import SnapshotStore
from astock_lens.domain.enums import DataStatus, SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.trade_gate.models import TradeContext, TradeMarketOverlay


class TradeGateSnapshotNotPublishedError(ValueError):
    """Trade Context 缺少指定日期的正式快照。"""


class TradeContextBuilder:
    def __init__(self, store: SnapshotStore) -> None:
        self._store = store

    def build(
        self, *, symbol: str, as_of: datetime, overlay: TradeMarketOverlay | None = None
    ) -> TradeContext:
        factor_rows = self._store.read(SnapshotKind.FACTOR, as_of)
        strategy_rows = self._store.read(SnapshotKind.STRATEGY, as_of)
        candidate_rows = self._store.read(SnapshotKind.CANDIDATE, as_of)
        factors = tuple(
            FactorResult.model_validate(row)
            for row in factor_rows
            if row.get("symbol") == symbol
        )
        strategies = tuple(
            StrategyResult.model_validate(row)
            for row in strategy_rows
            if row.get("symbol") == symbol
        )
        candidates = tuple(
            Candidate.model_validate(row)
            for row in candidate_rows
            if row.get("symbol") == symbol
        )
        candidate = candidates[0] if candidates else None
        candidate_published = as_of.date().isoformat() in self._store.dates(
            SnapshotKind.CANDIDATE
        )
        snapshot_dates = {
            kind: as_of.date().isoformat() in self._store.dates(kind)
            for kind in (
                SnapshotKind.FACTOR,
                SnapshotKind.STRATEGY,
                SnapshotKind.CANDIDATE,
            )
        }
        if not any(snapshot_dates.values()):
            raise TradeGateSnapshotNotPublishedError(
                f"no trade context snapshots for {as_of.date()}"
            )
        usable = {
            item.factor: item.raw_value
            for item in factors
            if item.status is DataStatus.VALUE and item.raw_value is not None
        }
        overlay_values = overlay
        return TradeContext(
            symbol=symbol,
            as_of=as_of,
            candidate_status="published"
            if candidate
            else ("not_selected" if candidate_published else "not_published"),
            candidate=candidate,
            factor_results=factors,
            strategy_results=strategies,
            market_validation=candidate.market_validation if candidate else None,
            signal=candidate.signal if candidate else None,
            lineage=candidate.lineage if candidate else SnapshotLineage(),
            overlay=overlay,
            ret_20d=usable.get("ret_20d"),
            ret_60d=usable.get("ret_60d"),
            volume_ratio_5_20=usable.get("volume_ratio_5_20"),
            relative_strength_60d=usable.get("relative_strength_60d"),
            stock_return_1d=overlay_values.stock_return_1d if overlay_values else None,
            sector_return_1d=overlay_values.sector_return_1d
            if overlay_values
            else None,
            benchmark_return_1d=overlay_values.benchmark_return_1d
            if overlay_values
            else None,
            confirmation_met=overlay_values.confirmation_met
            if overlay_values
            else None,
            current_price=overlay_values.current_price if overlay_values else None,
        )
