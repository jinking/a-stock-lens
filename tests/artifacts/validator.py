"""Independent snapshot validator.

`tests/artifacts/README.md` is the contract: this module judges the artifacts
the daily scan wrote **without importing any production code** — not the
domain models, not Pydantic validation, nothing from `astock_lens`. Sharing
the implementation's own validation logic would make it blind to that
implementation's systematic errors, which is precisely the failure mode an
independent validator exists to catch.

Every finding names the check, the symbol (empty when the record has none),
and what was observed, so a reader can act on a finding without re-running
anything.

Checks, each traceable to `docs/ARCHITECTURE.md` §20.2:

- `required_keys` — every kind declares the keys a record cannot lack;
- `score_range` / `rank_percentile_range` — when present, within `[0, 100]`
  and `[0, 1]`; a legitimate `None` is not a violation;
- `unknown_factor` / `unknown_strategy` — every factor and strategy reference
  resolves against the names the configuration actually defines;
- `empty_version` — lineage versions are non-empty, so an artifact can always
  say what produced it;
- `timestamp` — every timestamp is timezone-aware and no later than the
  snapshot's `as_of`: a record from the future or of ambiguous time is not
  point-in-time evidence;
- `cited_strategy_version` — a candidate's lineage version equals the version
  on every strategy result it cites.

`validate_job_manifest` checks the other artifact a daily run leaves behind:
the job manifest, whose stages an operator reads to see what actually ran.
Its checks are named the same way, and it shares no code with the pipeline
that wrote it.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "UNIVERSE": frozenset(
        {
            "as_of",
            "snapshot_id",
            "config_digest",
            "lineage",
            "included",
            "exclusions",
            "deferred_rules",
        }
    ),
    "FACTOR": frozenset(
        {"symbol", "factor", "as_of", "status", "factor_version", "lineage"}
    ),
    "STRATEGY": frozenset(
        {
            "symbol",
            "strategy_id",
            "as_of",
            "eligible",
            "score",
            "rank_percentile",
            "lineage",
        }
    ),
    "CANDIDATE": frozenset(
        {
            "symbol",
            "as_of",
            "next_action",
            "primary_strategy_id",
            "lineage",
            "strategy_results",
            "strategy_qualifications",
            "candidate_policy_version",
            "market_validation",
            "signal",
        }
    ),
    "MARKET_REGIME": frozenset(
        {"regime", "as_of", "lineage", "breadth_ratio", "index_trend", "reasons"}
    ),
}

# The version keys whose lineage value must be non-empty, per kind.
VERSION_KEYS: dict[str, tuple[str, ...]] = {
    "UNIVERSE": (),
    "FACTOR": ("factor_version",),
    "STRATEGY": ("strategy_version",),
    "MARKET_REGIME": ("regime_version",),
    "CANDIDATE": (
        "strategy_version",
        "qualification_version",
        "candidate_policy_version",
        "regime_version",
        "market_validation_version",
        "signal_version",
    ),
}

# The eleven stages `spec §15` names, in the order the canonical pipeline runs
# them: factors are measured before the Universe (its liquidity rule consumes
# `avg_amount_20d`), and Candidate is built after the market and signal layers.
JOB_STAGES: tuple[str, ...] = (
    "SYNC_DATA",
    "NORMALIZE",
    "COMPUTE_FACTORS",
    "BUILD_UNIVERSE",
    "RUN_STRATEGIES",
    "DETECT_REGIME",
    "MARKET_VALIDATE",
    "RUN_SIGNALS",
    "BUILD_CANDIDATES",
    "UPDATE_WATCHLIST",
    "GENERATE_DAILY_SNAPSHOT",
)

REQUIRED_JOB_KEYS: frozenset[str] = frozenset(
    {"job_type", "as_of", "status", "started_at"}
)

TERMINAL_JOB_STATUSES: frozenset[str] = frozenset(
    {"SUCCEEDED", "FAILED", "BLOCKED", "SKIPPED"}
)

# Statuses that assert something went wrong, and so must carry the reason.
PROBLEM_JOB_STATUSES: frozenset[str] = frozenset({"FAILED", "BLOCKED"})

MARKET_REGIME_VOCABULARY: frozenset[str] = frozenset(
    {"BULL", "RANGE_UP", "RANGE", "RANGE_DOWN", "BEAR", "EXTREME_VOLATILITY"}
)


@dataclass(frozen=True)
class ArtifactFinding:
    """One thing the validator saw that it cannot vouch for."""

    check: str
    symbol: str
    observed: str


def validate_snapshot(
    kind: str,
    records: Sequence[Mapping[str, object]],
    *,
    as_of: datetime,
    known_factor_names: Collection[str] = (),
    known_strategy_ids: Collection[str] = (),
) -> tuple[ArtifactFinding, ...]:
    """Judge one snapshot's records; return every finding, or `()` when clean.

    An unknown kind produces a finding naming the kind rather than raising:
    a snapshot kind this validator does not know is itself worth reporting.
    """
    findings: list[ArtifactFinding] = []
    required = REQUIRED_KEYS.get(kind)
    if required is None:
        return (
            ArtifactFinding(
                check="known_kind", symbol="", observed=f"unknown kind {kind!r}"
            ),
        )

    if kind == "CANDIDATE" and len(records) > 50:
        findings.append(
            ArtifactFinding(
                check="candidate_count",
                symbol="",
                observed=f"candidate snapshot contains {len(records)} records, exceeding maximum of 50",
            )
        )

    if kind == "MARKET_REGIME" and len(records) != 1:
        findings.append(
            ArtifactFinding(
                check="market_regime_count",
                symbol="",
                observed=f"market regime snapshot contains {len(records)} records, must contain exactly 1",
            )
        )

    seen_symbols: set[str] = set()
    for index, record in enumerate(records):
        symbol = _text(record.get("symbol"))
        if kind == "CANDIDATE" and symbol:
            if symbol in seen_symbols:
                findings.append(
                    ArtifactFinding(
                        check="unique_symbols",
                        symbol=symbol,
                        observed=f"symbol {symbol!r} appears more than once in candidate snapshot",
                    )
                )
            seen_symbols.add(symbol)

        findings.extend(_required_keys(required, record, symbol, index))
        findings.extend(_ranges(kind, record, symbol))
        findings.extend(
            _unknown_references(
                kind, record, symbol, known_factor_names, known_strategy_ids
            )
        )
        findings.extend(_versions(kind, record, symbol))
        findings.extend(_timestamps(kind, record, symbol, as_of))
        findings.extend(_availability_times(kind, record, symbol, as_of))
        findings.extend(_cited_versions(kind, record, symbol))
        findings.extend(_cited_scores(kind, record, symbol))
        findings.extend(_candidate_checks(kind, record, symbol))
        findings.extend(_regime_checks(kind, record, symbol))

    return tuple(findings)


def validate_snapshot_set(
    *,
    factor_records: Sequence[Mapping[str, object]],
    strategy_records: Sequence[Mapping[str, object]],
    candidate_records: Sequence[Mapping[str, object]],
    as_of: datetime,
) -> tuple[ArtifactFinding, ...]:
    """Judge a day's snapshots together: every citation must resolve.

    `validate_snapshot` sees one kind at a time, so it cannot answer the
    question that matters most for a candidate: do the strategies and factors it
    cites actually exist in the same day's snapshots? A candidate assembled from
    evidence that was never stored is unauditable, however well-formed it looks.

    Like the rest of this module, it shares no code with `astock_lens`.
    """
    del as_of  # 每个快照自己的时点由 `validate_snapshot` 负责，这里只看引用能否成链
    findings: list[ArtifactFinding] = []

    stored_strategies = {
        (
            _text(record.get("symbol")),
            _text(record.get("strategy_id")),
            _text(record.get("strategy_version")),
        )
        for record in strategy_records
    }
    stored_factors = {
        (
            _text(record.get("symbol")),
            _text(record.get("factor")),
            _text(record.get("factor_version")),
        )
        for record in factor_records
    }

    for candidate in candidate_records:
        symbol = _text(candidate.get("symbol"))
        for qual in _mappings(candidate.get("strategy_qualifications")):
            if qual.get("qualified") is True:
                strat_id = _text(qual.get("strategy_id"))
                matching = [
                    s for s in stored_strategies if s[0] == symbol and s[1] == strat_id
                ]
                if not matching:
                    findings.append(
                        ArtifactFinding(
                            check="cross_snapshot",
                            symbol=symbol,
                            observed=(
                                f"candidate cites qualified strategy {strat_id!r}, "
                                "which the day's STRATEGY snapshot does not contain"
                            ),
                        )
                    )

        for cited in _cited_results(candidate):
            strategy_key = (
                symbol,
                _text(cited.get("strategy_id")),
                _text(cited.get("strategy_version")),
            )
            if strategy_key not in stored_strategies:
                findings.append(
                    ArtifactFinding(
                        check="cross_snapshot",
                        symbol=symbol,
                        observed=(
                            f"candidate cites strategy {strategy_key[1]!r} "
                            f"{strategy_key[2]!r}, which the day's STRATEGY "
                            "snapshot does not contain"
                        ),
                    )
                )

            for factor in _cited_factors(cited):
                factor_key = (
                    symbol,
                    _text(factor.get("factor")),
                    _text(factor.get("factor_version")),
                )
                if factor_key not in stored_factors:
                    findings.append(
                        ArtifactFinding(
                            check="cross_snapshot",
                            symbol=symbol,
                            observed=(
                                f"candidate cites factor {factor_key[1]!r} "
                                f"{factor_key[2]!r}, which the day's FACTOR "
                                "snapshot does not contain"
                            ),
                        )
                    )

    return tuple(findings)


def validate_job_manifest(
    records: Sequence[Mapping[str, object]],
    *,
    as_of: datetime,
) -> tuple[ArtifactFinding, ...]:
    """Judge one day's job manifest: the record of what actually ran.

    An empty manifest is reported rather than accepted: a date with no stage
    runs means the pipeline never ran, which is a finding about the artifact
    and not a quiet success.
    """
    findings: list[ArtifactFinding] = []

    if not records:
        return (
            ArtifactFinding(
                check="manifest_stages",
                symbol="",
                observed="the manifest carries no stage runs at all",
            ),
        )

    seen: set[str] = set()
    for index, record in enumerate(records):
        stage = _text(record.get("job_type"))
        label = stage or f"record #{index}"
        findings.extend(_job_keys(record, label))
        findings.extend(_job_stage(stage, label))
        findings.extend(_job_duplicate(stage, label, seen))
        findings.extend(_job_status(record, label))
        findings.extend(_job_timestamps(record, label, as_of))

    missing = [stage for stage in JOB_STAGES if stage not in seen]
    if missing:
        findings.append(
            ArtifactFinding(
                check="manifest_stages",
                symbol="",
                observed=f"stages with no run recorded: {', '.join(missing)}",
            )
        )

    return tuple(findings)


def _job_keys(record: Mapping[str, object], label: str) -> list[ArtifactFinding]:
    missing = sorted(REQUIRED_JOB_KEYS - set(record))
    if not missing:
        return []
    return [
        ArtifactFinding(
            check="required_keys",
            symbol=label,
            observed=f"missing keys {missing}",
        )
    ]


def _job_stage(stage: str, label: str) -> list[ArtifactFinding]:
    if not stage or stage in JOB_STAGES:
        return []
    return [
        ArtifactFinding(
            check="known_stage",
            symbol=label,
            observed=f"job_type {stage!r} is not one of the design's stages",
        )
    ]


def _job_duplicate(stage: str, label: str, seen: set[str]) -> list[ArtifactFinding]:
    if not stage:
        return []
    if stage in seen:
        return [
            ArtifactFinding(
                check="duplicate_stage",
                symbol=label,
                observed=f"{stage} appears more than once in one manifest",
            )
        ]
    seen.add(stage)
    return []


def _job_status(record: Mapping[str, object], label: str) -> list[ArtifactFinding]:
    status = _text(record.get("status"))
    findings: list[ArtifactFinding] = []

    if status not in TERMINAL_JOB_STATUSES and status != "RUNNING":
        findings.append(
            ArtifactFinding(
                check="job_status",
                symbol=label,
                observed=f"status {status!r} is not a known job status",
            )
        )
        return findings

    finished = record.get("finished_at")
    if status == "RUNNING" and finished is not None:
        findings.append(
            ArtifactFinding(
                check="job_status",
                symbol=label,
                observed="a RUNNING stage recorded finished_at",
            )
        )
    if status in TERMINAL_JOB_STATUSES and finished is None:
        findings.append(
            ArtifactFinding(
                check="job_status",
                symbol=label,
                observed=f"a {status} stage has no finished_at",
            )
        )

    error = _text(record.get("error"))
    if status in PROBLEM_JOB_STATUSES and not error:
        findings.append(
            ArtifactFinding(
                check="job_status",
                symbol=label,
                observed=f"a {status} stage carries no error explanation",
            )
        )
    if status not in PROBLEM_JOB_STATUSES and error:
        findings.append(
            ArtifactFinding(
                check="job_status",
                symbol=label,
                observed=f"a {status} stage carries an error: {error!r}",
            )
        )
    return findings


def _job_timestamps(
    record: Mapping[str, object], label: str, as_of: datetime
) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []
    for key in ("as_of", "started_at", "finished_at"):
        value = record.get(key)
        if value is None and key == "finished_at":
            continue
        moment = _parse_datetime(value)
        if moment is None or moment.tzinfo is None:
            findings.append(
                ArtifactFinding(
                    check="timestamp",
                    symbol=label,
                    observed=f"{key} is {value!r}: missing or naive",
                )
            )
            continue
        if key == "as_of" and moment != as_of:
            findings.append(
                ArtifactFinding(
                    check="timestamp",
                    symbol=label,
                    observed=f"{key} is {value!r}, the manifest is for {as_of}",
                )
            )

    started = _parse_datetime(record.get("started_at"))
    finished = _parse_datetime(record.get("finished_at"))
    if started is not None and finished is not None and finished < started:
        findings.append(
            ArtifactFinding(
                check="timestamp",
                symbol=label,
                observed="finished_at is earlier than started_at",
            )
        )
    return findings


def _required_keys(
    required: frozenset[str],
    record: Mapping[str, object],
    symbol: str,
    index: int,
) -> list[ArtifactFinding]:
    missing = sorted(required - set(record))
    if not missing:
        return []
    return [
        ArtifactFinding(
            check="required_keys",
            symbol=symbol or f"record #{index}",
            observed=f"missing keys {missing}",
        )
    ]


def _ranges(
    kind: str, record: Mapping[str, object], symbol: str
) -> list[ArtifactFinding]:
    if kind != "STRATEGY":
        return []

    findings: list[ArtifactFinding] = []
    score = record.get("score")
    if score is not None and not _in_range(score, 0.0, 100.0):
        findings.append(
            ArtifactFinding(
                check="score_range", symbol=symbol, observed=f"score {score!r}"
            )
        )
    percentile = record.get("rank_percentile")
    if percentile is not None and not _in_range(percentile, 0.0, 1.0):
        findings.append(
            ArtifactFinding(
                check="rank_percentile_range",
                symbol=symbol,
                observed=f"rank_percentile {percentile!r}",
            )
        )
    return findings


def _cited_scores(
    kind: str, record: Mapping[str, object], symbol: str
) -> list[ArtifactFinding]:
    """The strategy results a candidate cites obey the same ranges."""
    if kind != "CANDIDATE":
        return []

    findings: list[ArtifactFinding] = []
    for cited in _cited_results(record):
        cited_symbol = _text(cited.get("symbol")) or symbol
        score = cited.get("score")
        if score is not None and not _in_range(score, 0.0, 100.0):
            findings.append(
                ArtifactFinding(
                    check="score_range",
                    symbol=cited_symbol,
                    observed=f"cited score {score!r}",
                )
            )
        percentile = cited.get("rank_percentile")
        if percentile is not None and not _in_range(percentile, 0.0, 1.0):
            findings.append(
                ArtifactFinding(
                    check="rank_percentile_range",
                    symbol=cited_symbol,
                    observed=f"cited rank_percentile {percentile!r}",
                )
            )
    return findings


def _unknown_references(
    kind: str,
    record: Mapping[str, object],
    symbol: str,
    known_factor_names: Collection[str],
    known_strategy_ids: Collection[str],
) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []

    if kind == "FACTOR" and known_factor_names:
        name = _text(record.get("factor"))
        if name and name not in known_factor_names:
            findings.append(
                ArtifactFinding(
                    check="unknown_factor",
                    symbol=symbol,
                    observed=f"factor {name!r} is not a configured factor",
                )
            )

    if kind == "STRATEGY" and known_strategy_ids:
        name = _text(record.get("strategy_id"))
        if name and name not in known_strategy_ids:
            findings.append(
                ArtifactFinding(
                    check="unknown_strategy",
                    symbol=symbol,
                    observed=f"strategy {name!r} is not a configured strategy",
                )
            )

    if kind == "STRATEGY" and known_factor_names:
        contributions = record.get("contributions")
        if isinstance(contributions, list):
            for contribution in contributions:
                if not isinstance(contribution, Mapping):
                    continue
                name = _text(contribution.get("factor"))
                if name and name not in known_factor_names:
                    findings.append(
                        ArtifactFinding(
                            check="unknown_factor",
                            symbol=symbol,
                            observed=(
                                f"contribution cites factor {name!r}, "
                                "which is not a configured factor"
                            ),
                        )
                    )
    return findings


def _versions(
    kind: str, record: Mapping[str, object], symbol: str
) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []
    lineage = record.get("lineage")
    if not isinstance(lineage, Mapping):
        return findings

    for key in VERSION_KEYS.get(kind, ()):
        if not _text(lineage.get(key)):
            findings.append(
                ArtifactFinding(
                    check="empty_version",
                    symbol=symbol,
                    observed=f"lineage.{key} is empty",
                )
            )

    if kind == "UNIVERSE" and not _text(record.get("snapshot_id")):
        findings.append(
            ArtifactFinding(
                check="empty_version",
                symbol=symbol,
                observed="snapshot_id is empty",
            )
        )
    return findings


def _timestamps(
    kind: str,
    record: Mapping[str, object],
    symbol: str,
    as_of: datetime,
) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []
    stamps = [(key, record.get(key)) for key in ("as_of",)]
    if kind == "CANDIDATE":
        stamps.extend(
            (f"strategy_results[{index}].as_of", cited.get("as_of"))
            for index, cited in enumerate(_cited_results(record))
        )
        stamps.extend(
            (f"strategy_qualifications[{index}].as_of", q.get("as_of"))
            for index, q in enumerate(_mappings(record.get("strategy_qualifications")))
        )

    for label, value in stamps:
        moment = _parse_datetime(value)
        if moment is None or moment.tzinfo is None or moment > as_of:
            findings.append(
                ArtifactFinding(
                    check="timestamp",
                    symbol=symbol,
                    observed=f"{label} is {value!r}: naive or later than the snapshot",
                )
            )
    return findings


def _cited_versions(
    kind: str, record: Mapping[str, object], symbol: str
) -> list[ArtifactFinding]:
    if kind != "CANDIDATE":
        return []

    declared = _versions_declared(
        _text(_mapping(record.get("lineage")).get("strategy_version"))
    )
    findings: list[ArtifactFinding] = []
    for index, cited in enumerate(_cited_results(record)):
        result_version = _text(_mapping(cited.get("lineage")).get("strategy_version"))
        if result_version not in declared:
            findings.append(
                ArtifactFinding(
                    check="cited_strategy_version",
                    symbol=_text(cited.get("symbol")) or symbol,
                    observed=(
                        f"strategy_results[{index}] carries "
                        f"{result_version!r}, which the candidate's lineage "
                        f"({sorted(declared)}) does not declare"
                    ),
                )
            )

    declared_quals = _versions_declared(
        _text(_mapping(record.get("lineage")).get("qualification_version"))
    )
    for index, q in enumerate(_mappings(record.get("strategy_qualifications"))):
        q_version = _text(_mapping(q.get("lineage")).get("qualification_version"))
        if q_version and declared_quals and q_version not in declared_quals:
            findings.append(
                ArtifactFinding(
                    check="cited_qualification_version",
                    symbol=_text(q.get("symbol")) or symbol,
                    observed=(
                        f"strategy_qualifications[{index}] carries "
                        f"{q_version!r}, which the candidate's lineage "
                        f"({sorted(declared_quals)}) does not declare"
                    ),
                )
            )
    return findings


def _candidate_checks(
    kind: str, record: Mapping[str, object], symbol: str
) -> list[ArtifactFinding]:
    if kind != "CANDIDATE":
        return []

    findings: list[ArtifactFinding] = []

    # Policy version at candidate level
    policy_ver = record.get("candidate_policy_version")
    if not isinstance(policy_ver, str) or not policy_ver.strip():
        findings.append(
            ArtifactFinding(
                check="empty_version",
                symbol=symbol,
                observed="candidate_policy_version is empty",
            )
        )

    # Market validation veto
    mv = record.get("market_validation")
    if mv == "CONTRADICTED":
        findings.append(
            ArtifactFinding(
                check="market_validation_veto",
                symbol=symbol,
                observed="candidate has market_validation 'CONTRADICTED'",
            )
        )

    # Strategy qualifications
    quals = _mappings(record.get("strategy_qualifications"))
    qualified_strats: list[str] = []
    for q in quals:
        if q.get("qualified") is True:
            strat_id = _text(q.get("strategy_id"))
            if strat_id:
                qualified_strats.append(strat_id)

    if not qualified_strats:
        findings.append(
            ArtifactFinding(
                check="candidate_qualifications",
                symbol=symbol,
                observed="candidate has no qualified strategy_qualifications",
            )
        )
    else:
        cited_strat_ids = {
            _text(cited.get("strategy_id")) for cited in _cited_results(record)
        }
        for strat_id in qualified_strats:
            if strat_id not in cited_strat_ids:
                findings.append(
                    ArtifactFinding(
                        check="candidate_qualifications",
                        symbol=symbol,
                        observed=(
                            f"qualified strategy {strat_id!r} has no matching "
                            "cited strategy_result"
                        ),
                    )
                )

    # Primary strategy validation
    primary_strat = _text(record.get("primary_strategy_id"))
    if not primary_strat:
        findings.append(
            ArtifactFinding(
                check="candidate_primary_strategy",
                symbol=symbol,
                observed="primary_strategy_id is missing or empty",
            )
        )
    elif qualified_strats:
        if primary_strat not in qualified_strats:
            findings.append(
                ArtifactFinding(
                    check="candidate_primary_strategy",
                    symbol=symbol,
                    observed=(
                        f"primary_strategy_id {primary_strat!r} has no matching "
                        "qualified strategy_qualification"
                    ),
                )
            )
        else:
            # Deterministic check: highest rank_percentile, then ascending strategy_id
            qualified_qual_objs = [
                q
                for q in quals
                if q.get("qualified") is True and _text(q.get("strategy_id"))
            ]

            def _strat_rank_key(q: Mapping[str, object]) -> tuple[float, str]:
                p = q.get("rank_percentile")
                pval = float(p) if isinstance(p, (int, float)) else -1.0
                return (-pval, _text(q.get("strategy_id")))

            sorted_quals = sorted(qualified_qual_objs, key=_strat_rank_key)
            expected_primary = _text(sorted_quals[0].get("strategy_id"))
            if primary_strat != expected_primary:
                findings.append(
                    ArtifactFinding(
                        check="candidate_primary_strategy",
                        symbol=symbol,
                        observed=(
                            f"primary_strategy_id {primary_strat!r} is not the top "
                            f"qualified strategy (expected {expected_primary!r})"
                        ),
                    )
                )

    # Signal strategy alignment
    sig_strat = _text(record.get("signal_strategy_id"))
    if not sig_strat:
        sig_val = record.get("signal")
        if isinstance(sig_val, Mapping):
            sig_strat = _text(sig_val.get("strategy_id"))
    if sig_strat and primary_strat and sig_strat != primary_strat:
        findings.append(
            ArtifactFinding(
                check="signal_strategy_match",
                symbol=symbol,
                observed=(
                    f"signal strategy_id {sig_strat!r} does not match "
                    f"primary_strategy_id {primary_strat!r}"
                ),
            )
        )

    # Market validation strategy alignment
    mv_strat = _text(record.get("market_validation_strategy_id"))
    if not mv_strat:
        mv_val = record.get("market_validation")
        if isinstance(mv_val, Mapping):
            mv_strat = _text(mv_val.get("strategy_id"))
    if mv_strat and primary_strat and mv_strat != primary_strat:
        findings.append(
            ArtifactFinding(
                check="market_validation_strategy_match",
                symbol=symbol,
                observed=(
                    f"market validation strategy_id {mv_strat!r} does not match "
                    f"primary_strategy_id {primary_strat!r}"
                ),
            )
        )

    # Signal publication rules (Decision D1, E1, F1 independent replay)
    sig = _text(record.get("signal"))
    if sig == "BREAKDOWN":
        findings.append(
            ArtifactFinding(
                check="signal_veto",
                symbol=symbol,
                observed="candidate has signal 'BREAKDOWN' which is vetoed by approved Decision D1",
            )
        )
    elif sig == "TREND_WEAKEN":
        action = _text(record.get("next_action"))
        if action != "WATCH":
            findings.append(
                ArtifactFinding(
                    check="signal_action",
                    symbol=symbol,
                    observed=(
                        f"candidate with signal 'TREND_WEAKEN' must have next_action 'WATCH', "
                        f"observed {action!r}"
                    ),
                )
            )
        risks = record.get("risks")
        risk_strs = [str(r) for r in risks] if isinstance(risks, (list, tuple)) else []
        if not any("TREND_WEAKEN" in r or "走弱" in r for r in risk_strs):
            findings.append(
                ArtifactFinding(
                    check="signal_risk_warning",
                    symbol=symbol,
                    observed="candidate with signal 'TREND_WEAKEN' lacks weaken risk warning in risks",
                )
            )
    elif sig == "NO_SIGNAL":
        action = _text(record.get("next_action"))
        if action != "WATCH":
            findings.append(
                ArtifactFinding(
                    check="signal_action",
                    symbol=symbol,
                    observed=(
                        f"candidate with signal 'NO_SIGNAL' must have next_action 'WATCH', "
                        f"observed {action!r}"
                    ),
                )
            )

    # Market validation independent replay from serialized evidence
    for res in _cited_results(record):
        for factor in _cited_factors(res):
            if _text(factor.get("factor")) == "avg_amount_20d":
                raw_val = factor.get("raw_value")
                if (
                    isinstance(raw_val, (int, float))
                    and not isinstance(raw_val, bool)
                    and float(raw_val) < 100_000_000.0
                ):
                    findings.append(
                        ArtifactFinding(
                            check="market_validation_liquidity_veto",
                            symbol=symbol,
                            observed=(
                                f"avg_amount_20d {raw_val} < 1.0e8 triggers liquidity veto, "
                                "candidate cannot be published"
                            ),
                        )
                    )

    return findings


def _regime_checks(
    kind: str, record: Mapping[str, object], symbol: str
) -> list[ArtifactFinding]:
    if kind != "MARKET_REGIME":
        return []
    findings: list[ArtifactFinding] = []
    regime = record.get("regime")
    if not isinstance(regime, str) or regime not in MARKET_REGIME_VOCABULARY:
        findings.append(
            ArtifactFinding(
                check="regime_vocabulary",
                symbol=symbol,
                observed=f"regime {regime!r} is not one of {sorted(MARKET_REGIME_VOCABULARY)}",
            )
        )
    return findings


def _availability_times(
    kind: str,
    record: Mapping[str, object],
    symbol: str,
    as_of: datetime,
) -> list[ArtifactFinding]:
    """FACTOR 快照必须能独立自证没有前视。

    规则只有两条，但都要在快照里看得见：只要一条引用**真的带了证据**（写了报告期），
    它就必须带上 `available_at`；而带上之后，那个时刻必须是带时区的，并且不晚于
    计算时点。只写 `metric` 的引用表示"这条证据不存在"，没有时间可写。
    """
    if kind != "FACTOR":
        return []

    findings: list[ArtifactFinding] = []
    for index, ref in enumerate(_input_refs(record)):
        label = f"inputs[{index}]"
        raw = ref.get("available_at")
        if raw is None:
            if ref.get("report_period") is None:
                continue
            findings.append(
                ArtifactFinding(
                    check="available_at",
                    symbol=symbol,
                    observed=(
                        f"{label} cites report period "
                        f"{ref.get('report_period')!r} without an availability "
                        "time, so the snapshot cannot show it had no look-ahead"
                    ),
                )
            )
            continue

        moment = _parse_datetime(raw)
        if moment is None or moment.tzinfo is None or moment > as_of:
            findings.append(
                ArtifactFinding(
                    check="available_at",
                    symbol=symbol,
                    observed=(
                        f"{label} available_at is {raw!r}: unparseable, naive, or "
                        "later than the snapshot's as_of"
                    ),
                )
            )
    return findings


def _input_refs(record: Mapping[str, object]) -> list[Mapping[str, object]]:
    """一条 FACTOR 记录引用的证据。"""
    return _mappings(record.get("inputs"))


def _cited_factors(result: Mapping[str, object]) -> list[Mapping[str, object]]:
    """一条策略结果引用的因子。"""
    return _mappings(result.get("factor_snapshot"))


def _mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _versions_declared(declared: str) -> frozenset[str]:
    """Split a lineage version field into the versions it declares.

    A run may score with more than one scanner, and each carries its own
    version, so a lineage field can list several — comma-separated. An empty
    field declares nothing, which fails the `empty_version` check elsewhere.
    """
    return frozenset(
        part for part in (item.strip() for item in declared.split(",")) if part
    )


def _cited_results(record: Mapping[str, object]) -> list[Mapping[str, object]]:
    results = record.get("strategy_results")
    if not isinstance(results, list):
        return []
    return [result for result in results if isinstance(result, Mapping)]


def _in_range(value: object, low: float, high: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return low <= float(value) <= high


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
