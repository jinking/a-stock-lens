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

    cited_version = _text(_mapping(record.get("lineage")).get("strategy_version"))
    findings: list[ArtifactFinding] = []
    for index, cited in enumerate(_cited_results(record)):
        result_version = _text(_mapping(cited.get("lineage")).get("strategy_version"))
        if result_version != cited_version:
            findings.append(
                ArtifactFinding(
                    check="cited_strategy_version",
                    symbol=_text(cited.get("symbol")) or symbol,
                    observed=(
                        f"strategy_results[{index}] carries "
                        f"{result_version!r}, the candidate declares "
                        f"{cited_version!r}"
                    ),
                )
            )
    return findings


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
