"""Integration tests for `astock today` CLI command.

Plan: docs/superpowers/plans/2026-09-21-candidate-today-query-experience.md Task 4
Spec: docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md
"""

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from astock_lens.candidates.models import Candidate
from astock_lens.cli.app import app
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import MarketValidation, NextAction, Signal, SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

runner = CliRunner()
AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


def _make_candidate(
    symbol: str,
    *,
    primary_strategy_id: str = "momentum",
    qualified_strategies: tuple[str, ...] = ("momentum",),
    market_validation: MarketValidation | None = MarketValidation.CONFIRMED,
    signal: Signal | None = Signal.BREAKOUT,
    next_action: NextAction = NextAction.WATCH,
    risks: tuple[str, ...] = (),
) -> Candidate:
    quals = tuple(
        StrategyQualification(
            symbol=symbol,
            strategy_id=s_id,
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=0.95,
            as_of=AS_OF,
        )
        for s_id in qualified_strategies
    )
    s_results = tuple(
        StrategyResult(
            symbol=symbol,
            strategy_id=s_id,
            strategy_version="v1",
            as_of=AS_OF,
            eligible=True,
            score=88.0,
            rank_percentile=0.95,
            lineage=SnapshotLineage(strategy_version="v1"),
        )
        for s_id in qualified_strategies
    )
    return Candidate(
        symbol=symbol,
        as_of=AS_OF,
        next_action=next_action,
        lineage=SnapshotLineage(
            strategy_version="v1",
            qualification_version="v1",
            candidate_policy_version="v1",
            regime_version="v1",
            market_validation_version="v1",
            signal_version="v1",
            universe_snapshot="2026-09-19:u1",
        ),
        primary_strategy_id=primary_strategy_id,
        strategy_qualifications=quals,
        strategy_results=s_results,
        market_validation=market_validation,
        signal=signal,
        reasons=(f"qualified for {primary_strategy_id}",),
        risks=risks,
    )


def test_today_cli_missing_snapshot_fails_explicitly(
    local_tmp: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(local_tmp / "snapshots"))
    result = runner.invoke(app, ["today", "--as-of", "2026-09-01"])
    assert result.exit_code != 0
    assert "no CANDIDATE snapshot for 2026-09-01" in result.output


def test_today_cli_empty_snapshot_exits_zero(local_tmp: Path, monkeypatch) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)
    store.write(SnapshotKind.CANDIDATE, AS_OF, [])
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))

    result = runner.invoke(app, ["today", "--as-of", "2026-09-19"])
    assert result.exit_code == 0
    assert "candidates: 0" in result.output


def test_today_cli_exact_aggregation_and_top_order(
    local_tmp: Path, monkeypatch
) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)

    candidates = [
        _make_candidate(
            "601336.SH",
            primary_strategy_id="value",
            qualified_strategies=("value", "garp"),
            market_validation=MarketValidation.NEUTRAL,
            signal=Signal.VALUE_CONTRARIAN,
        ),
        _make_candidate(
            "300741.SZ",
            primary_strategy_id="momentum",
            market_validation=MarketValidation.CONFIRMED,
            signal=Signal.BREAKOUT,
        ),
        _make_candidate(
            "688617.SH",
            primary_strategy_id="growth",
            market_validation=MarketValidation.NEUTRAL,
            signal=Signal.TREND_WEAKEN,
            risks=("技术信号提示走弱风险 (TREND_WEAKEN)",),
        ),
    ]
    store.write(SnapshotKind.CANDIDATE, AS_OF, candidates)
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))

    result = runner.invoke(app, ["today", "--as-of", "2026-09-19"])
    assert result.exit_code == 0
    output = result.output

    # 验证关键聚合数字与分类
    assert "candidates: 3" in output
    assert "value: 1" in output
    assert "momentum: 1" in output
    assert "growth: 1" in output
    assert "CONFIRMED: 1" in output
    assert "NEUTRAL: 2" in output
    assert "VALUE_CONTRARIAN: 1" in output
    assert "BREAKOUT: 1" in output
    assert "TREND_WEAKEN: 1" in output

    # 验证 Top 列表保持原生存储顺序
    idx_val = output.find("601336.SH")
    idx_mom = output.find("300741.SZ")
    idx_gro = output.find("688617.SH")
    assert idx_val != -1 and idx_mom != -1 and idx_gro != -1
    assert idx_val < idx_mom < idx_gro


def test_today_cli_is_strictly_read_only(local_tmp: Path, monkeypatch) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)
    c = _make_candidate("600519.SH")
    store.write(SnapshotKind.CANDIDATE, AS_OF, [c])
    snap_file = store.path_for(SnapshotKind.CANDIDATE, AS_OF)
    initial_bytes = snap_file.read_bytes()
    initial_mtime = snap_file.stat().st_mtime_ns

    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))
    result = runner.invoke(app, ["today", "--as-of", "2026-09-19"])
    assert result.exit_code == 0

    assert snap_file.read_bytes() == initial_bytes
    assert snap_file.stat().st_mtime_ns == initial_mtime
