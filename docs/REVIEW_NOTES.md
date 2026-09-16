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

## Data-source boundary amendment (2026-09-16)

The project owner approved moving the bulk financial-statement source to the
same Tencent WeStock CLI the deep-research stack uses, and leaving `neodata` on
the research side. The amendment itself is written into the spec as §24, and
`docs/PRODUCT.md` §4.2, `docs/ARCHITECTURE.md` §4.1 and `docs/DATA_SOURCES.md`
§1–2 point at it. What the decision rests on, measured that day:

| Evidence | Result |
| --- | --- |
| `westock finance sh600519 --type income --fields all` | `EndDate` (report period) **and** `InfoPublDate` (publication date) |
| Same call with the default `--fields core` | no publication date at all |
| AkShare/Sina statements | publication date is not the original filing date (FY2025 balance sheet says `20260815`, the same period's income statement says `20260417`) |
| 100 symbols in one batch | 11.4s, 100 rows returned — a whole-market quarterly refresh lands near the §21 target |
| CLI batch summary (`成功: 1`) | says success even for an invalid code, so coverage is computed from returned codes instead |
| `neodata` query for the latest report | answered with structured markdown including `发布日期` / `统计截止日期` / `报告期` (2026-H1 works when the period is named), but it is per-entity, prose-shaped, and its 12-hour credential can only be refreshed by the WorkBuddy platform |

Consequences recorded in code:

- `RawDataset.missing_symbols` exists because a source can answer a batch
  partially without saying so;
- the provider always requests `--fields all`, and that is asserted by a test
  rather than left to convention;
- WeStock is invoked as an external command. No deep-research Python module is
  imported and no internal state is read (`ARCHITECTURE.md` §4.1).
