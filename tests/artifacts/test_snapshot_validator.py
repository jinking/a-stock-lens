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

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from artifacts.validator import (
    ArtifactFinding,
    validate_snapshot,
    validate_snapshot_set,
)
from astock_lens.data.snapshots.store import JsonSnapshotStore, SnapshotStore
from astock_lens.domain.enums import SnapshotKind
from astock_lens.factors.config import load_factor_config
from astock_lens.pipelines.analysis import compute_factor_state, run_analysis
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
        "candidate_policy_version": "v1",
        "strategy_qualifications": [
            {
                "symbol": "600000.SH",
                "strategy_id": "momentum",
                "qualified": True,
                "percentile_floor": 0.90,
                "as_of": AS_OF.isoformat(),
                "lineage": {"qualification_version": "v1"},
            }
        ],
        "market_validation": None,
        "signal": None,
        "lineage": {
            "strategy_version": "v1",
            "qualification_version": "v1",
            "candidate_policy_version": "v1",
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


# --- point-in-time evidence --------------------------------------------------


def _input_ref(**overrides: object) -> dict[str, object]:
    ref: dict[str, object] = {
        "metric": "net_operating_cashflow_ttm",
        "report_period": "2026-06-30",
        "announce_date": "2026-08-15",
        "available_at": "2026-08-15T15:00:00+00:00",
        "value": 120.0,
    }
    ref.update(overrides)
    return ref


def _factor_with_input(ref: dict[str, object]) -> dict[str, object]:
    return _factor_record(inputs=[ref])


def test_a_cited_input_with_an_availability_time_is_clean() -> None:
    findings = validate_snapshot(
        "FACTOR", [_factor_with_input(_input_ref())], as_of=AS_OF
    )

    assert findings == ()


def test_input_evidence_without_an_availability_time_is_a_finding() -> None:
    """有报告期却没有可用时刻，快照就无法自证没有前视。"""
    ref = _input_ref()
    del ref["available_at"]

    findings = validate_snapshot("FACTOR", [_factor_with_input(ref)], as_of=AS_OF)

    assert "available_at" in _checks(findings)


def test_a_future_available_at_is_a_finding() -> None:
    """证据的可用时刻晚于计算时点，就是前视。"""
    findings = validate_snapshot(
        "FACTOR",
        [_factor_with_input(_input_ref(available_at="2026-09-05T15:00:00+00:00"))],
        as_of=AS_OF,
    )

    assert "available_at" in _checks(findings)


def test_a_naive_available_at_is_a_finding() -> None:
    """没有时区的时间戳无法与任何时点比较。"""
    findings = validate_snapshot(
        "FACTOR",
        [_factor_with_input(_input_ref(available_at="2026-08-15T15:00:00"))],
        as_of=AS_OF,
    )

    assert "available_at" in _checks(findings)


def test_an_empty_reference_is_not_asked_for_an_availability_time() -> None:
    """`metric` 单独出现表示"这条证据不存在"，它没有时间可写。"""
    findings = validate_snapshot(
        "FACTOR",
        [_factor_with_input({"metric": "peg"})],
        as_of=AS_OF,
    )

    assert findings == ()


# --- cross-snapshot consistency ---------------------------------------------


def _strategy_record_for(
    symbol: str, *, strategy_id: str = "momentum", factor: str = "ret_20d"
) -> dict[str, object]:
    record = _strategy_record()
    record["symbol"] = symbol
    record["strategy_id"] = strategy_id
    record["factor_snapshot"] = [
        {
            "symbol": symbol,
            "factor": factor,
            "as_of": AS_OF.isoformat(),
            "status": "VALUE",
            "factor_version": "v1",
            "lineage": {"factor_version": "v1"},
            "raw_value": 1.0,
        }
    ]
    return record


def _candidate_for_set(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "as_of": AS_OF.isoformat(),
        "next_action": "WATCH",
        "lineage": {"factor_version": "v1", "strategy_version": "v1"},
        "strategy_results": [_strategy_record_for(symbol)],
        "reasons": [],
        "risks": [],
    }


def test_a_clean_snapshot_set_produces_no_findings() -> None:
    findings = validate_snapshot_set(
        factor_records=[_factor_with_input(_input_ref())],
        strategy_records=[_strategy_record_for("600000.SH")],
        candidate_records=[_candidate_for_set("600000.SH")],
        as_of=AS_OF,
    )

    assert findings == ()


def test_a_candidate_citing_an_absent_strategy_is_a_finding() -> None:
    findings = validate_snapshot_set(
        factor_records=[_factor_with_input(_input_ref())],
        strategy_records=[],
        candidate_records=[_candidate_for_set("600000.SH")],
        as_of=AS_OF,
    )

    assert "cross_snapshot" in _checks(findings)
    assert any("momentum" in finding.observed for finding in findings)


def test_a_candidate_citing_an_absent_factor_is_a_finding() -> None:
    findings = validate_snapshot_set(
        factor_records=[],
        strategy_records=[_strategy_record_for("600000.SH")],
        candidate_records=[_candidate_for_set("600000.SH")],
        as_of=AS_OF,
    )

    assert "cross_snapshot" in _checks(findings)
    assert any("ret_20d" in finding.observed for finding in findings)


def test_a_candidate_citing_a_factor_version_that_was_not_stored_is_a_finding() -> None:
    stored = _factor_record()
    stored["factor"] = "ret_20d"
    stored["factor_version"] = "v1"
    cited = _strategy_record_for("600000.SH")
    cited["factor_snapshot"][0]["factor_version"] = "v2"  # type: ignore[index]
    candidate = _candidate_for_set("600000.SH")
    candidate["strategy_results"] = [cited]

    findings = validate_snapshot_set(
        factor_records=[stored],
        strategy_records=[cited],
        candidate_records=[candidate],
        as_of=AS_OF,
    )

    assert "cross_snapshot" in _checks(findings)


def test_a_clean_snapshot_set_tolerates_an_empty_candidate_list() -> None:
    """当前阶段本该如此：入选规则未批准，当天没有 CANDIDATE 快照。"""
    findings = validate_snapshot_set(
        factor_records=[_factor_with_input(_input_ref())],
        strategy_records=[_strategy_record_for("600000.SH")],
        candidate_records=[],
        as_of=AS_OF,
    )

    assert findings == ()


# --- real evidence, end to end ----------------------------------------------

INCOME_CSV = (
    "code,EndDate,InfoPublDate,OperatingRevenue,ROE,GrossIncomeRatio\n"
    "sh600519,2026-06-30,2026-07-20,90703260964.48,17.7179,89.5552\n"
)


def test_real_factor_records_carry_their_own_availability_time(
    local_tmp: Path,
) -> None:
    """真实链路的因子快照必须自己过得了校验器，而不是靠合成记录。

    这里跑的是生产的归一化与因子计算，再由**不共享任何实现**的校验器判它。
    没有这一步，"零 finding" 就只是一句关于合成数据的话。
    """
    for name in ("daily_bars_long.csv", "securities.csv"):
        shutil.copyfile(CSV_ROOT / name, local_tmp / name)
    (local_tmp / "financial_income.csv").write_text(INCOME_CSV, encoding="utf-8")

    measured = compute_factor_state(
        csv_root=local_tmp,
        as_of=AS_OF,
        factor_configs=tuple(
            load_factor_config(path)
            for path in sorted((ROOT / "configs" / "factors").glob("*.yaml"))
        ),
        dataset=LONG_DATASET,
    )
    records = [result.model_dump(mode="json") for result in measured.factor_results]
    cited = [
        ref
        for record in records
        for ref in record.get("inputs", [])
        if isinstance(ref, dict)
    ]

    findings = validate_snapshot(
        "FACTOR", records, as_of=AS_OF, known_factor_names=KNOWN_FACTORS
    )

    assert findings == ()
    # 前提检查：这份快照里确实有需要自证时点的证据，否则上面的零 finding 是空话。
    assert cited
    assert any(ref.get("report_period") for ref in cited)
    assert all(ref.get("available_at") for ref in cited if ref.get("report_period"))


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
