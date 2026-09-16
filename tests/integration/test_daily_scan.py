"""End-to-end test for the daily scan.

One call drives the full chain the design names:

    NORMALIZE → BUILD_UNIVERSE → COMPUTE_FACTORS → RUN_STRATEGIES
        → BUILD_CANDIDATES → snapshots

over the long fixture, whose securities exist to make each Universe rule
observable (see `scripts/generate_fixtures.py` for the per-row intent).

The expected ranking is hand-computed from the fixture's formulas, not from
running the implementation: every symbol's price follows close = base ×
(1 + rate)^i, so ret_20d and ret_60d order strictly by `rate`, and
proximity_52w_high equals (1 + rate)^5 / 1.2 for the spiked symbols and
1 / 1.01 for 000006.SZ, whose spike ratio is 1.0 — its yearly high is simply
the last day. With equal weights the blend preserves that order except that
000006.SZ jumps to third on proximity:

    300750.SZ > 600000.SH > 000006.SZ > 830799.BJ
        > 600519.SH > 900948.SH > 000001.SZ
"""

from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import SnapshotKind
from astock_lens.factors.config import load_factor_config
from astock_lens.pipelines.daily_scan import DailyScanResult, run_daily_scan
from astock_lens.strategies.config import load_strategy_config
from astock_lens.universe.config import load_universe_config
from astock_lens.universe.models import UniverseRule

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LONG_DATASET = "daily_bars_long"

EXPECTED_RANKING = (
    "300750.SZ",
    "600000.SH",
    "000006.SZ",
    "830799.BJ",
    "600519.SH",
    "900948.SH",
    "000001.SZ",
)

# One rule per excluded symbol, exactly as the fixture intends.
EXPECTED_EXCLUSIONS: dict[str, tuple[UniverseRule, ...]] = {
    "000002.SZ": (UniverseRule.ST,),
    "000003.SZ": (UniverseRule.DELISTING_BOARD,),
    "000004.SZ": (UniverseRule.SHORT_LISTING,),
    "000005.SZ": (UniverseRule.LOW_LIQUIDITY,),
    "000007.SZ": (UniverseRule.NO_MARKET_DATA, UniverseRule.NO_LIQUIDITY_MEASURE),
}


def _run(local_tmp: Path) -> DailyScanResult:
    return run_daily_scan(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=load_universe_config(ROOT / "configs" / "universe.yaml"),
        factor_configs=tuple(
            load_factor_config(path)
            for path in sorted((ROOT / "configs" / "factors").glob("*.yaml"))
        ),
        strategy_config=load_strategy_config(
            ROOT / "configs" / "strategies" / "momentum.yaml"
        ),
        store=JsonSnapshotStore(local_tmp),
        dataset=LONG_DATASET,
    )


def _rules(result: DailyScanResult, symbol: str) -> tuple[UniverseRule, ...]:
    return tuple(
        exclusion.rule
        for exclusion in result.universe.exclusions
        if exclusion.symbol == symbol
    )


def test_every_designed_exclusion_fires_on_its_symbol(local_tmp: Path) -> None:
    result = _run(local_tmp)

    for symbol, rules in EXPECTED_EXCLUSIONS.items():
        assert _rules(result, symbol) == rules, symbol


def test_the_deferred_suspension_rule_is_reported_not_applied(local_tmp: Path) -> None:
    result = _run(local_tmp)

    deferred = {rule.rule for rule in result.universe.deferred_rules}
    assert deferred == {UniverseRule.LONG_SUSPENSION}
    # 000006.SZ has been suspended for ages, but the rule has no threshold:
    # excluding it on a number nobody reviewed is exactly the guess the
    # deferred-rule contract exists to prevent.
    assert "000006.SZ" in result.universe.included


def test_the_ranking_matches_the_hand_computed_order(local_tmp: Path) -> None:
    result = _run(local_tmp)

    scored = sorted(
        (
            (item.symbol, item.score)
            for item in result.strategy_results
            if item.score is not None
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )

    assert [symbol for symbol, _ in scored] == list(EXPECTED_RANKING)
    # Monotone scores: no tie can hide behind the sort.
    assert all(later[1] < earlier[1] for earlier, later in pairwise(scored))


def test_next_action_follows_the_ordering_rule(local_tmp: Path) -> None:
    """D5: eligible with a measured score is WATCH; nothing else is."""
    result = _run(local_tmp)

    assert {candidate.symbol for candidate in result.candidates} == set(
        EXPECTED_RANKING
    )
    assert all(
        candidate.next_action.value == "WATCH" for candidate in result.candidates
    )


def test_only_universe_symbols_enter_the_strategies(local_tmp: Path) -> None:
    """A symbol the Universe excluded must not be scored behind its back."""
    result = _run(local_tmp)

    assert {item.symbol for item in result.strategy_results} == set(
        result.universe.included
    )


def test_all_four_snapshots_are_written(local_tmp: Path) -> None:
    _run(local_tmp)

    for kind in (
        SnapshotKind.UNIVERSE,
        SnapshotKind.FACTOR,
        SnapshotKind.STRATEGY,
        SnapshotKind.CANDIDATE,
    ):
        assert (local_tmp / kind.value / "2026-09-04.json").is_file(), kind


def test_a_second_run_for_the_same_date_overwrites_not_duplicates(
    local_tmp: Path,
) -> None:
    store = JsonSnapshotStore(local_tmp)
    first = _run(local_tmp)
    second = _run(local_tmp)

    assert first.candidate_snapshot_path == second.candidate_snapshot_path
    assert store.dates(SnapshotKind.CANDIDATE) == ("2026-09-04",)
    assert len(store.read(SnapshotKind.CANDIDATE, AS_OF)) == len(second.candidates)
    assert len(store.read(SnapshotKind.STRATEGY, AS_OF)) == len(second.strategy_results)
