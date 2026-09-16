# A-Stock Lens First Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the first end-to-end slice of the V1 acceptance chain real — a source-shaped local CSV provider, a canonical normalizer, a Data Quality Gate, one versioned factor, one scanner, a candidate snapshot, and the first domain query API — without inventing a single threshold, weight, or vocabulary the design does not already name.

**Architecture:** Keep the approved modular monolith and its strict dependency direction. This slice touches `data → factors → strategies → candidates → api/cli` and stays inside the existing Protocol contracts, extending `RawDataset` and `NormalizedDataset` only where the bootstrap contracts were provably incomplete. Every number that the design does not fix (factor windows, strategy weights) is read from YAML; every number the design does fix (`available_at <= as_of`, the 20-day Universe window, `min_listing_days: 120`) is reused rather than restated.

**Tech Stack:** Python 3.12+, Pydantic 2, PyYAML, Typer, FastAPI, pytest, pytest-cov, Ruff, mypy (strict), uv. No new runtime dependency is added by this slice.

**Spec:** `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`

**Base:** `main` at `c6ecf1c` (bootstrap PR #1 rebase-merged). Branch: `feat/first-vertical-slice`.

## Global Constraints

Inherited from the bootstrap plan and still binding:

- Precedence is design spec → `docs/PRODUCT.md` → `docs/ARCHITECTURE.md` → `README.md`.
- Dependency direction `Provider → Raw → Normalized → Data Quality Gate → Universe → Factor → Strategy → Market → Signal → Candidate → Watchlist → Deep Research` is one-way and never reversed.
- Strategies never call a provider. API and Web never recompute factors. Providers never contain strategy decisions.
- Missing-data states are exactly `VALUE`, `NULL`, `STALE`, `INVALID`, `SOURCE_ERROR`, `NOT_APPLICABLE`. **A missing value never becomes `0`.**
- Financial observations carry `report_period`, `announce_date`, `available_at` with `available_at <= as_of`. Time-sensitive results carry `as_of`. Timestamps are timezone-aware (`DTZ001` is enforced by the locked Ruff defaults).
- Snapshots carry `universe_snapshot`, `factor_version`, `strategy_version` lineage.
- Candidate is a research object, never a recommendation. `next_action` is limited to `IGNORE`, `WATCH`, `DEEP_RESEARCH`, `TRACK_SIGNAL`.
- Unknown thresholds and weights stay absent or explicitly deferred. Do not invent product rules.
- Every behaviour change starts with a failing test. No behaviour change commits without failure evidence.

## Slice Decisions

Each decision below is a ruling this slice introduces. They are recorded here so a reviewer can reject any of them before implementation is trusted.

**S1 — `RawDataset` gains an explicit payload.** The bootstrap contract carried only fetch metadata, so `Normalizer.normalize(dataset, as_of)` had no way to reach the source rows. `RawPayload` (`columns` + `rows`, all strings, order-preserving, immutable) is added, and `RawDataset.payload: RawPayload | None = None`. Payload stays verbatim — no type inference, no cleaning, no renaming — because `docs/ARCHITECTURE.md` §4.2 requires the raw layer to preserve the source shape. *Cost if wrong: raw storage and the normalizer both carry a payload the storage layer may later prefer to own.*

**S2 — Fixture and raw data are CSV, never Parquet.** `.gitignore` contains `data/**/*.parquet`, so a Parquet fixture would be silently excluded from the repository and the test suite would fail on a clean clone. *Cost if wrong: none; CSV is also human-diffable, which matters more here than parse speed.*

**S3 — The Data Quality Gate reports, it does not repair.** `check()` returns a `QualityReport` and never rewrites a value. Which bars survive is decided by the caller through `valid_bars()`. This keeps "invalid" visible instead of silently dropping rows inside a filter. *Cost if wrong: callers must remember to apply the report, so a caller that ignores it will process invalid bars.*

**S4 — This slice ships no strategy scoring.** `docs/ARCHITECTURE.md` §8.3 says weights and thresholds belong in YAML, and no weight has been reviewed yet. `MomentumScanner` therefore implements `required_factors`, `eligibility`, `explain`, and a `score` that reports the factor values it used while leaving `score`, `rank_percentile`, and `confidence` explicitly `None` with a stated reason. *Cost if wrong: the first scanner is not yet a ranker; the acceptance chain reaches a Candidate but not a ranked Candidate.*

**S5 — `next_action` defaults to the conservative `IGNORE`.** The design enumerates the allowed actions but defines no rule for choosing between them. Until a reviewed rule exists, every candidate is marked `IGNORE` — "no action" — which cannot mislead, unlike defaulting to `WATCH` or `DEEP_RESEARCH`. *Cost if wrong: candidates look inert until the routing rule lands.*

**S6 — Snapshots go through a `SnapshotStore` protocol.** DuckDB is specified for V1 storage but lives in the optional `data` extra, and the bootstrap ruling keeps the default environment light. This slice defines the protocol plus a standard-library JSON implementation under `data/snapshots/`, so the chain is verifiable and testable with no extra dependency. The DuckDB implementation lands later behind the same protocol. *Cost if wrong: an interim JSON format exists that DuckDB will eventually supersede.*

**S7 — Factor parameters live in `configs/factors/*.yaml`.** The first factor's window, domain, version, direction, and null policy are all configuration. The code contains no default window, so a missing config is an error rather than a silent fallback. *Cost if wrong: running the factor requires a config file to exist, which is intentional.*

---

### Task 1: Raw Payload Contract and Local CSV Provider

**Files:**
- Modify: `src/astock_lens/data/contracts.py`
- Create: `src/astock_lens/data/providers/local.py`
- Create: `src/astock_lens/data/providers/__init__.py` (replace the empty placeholder)
- Create: `tests/unit/test_local_csv_provider.py`
- Create: `tests/fixtures/csv/daily_bars.csv`

**Interfaces:**

- Consumes: `astock_lens.data.contracts.{DataProvider, FetchRequest, RawDataset, ProviderHealth}`
- Produces:
  - `RawPayload(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...])`
  - `RawDataset.payload: RawPayload | None = None`
  - `LocalCsvProvider(root: Path, *, provider: str = "local-csv", version: str = "v1")`
  - `LocalCsvProvider.health() -> ProviderHealth`
  - `LocalCsvProvider.fetch(request: FetchRequest) -> RawDataset`

**Error model (stated, not implied):**

- A *data* problem — missing file, unreadable file, empty file — returns a `RawDataset` carrying `DataStatus.SOURCE_ERROR` or `DataStatus.NULL` with `row_count` matching reality. It never raises, because data problems must be visible in Data Health rather than crash a scan.
- A *caller* problem — asking to filter on a column the file does not have — raises `ValueError`. That is a programming error, not a data condition.
- A file that exists and parses returns `DataStatus.VALUE`.

- [ ] **Step 1: Write the failing provider tests**

Cover: the fixture file loads with the expected column set and row count; a missing file yields `SOURCE_ERROR` with `row_count == 0` and `payload is None`; `health()` is unhealthy when the root is absent and healthy when present; symbol filtering keeps only requested symbols; asking to filter on an unknown column raises `ValueError`; an empty cell stays an empty string in the payload and is *not* turned into `0`.

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
uv run pytest tests/unit/test_local_csv_provider.py -q
```

Expected: collection error or import failure for `astock_lens.data.providers.local`.

- [ ] **Step 3: Add `RawPayload` and the `payload` field**

Extend `RawDataset` with `payload` defaulting to `None` so every existing construction site keeps working.

- [ ] **Step 4: Implement `LocalCsvProvider`**

Read `root / f"{request.dataset}.csv"` with `csv.reader`, keep every cell as a string, and never coerce types.

- [ ] **Step 5: Add the CSV fixture**

`tests/fixtures/csv/daily_bars.csv` — a small hand-written set of symbols across several trade dates, including at least one blank `amount` cell so the "missing stays missing" invariant is exercised from Task 1 onward.

- [ ] **Step 6: Run the full gate and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A && git commit -m "feat(data): add raw payload contract and local csv provider"
```

---

### Task 2: Canonical Normalizer for Daily Bars

**Files:**
- Modify: `src/astock_lens/data/contracts.py` (add `ParseFailure`, `NormalizedDataset.parse_failures`)
- Create: `src/astock_lens/data/normalize/csv_bars.py`
- Modify: `src/astock_lens/data/normalize/__init__.py`
- Create: `tests/unit/test_csv_daily_bar_normalizer.py`

**Interfaces:**

- Consumes: `RawDataset` with a non-empty `payload`
- Produces:
  - `ParseFailure(row_index: int, column: str, raw_value: str, reason: str)`
  - `NormalizedDataset.parse_failures: tuple[ParseFailure, ...] = ()`
  - `CsvDailyBarNormalizer(*, column_map: Mapping[str, str] | None = None, source: str)`
  - `CsvDailyBarNormalizer.normalize(dataset: RawDataset, *, as_of: datetime) -> NormalizedDataset`

**Normalization rules:**

- `as_of` must be timezone-aware; a naive `as_of` raises `ValueError`.
- Blank cells, `-`, `--`, `nan`, `N/A` (case-insensitive) normalize to `None`. **Not `0`.**
- A cell that is present but unparseable as a float becomes `None` *and* emits a `ParseFailure` naming the row index, column, and raw text. The distinction between "absent" and "corrupt" survives.
- A row whose `symbol` or `trade_date` cannot be read is rejected entirely and emits a `ParseFailure`; it never becomes a `DailyBar` with fabricated keys.
- A `payload is None` dataset normalizes to an empty `NormalizedDataset` — the upstream status already recorded why.
- `column_map` renames source columns to canonical names; without it, canonical names are matched directly.

- [ ] **Step 1: Write the failing normalizer tests**

Cover: a clean row maps to the expected `DailyBar`; a blank `amount` yields `amount is None`; a corrupt `close` yields `close is None` *and* one `ParseFailure`; a row with an unreadable `trade_date` produces no `DailyBar` and one `ParseFailure`; a payload-less dataset yields an empty result; a naive `as_of` raises `ValueError`.

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
uv run pytest tests/unit/test_csv_daily_bar_normalizer.py -q
```

- [ ] **Step 3: Add `ParseFailure` and normalize the row contract**

- [ ] **Step 4: Implement `CsvDailyBarNormalizer`**

- [ ] **Step 5: Run the full gate and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A && git commit -m "feat(data): normalize csv rows into canonical daily bars"
```

---

### Task 3: Data Quality Gate

**Files:**
- Create: `src/astock_lens/data/quality/gate.py`
- Modify: `src/astock_lens/data/quality/__init__.py`
- Create: `tests/unit/test_daily_bar_quality_gate.py`

**Interfaces:**

- Consumes: `NormalizedDataset`
- Produces:
  - `QualityIssue(rule: str, status: DataStatus, severity: ErrorSeverity, symbol: str | None, trade_date: date | None, message: str)`
  - `QualityReport(dataset: str, as_of: datetime, checked: int, accepted: int, issues: tuple[QualityIssue, ...] = ())`
  - `QualityReport.blocking() -> tuple[QualityIssue, ...]`
  - `DailyBarQualityGate(rules_version: str = "v1")`
  - `DailyBarQualityGate.check(dataset: NormalizedDataset) -> QualityReport`
  - `valid_bars(dataset: NormalizedDataset, report: QualityReport) -> tuple[DailyBar, ...]`

**Rules — every one traceable to `docs/ARCHITECTURE.md` §4.4, none invented:**

| Rule id | Condition | Status | Severity |
|---|---|---|---|
| `close_not_positive` | `close is not None and close <= 0` | `INVALID` | P2 |
| `close_missing` | `close is None` | `INVALID` | P2 |
| `volume_negative` | `volume is not None and volume < 0` | `INVALID` | P2 |
| `duplicate_primary_key` | repeated `(symbol, trade_date)` | `INVALID` | P2 |
| `dataset_empty` | zero bars to check | `SOURCE_ERROR` | P1 |

Severity reasoning: a single bad bar must not block a whole-market scan, so per-record findings are P2 ("non-critical missing data; continue with warning"). A dataset that yields nothing at all is P1 ("key dataset unavailable; block/degrade the related module"). No ratio-based escalation is implemented, because the design names no such ratio.

- [ ] **Step 1: Write the failing gate tests**

Cover each row of the table above individually, plus: a clean dataset produces zero issues and `accepted == checked`; `blocking()` returns exactly the P0/P1 findings; `valid_bars()` excludes only the bars named by `invalid` issues; the gate never mutates the input dataset.

- [ ] **Step 2: Run the tests and confirm they fail**

- [ ] **Step 3: Implement `QualityIssue`, `QualityReport`, and `DailyBarQualityGate`**

- [ ] **Step 4: Run the full gate and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A && git commit -m "feat(data): add daily bar quality gate"
```

---

### Task 4: Factor Registry and the First Factor

**Files:**
- Create: `src/astock_lens/factors/registry.py`
- Create: `src/astock_lens/factors/builtin.py`
- Create: `src/astock_lens/factors/config.py`
- Modify: `src/astock_lens/factors/__init__.py`
- Create: `configs/factors/avg_amount_20d.yaml`
- Modify: `configs/factors/README.md`
- Create: `tests/unit/test_factor_registry.py`
- Create: `tests/unit/test_avg_amount_factor.py`

**Interfaces:**

- Consumes: a post-gate `NormalizedDataset`
- Produces:
  - `FactorConfig` (parsed from YAML: `name`, `domain`, `description`, `inputs`, `frequency`, `direction`, `null_policy`, `version`, `params`)
  - `load_factor_config(path: Path) -> FactorConfig`
  - `FactorRegistry.register(factor: Factor) -> None` — duplicate name raises `ValueError`
  - `FactorRegistry.get(name: str) -> Factor` — unknown name raises `KeyError`
  - `FactorRegistry.names() -> tuple[str, ...]` — registration order preserved
  - `AverageAmountFactor(factor_config: FactorConfig)`

**Factor semantics:**

- The window is read from `params["window"]`. There is **no default**; a config without it fails to load.
- `avg_amount_20d` requires `window` consecutive trading days on or before `as_of.date()`.
- Fewer than `window` available bars yields `DataStatus.NULL` with `raw_value=None`. It does **not** average a shorter window, because that would silently answer a different question.
- Any missing `amount` inside the window yields `DataStatus.NULL`. No partial averaging.
- A complete window yields `DataStatus.VALUE` and the arithmetic mean.
- The factor assumes its input has already passed the Data Quality Gate; this is stated in the docstring as a boundary, not enforced by a silent fallback.

`configs/factors/avg_amount_20d.yaml` uses `window: 20`, which `docs/ARCHITECTURE.md` §6 and the design spec §6 already name as the Universe's 20-day average turnover window. The file records that provenance in a comment. The `domain`, `direction`, and `null_policy` strings are declared here — in configuration, reviewable and editable — precisely because the design does not enumerate their vocabularies.

- [ ] **Step 1: Write the failing factor tests**

Cover: registry duplicate registration raises; unknown lookup raises; `names()` preserves order. For the factor: a full window produces the exact arithmetic mean; `window - 1` bars produces `NULL` with `raw_value is None`; a `None` `amount` inside an otherwise full window produces `NULL`; bars after `as_of` are excluded; a config missing `window` fails to load.

- [ ] **Step 2: Run the tests and confirm they fail**

- [ ] **Step 3: Implement `FactorConfig`, `load_factor_config`, `FactorRegistry`, `AverageAmountFactor`**

- [ ] **Step 4: Run the full gate and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A && git commit -m "feat(factors): add factor registry and first configured factor"
```

---

### Task 5: First Scanner, Candidate Builder, and Snapshot Store

**Files:**
- Create: `src/astock_lens/strategies/config.py`
- Create: `src/astock_lens/strategies/momentum.py`
- Modify: `src/astock_lens/strategies/__init__.py`
- Create: `src/astock_lens/candidates/models.py`
- Create: `src/astock_lens/candidates/builder.py`
- Modify: `src/astock_lens/candidates/__init__.py`
- Create: `src/astock_lens/data/snapshots/store.py`
- Modify: `configs/strategies/momentum.yaml`
- Create: `tests/unit/test_momentum_scanner.py`
- Create: `tests/unit/test_candidate_builder.py`
- Create: `tests/unit/test_snapshot_store.py`

**Interfaces:**

- Consumes: `FactorResult`, `StrategyContext`, `SnapshotLineage`
- Produces:
  - `StrategyConfig` and `load_strategy_config(path: Path) -> StrategyConfig`
  - `MomentumScanner(strategy_config: StrategyConfig)`
  - `Candidate(symbol, as_of, strategy_results, reasons, risks, next_action, market_validation=None, signal=None, lineage)`
  - `CandidateBuilder.build(symbol: str, *, as_of: datetime, strategy_results, lineage, next_action: NextAction = NextAction.IGNORE) -> Candidate`
  - `SnapshotStore` Protocol: `write(kind: SnapshotKind, as_of: datetime, records: Sequence[BaseModel]) -> Path` and `read(kind: SnapshotKind, as_of: datetime) -> tuple[dict[str, object], ...]`
  - `JsonSnapshotStore(root: Path)`

**Scanner behaviour:**

- `required_factors()` reads the factor names from `configs/strategies/momentum.yaml`, which is extended with a `required_factors` list. No factor name is hardcoded in Python.
- `eligibility()` requires every required factor to be present with `DataStatus.VALUE`. Every unmet condition becomes a `reasons` entry naming the factor and the status actually seen.
- `score()` returns `StrategyResult(score=None, rank_percentile=None, confidence=None, ...)` with the observed factor values written into `reasons`. `rank_percentile` needs a whole-market distribution that this slice does not build, and `score` needs weights no one has reviewed yet — S4. The result stays honest rather than plausible.
- `explain()` turns the result into a factor-level `Explanation`.

**Candidate lineage:** `CandidateBuilder.build` refuses a candidate whose `strategy_results` reference a factor version the lineage does not carry, raising `ValueError`. This is the one lineage invariant this slice can genuinely enforce.

**Snapshot store:** writes `data/snapshots/<kind>/<as_of-date>.json` containing an `as_of`, a `kind`, and the serialized records. `read()` returns an empty tuple for an absent snapshot rather than raising, so the API can report "no snapshot for this date" instead of a 500.

- [ ] **Step 1: Write the failing tests**

Scanner: eligibility passes when all required factors are `VALUE`; fails with a reason naming the factor when one is `NULL`; a missing required factor is a failure, not an exception. Candidate: lineage mismatch raises `ValueError`; default `next_action` is `IGNORE`; `market_validation` and `signal` stay `None`. Snapshot store: write-then-read round-trips; reading an unwritten date returns `()`, not an error.

- [ ] **Step 2: Run the tests and confirm they fail**

- [ ] **Step 3: Implement the scanner, the candidate builder, and the snapshot store**

- [ ] **Step 4: Run the full gate and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A && git commit -m "feat(pipeline): add first scanner, candidate builder, and snapshot store"
```

---

### Task 6: CLI Command, Domain API, and End-to-End Integration Test

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Modify: `src/astock_lens/api/app.py`
- Create: `src/astock_lens/pipelines/first_slice.py`
- Modify: `src/astock_lens/pipelines/__init__.py`
- Create: `tests/integration/test_first_slice.py`
- Create: `tests/unit/test_api.py` (extend the existing file)
- Modify: `README.md`

**Interfaces:**

- Produces:
  - `run_first_slice(*, csv_root: Path, as_of: datetime, factor_config: FactorConfig, strategy_config: StrategyConfig, store: SnapshotStore) -> CandidateSnapshotResult` — the whole chain in one callable, so the CLI and the integration test exercise the same code path instead of two parallel ones.
  - `astock factors compute --as-of YYYY-MM-DD` — runs the chain and prints one JSON document per factor result to stdout.
  - `astock scan --as-of YYYY-MM-DD` — runs the chain, writes the candidate snapshot, and prints the candidate count and their `next_action` values.
  - `GET /factors?symbol=<symbol>&as_of=YYYY-MM-DD` — reads a stored factor snapshot. It never recomputes.
  - `GET /candidates?as_of=YYYY-MM-DD` — reads a stored candidate snapshot.

**API rules:** both routes return `404` with an explicit `detail` when no snapshot exists for the requested date. Neither route imports the factor or strategy engines, because `docs/ARCHITECTURE.md` §2 forbids the API from recomputing. A test asserts this by inspecting the route module's imports.

- [ ] **Step 1: Write the failing integration test**

Drive the full chain from `tests/fixtures/csv/daily_bars.csv` and assert the invariants that define the slice: every `FactorResult` has a `factor_version` and an `as_of`; no missing input ever produced a `0`; a symbol with fewer bars than the window is `NULL`, not a number; every candidate's `next_action` is a legal enum member; the written snapshot round-trips through `JsonSnapshotStore`.

- [ ] **Step 2: Run it and confirm it fails**

- [ ] **Step 3: Implement `run_first_slice`, the two CLI commands, and the two API routes**

- [ ] **Step 4: Update `README.md`**

Move the shipped items out of "尚未实现" and state plainly what is still missing: no strategy scoring, `next_action` fixed at `IGNORE`, JSON snapshots rather than DuckDB, no Universe engine, no market or signal layer.

- [ ] **Step 5: Run the full gate**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run astock doctor
uv run astock factors compute --as-of 2026-09-15
uv run astock scan --as-of 2026-09-15
```

- [ ] **Step 6: Commit and open the PR**

```bash
git add -A && git commit -m "feat(pipeline): expose first slice through cli and api"
git push -u origin feat/first-vertical-slice
gh pr create --base main --title "feat: first vertical slice" --body-file .superpowers/sdd/2026-09-16-first-vertical-slice/pr-body.md
```

---

## Final State

When all six tasks are complete, `astock scan --as-of <date>` runs

`CSV → RawDataset → NormalizedDataset → QualityReport → FactorResult → StrategyResult → Candidate`

end to end from a clean clone with no network access and no optional dependency installed, and the same artifacts are readable back through `GET /factors` and `GET /candidates`.

Deliberately still absent, and named in `README.md` so the gap stays visible: strategy scoring and ranking, the routing rule for `next_action`, the Universe engine, the market regime and signal layers, DuckDB/Parquet persistence, and the AkShare provider.
