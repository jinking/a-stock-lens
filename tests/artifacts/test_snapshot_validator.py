"""The independent snapshot validator, proven against corrupted records.

This module is the check on the checks: it shares no code with the production
implementation, so a systemic mistake inside `astock_lens` cannot hide from it
(`tests/artifacts/README.md`). The validator is fed deliberately corrupted
records first — a validator that has never been seen failing cannot be trusted
passing — and only then run against the real records the canonical analysis
flow computes.

CANDIDATE 的跨快照一致性（引用的策略与因子是否真的存在）由 Task 8 的
`validate_snapshot_set` 负责，所以这里只校验分析链直接产出的三类快照。
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from artifacts.validator import ArtifactFinding, validate_snapshot
from astock_lens.data.snapshots.store import JsonSnapshotStore, SnapshotStore
from astock_lens.domain.enums import SnapshotKind
from astock_lens.factors.config import load_factor_config
from astock_lens.pipelines.analysis import run_analysis
from astock_lens.strategies.config import load_strategy_config
from astock_lens.strategies.registry import RegisteredStrategy, build_scanner

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LONG_DATASET = "daily_bars_long"

KNOWN_FACTORS = {path.stem for path in (ROOT / "configs" / "factors").glob("*.yaml")}


from astock_lens.universe.config import load_universe_config


def _factor_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "symbol": "600000.SH",
        "factor": "ret_20d",
        "as_of": AS_OF.isoformat(),
        "status": "VALUE",
        "factor_version": "v1",
        "lineage": {"factor_version": "v1"},
    }
    record.update(overrides)
    return record


def _strategy_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "symbol": "600000.SH",
        "strategy_id": "momentum",
        "as_of": AS_OF.isoformat(),
        "eligible": True,
        "score": 80.0,
        "rank_percentile": 0.9,
        "contributions": (),
        "reasons": (),
        "risks": (),
        "lineage": {"strategy_version": "v1"},
    }
    record.update(overrides)
    return record


def _candidate_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "symbol": "600000.SH",
        "as_of": AS_OF.isoformat(),
        "next_action": "WATCH",
        "reasons": (),
        "risks": (),
        "lineage": {
            "strategy_version": "v1",
            "universe_snapshot": "2026-09-04:abc",
        },
        "strategy_results": [_strategy_record()],
    }
    record.update(overrides)
    return record


def _checks(findings: tuple[ArtifactFinding, ...]) -> list[str]:
    return [finding.check for finding in findings]


def test_a_missing_required_key_is_reported() -> None:
    findings = validate_snapshot("FACTOR", [{"symbol": "600000.SH"}], as_of=AS_OF)

    assert "required_keys" in _checks(findings)


def test_an_out_of_range_score_is_reported() -> None:
    findings = validate_snapshot(
        "STRATEGY", [_strategy_record(score=150.0)], as_of=AS_OF
    )

    assert "score_range" in _checks(findings)


def test_a_missing_score_is_not_a_range_finding() -> None:
    """`score` may legitimately be `None`; absence is not a violation."""
    findings = validate_snapshot(
        "STRATEGY", [_strategy_record(score=None, rank_percentile=None)], as_of=AS_OF
    )

    assert "score_range" not in _checks(findings)
    assert "rank_percentile_range" not in _checks(findings)


def test_an_out_of_range_rank_percentile_is_reported() -> None:
    findings = validate_snapshot(
        "STRATEGY", [_strategy_record(rank_percentile=1.5)], as_of=AS_OF
    )

    assert "rank_percentile_range" in _checks(findings)


def test_an_unknown_factor_name_is_reported() -> None:
    findings = validate_snapshot(
        "FACTOR",
        [_factor_record(factor="made_up")],
        as_of=AS_OF,
        known_factor_names=KNOWN_FACTORS,
    )

    assert "unknown_factor" in _checks(findings)


def test_an_unknown_strategy_id_is_reported() -> None:
    findings = validate_snapshot(
        "STRATEGY",
        [_strategy_record(strategy_id="moonshot")],
        as_of=AS_OF,
        known_strategy_ids={"momentum"},
    )

    assert "unknown_strategy" in _checks(findings)


def test_an_empty_version_is_reported() -> None:
    findings = validate_snapshot(
        "FACTOR",
        [_factor_record(lineage={"factor_version": ""})],
        as_of=AS_OF,
    )

    assert "empty_version" in _checks(findings)


def test_a_naive_timestamp_is_reported() -> None:
    findings = validate_snapshot(
        "FACTOR",
        [_factor_record(as_of="2026-09-04T15:00:00")],
        as_of=AS_OF,
    )

    assert "timestamp" in _checks(findings)


def test_a_timestamp_after_the_snapshot_is_reported() -> None:
    late = (AS_OF + timedelta(days=1)).isoformat()
    findings = validate_snapshot("FACTOR", [_factor_record(as_of=late)], as_of=AS_OF)

    assert "timestamp" in _checks(findings)


def test_a_candidate_citing_a_mismatched_strategy_version_is_reported() -> None:
    findings = validate_snapshot(
        "CANDIDATE",
        [
            _candidate_record(
                lineage={
                    "strategy_version": "v2",
                    "universe_snapshot": "2026-09-04:abc",
                }
            )
        ],
        as_of=AS_OF,
    )

    assert "cited_strategy_version" in _checks(findings)


def test_clean_records_produce_no_findings() -> None:
    findings = (
        validate_snapshot(
            "FACTOR", [_factor_record()], as_of=AS_OF, known_factor_names=KNOWN_FACTORS
        )
        + validate_snapshot(
            "STRATEGY",
            [_strategy_record()],
            as_of=AS_OF,
            known_strategy_ids={"momentum"},
        )
        + validate_snapshot("CANDIDATE", [_candidate_record()], as_of=AS_OF)
        + validate_snapshot(
            "UNIVERSE",
            [
                {
                    "as_of": AS_OF.isoformat(),
                    "snapshot_id": "2026-09-04:abc",
                    "config_digest": "abc",
                    "lineage": {"universe_snapshot": "2026-09-04:abc"},
                    "included": ["600000.SH"],
                    "exclusions": [],
                    "deferred_rules": [],
                }
            ],
            as_of=AS_OF,
        )
    )

    assert findings == ()


def test_findings_name_the_symbol_and_the_observation() -> None:
    findings = validate_snapshot(
        "STRATEGY", [_strategy_record(score=150.0)], as_of=AS_OF
    )

    assert findings
    assert all(finding.symbol == "600000.SH" for finding in findings)
    assert all(finding.observed for finding in findings)


def test_real_snapshots_from_the_analysis_flow_validate_cleanly(
    local_tmp: Path,
) -> None:
    """The validator's purpose: judge what the analysis chain actually
    produced, without sharing a single line of its implementation."""
    config = load_strategy_config(ROOT / "configs" / "strategies" / "momentum.yaml")
    analysis = run_analysis(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=load_universe_config(ROOT / "configs" / "universe.yaml"),
        factor_configs=tuple(
            load_factor_config(path)
            for path in sorted((ROOT / "configs" / "factors").glob("*.yaml"))
        ),
        scanners=(RegisteredStrategy(config=config, plugin=build_scanner(config)),),
        dataset=LONG_DATASET,
    )

    store: SnapshotStore = JsonSnapshotStore(local_tmp)
    store.write(SnapshotKind.UNIVERSE, AS_OF, (analysis.universe,))
    store.write(SnapshotKind.FACTOR, AS_OF, analysis.factor_results)
    store.write(SnapshotKind.STRATEGY, AS_OF, analysis.strategy_results)

    findings: tuple[ArtifactFinding, ...] = ()
    for kind in (
        SnapshotKind.UNIVERSE,
        SnapshotKind.FACTOR,
        SnapshotKind.STRATEGY,
    ):
        findings += validate_snapshot(
            kind.value,
            store.read(kind, AS_OF),
            as_of=AS_OF,
            known_factor_names=KNOWN_FACTORS,
            known_strategy_ids={"momentum"},
        )

    assert findings == ()
