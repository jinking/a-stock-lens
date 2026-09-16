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
| 100 symbols in one batch, one statement | 11.4s, 100 rows returned — so a whole-market pass over the three statements is ~30 min: a quarterly job, not part of the 10-minute daily target |
| CLI batch summary (`成功: 1`) | says success even for an invalid code, so coverage is computed from returned codes instead |
| `neodata` query for the latest report | answered with structured markdown including `发布日期` / `统计截止日期` / `报告期` (2026-H1 works when the period is named), but it is per-entity, prose-shaped, and its 12-hour credential can only be refreshed by the WorkBuddy platform |

Consequences recorded in code:

- `RawDataset.missing_symbols` exists because a source can answer a batch
  partially without saying so;
- the provider always requests `--fields all`, and that is asserted by a test
  rather than left to convention;
- WeStock is invoked as an external command. No deep-research Python module is
  imported and no internal state is read (`ARCHITECTURE.md` §4.1).

## Fundamentals slice (2026-09-16, after the amendment)

The provider landed statements; this slice turned them into canonical,
point-in-time observations the factor engine may read.

Decisions taken here, none of which the design settles:

- **`available_at` is the publication date at the A-share close** (`15:00
  +08:00`). `InfoPublDate` is a date, not a moment, and a filing can appear
  before the open or after the close. Taking the close is the conservative
  reading: it can delay availability, never advance it.
- **The metric mapping lives in code** (`data/normalize/financials.py`), next
  to the provider that produced the columns, exactly as
  `akshare_provider.BAR_COLUMN_MAP` does. A source-column mapping is
  integration detail, not a threshold.
- **48 canonical metrics** cover the design's Quality / Growth / Valuation /
  Dividend / cash-flow dimensions, with units carried per metric (`%`, `x`,
  `CNY`, `CNY/share`) so a reader never has to guess whether `17.7179` is a
  ratio or a percent.
- **Three ways to be absent stay distinct**: a source marker (`-`) becomes a
  `NULL` observation, unreadable text becomes an `INVALID` key with a failure
  record naming the raw cell, and a statement that was never landed is named in
  `absent_datasets`. None of them becomes zero and none of them disappears.
- **`NULL` observations stay usable** through the gate, unlike `INVALID` ones:
  a factor has to be able to report "the source has no value here", and
  dropping the observation would make that indistinguishable from a metric
  nobody computes.
- **Statements are re-fetched, not skipped by age.** A freshness-based skip
  would need a cadence decision (`Deferred`); re-landing is safe because rows
  merge on `(code, EndDate)`.

### A real defect the end-to-end run found

Syncing into a directory that already held the fixture listing produced **two
profiles for one symbol**, and the scan then died mid-pipeline with
`score_cross_section expects at most one context per symbol`. Two causes, both
fixed:

1. the listing was merged on *every* column, so a reformatted name or listing
   date appended a second row for the same instrument — the listing is now
   keyed by `symbol` alone;
2. `UniverseBuilder` admitted both profiles, so one symbol entered the
   cross-section twice. A repeated instrument is now excluded with the
   `DUPLICATE_SECURITY` rule, which keeps the scan running *and* keeps the
   reason visible instead of silently deduplicating the listing.

The throughput figure in §24 was also corrected: ~11s per 100 symbols is one
statement, so all three statements over the whole market is a ~30-minute
quarterly job, not part of the 10-minute daily target.

## Fundamental factor slice (2026-09-16, same day)

Five ratio factors now read the canonical observations. Decisions taken here,
none of which the design settles:

- **TTM against TTM.** Chinese statements are cumulative year-to-date, so
  dividing an H1 flow by a period-end stock mixes half a year with a whole
  balance sheet. The source publishes both TTM and period fields, so the ratios
  that need a trailing year use TTM on both sides rather than a sum this code
  assembled from quarters.
- **Missing-evidence precedence is stated, not implied**: `NOT_APPLICABLE`
  (the instrument's statements do not carry the line) outranks `NULL` (the
  line exists without a value), which outranks `STALE`. Without a stated order
  two implementations would disagree about the same record.
- **`STALE` is a mechanism waiting for a number.** Each fundamental factor
  config must declare `params.stale_after_days`; writing `null` records that no
  freshness requirement has been reviewed, and the factor then never reports
  `STALE`. This mirrors `configs/universe.yaml`'s `long_suspension_days: null`.
- **`FactorResult.inputs` was added** so a value can name the metric, the report
  period, the announcement date and the raw value it rests on. The design
  requires the explanation chain to be walkable; without this field a reader
  could see a ratio but not which quarter produced it.
- **`factors compute` now normalizes through the same stage as the daily run.**
  It previously built its own bars-only dataset, which would have made a
  fundamental factor report `NOT_APPLICABLE` under one command and `VALUE`
  under another.

Known interpretation boundary, recorded rather than fixed: a bank's operating
cash flow includes deposit movements, so `ocf_to_net_profit` does not mean
"profit quality" for financial companies (measured: 000001.SZ = 8.20). Whether
a factor should be exempt for some industries is a strategy-layer decision the
design has not made, so no industry guard was added.
