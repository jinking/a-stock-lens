# Review Notes

The archived spec metadata says that final review is pending, while the current user instruction confirms this package as the formal approved baseline.

The current instruction resolves the status mismatch. No product rule was changed.

## Implementation notes (conformance pass, 2026-09-16)

The design package was re-applied to the repository. `docs/PRODUCT.md`,
`docs/ARCHITECTURE.md` and the spec are byte-identical to what the package
contains, so no document was overwritten; the work was closing gaps between the
design and the code. Every gap that could be closed without inventing a number
was closed. The decisions taken, and why, are recorded here.

### Watchlist transitions

`spec §13` confirms one active path — `DISCOVERED → WATCH → DEEP_RESEARCH →
TRACK_SIGNAL` — and lists `READY`, `HOLDING`, `EXITED`, `ARCHIVED` as reserved
for later phases. The implementation accepts exactly the confirmed forward
step, and refuses backward moves, skipped moves, repeated moves, and every
reserved state. Those refusals are an interpretation: the design does not
define a backward or a skipping rule, and accepting one would put a product
decision in the code. The refusal message names every state involved, so a
future user who wants a different rule knows exactly what to change.

### Stage order inside the daily pipeline

`spec §15` lists `BUILD_UNIVERSE` (3) before `COMPUTE_FACTORS` (4). The pipeline
runs `COMPUTE_FACTORS` first, because the Universe's liquidity rule consumes
the `avg_amount_20d` factor and measuring it twice would give one quantity two
definitions. This was already the behaviour of the earlier scan slice; it is
now stated in `pipelines/daily.py` next to `EXECUTION_ORDER` rather than left
implicit. The manifest records the order that actually ran.

### Blocked stages

`DETECT_REGIME`, `MARKET_VALIDATE`, `RUN_SIGNALS` and `UPDATE_WATCHLIST` are
recorded as `BLOCKED` with the decision they wait for. The design fixes their
vocabularies but not any threshold, and `AGENTS.md` forbids inventing one; no
rule changes a watchlist state on its own either. Consequently `astock daily`
exits non-zero while those stages are blocked, and `--allow-incomplete` must be
asked for explicitly. `MARKET_REGIME` therefore has no producer yet, and
`GENERATE_DAILY_SNAPSHOT` names it as missing rather than writing a placeholder.

### Vocabulary that is not in `domain/enums.py`

`JobStatus` lives next to the job store, not in `domain/enums.py`, for the same
reason `UniverseRule` does: `domain` holds the vocabularies the design
enumerates, and the design names the `status` field of `JobRun` without
enumerating its values.

### Snapshot lineage with more than one scanner

`docs/DATA_MODEL.md` §2 reserves a `strategy_version` lineage field, and
`spec §8` has seven scanners, so a run can score one symbol with several
strategies carrying different versions. A lineage field therefore lists every
version that took part, comma-separated, and "is this result covered by this
lineage?" is a membership question rather than an equality one.
`SnapshotLineage` exposes the split, and both the CandidateBuilder and the
independent Artifact Validator use it.

### Deep research adapter

`spec §14` fixes the adapter interface and names a CLI implementation, but not
the shape of the external call. The command comes from
`ASTOCK_DEEP_RESEARCH_CMD` and speaks one JSON document in, one JSON document
out. That call shape is an integration detail recorded here, not a product
rule; job states remain the other system's vocabulary and are passed through
unchanged. With no command configured, `astock research` refuses by name
rather than pretending to submit.
