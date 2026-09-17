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
        {"symbol", "as_of", "next_action", "lineage", "strategy_results"}
    ),
}

# The version keys whose lineage value must be non-empty, per kind.
VERSION_KEYS: dict[str, tuple[str, ...]] = {
    "UNIVERSE": (),
    "FACTOR": ("factor_version",),
    "STRATEGY": ("strategy_version",),
    "CANDIDATE": ("strategy_version",),
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

    for index, record in enumerate(records):
        symbol = _text(record.get("symbol"))
        findings.extend(_required_keys(required, record, symbol, index))
        findings.extend(_ranges(kind, record, symbol))
        findings.extend(
            _unknown_references(
                kind, record, symbol, known_factor_names, known_strategy_ids
            )
        )
        findings.extend(_versions(kind, record, symbol))
        findings.extend(_timestamps(kind, record, symbol, as_of))
        findings.extend(_cited_versions(kind, record, symbol))
        findings.extend(_cited_scores(kind, record, symbol))

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
    return findings


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
