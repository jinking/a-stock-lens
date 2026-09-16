# A-Stock Lens Daily Scan Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the first slice's single-factor, unranked pipeline into a real daily scan — an immutable Universe snapshot, the momentum factors the design actually names, a cross-sectional score whose weights live in YAML, a routing rule that follows from that score, DuckDB persistence behind the existing `SnapshotStore` protocol, and a recorded AkShare provider whose contract tests run offline.

**Architecture:** The approved modular monolith and its one-way dependency direction are unchanged. This slice extends `data → universe → factors → strategies → candidates` and adds a provider, without inventing a single threshold or vocabulary the design does not already name. Two contracts gain fields only where the previous shape was provably insufficient (`NormalizedDataset.securities`, `StrategyResult.contributions`); every other extension is a new module behind an existing Protocol.

**Tech Stack:** Python 3.12+, Pydantic 2, PyYAML, Typer, FastAPI, pytest, Ruff, mypy (strict), uv. Optional extras `data` (DuckDB) and `providers` (AkShare) become exercisable but stay optional — the default environment and the default test run must keep working without them.

**Spec:** `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`

**Base:** `main` at `c6ecf1c`. Branch: `feat/daily-scan-slice` (cut from `main`, not from `feat/first-vertical-slice`).

---

## Global Constraints

Inherited from the bootstrap plan and still binding:

- Precedence is design spec → `docs/PRODUCT.md` → `docs/ARCHITECTURE.md` → `README.md`.
- Dependency direction `Provider → Raw → Normalized → Data Quality Gate → Universe → Factor → Strategy → Market → Signal → Candidate → Watchlist → Deep Research` is one-way and never reversed.
- Strategies never call a provider. API and Web never recompute factors. Providers never contain strategy decisions.
- Missing-data states are exactly `VALUE`, `NULL`, `STALE`, `INVALID`, `SOURCE_ERROR`, `NOT_APPLICABLE`. **A missing value never becomes `0`.**
- Time-sensitive results carry `as_of`. Timestamps are timezone-aware (`DTZ001`).
- Snapshots carry `universe_snapshot`, `factor_version`, `strategy_version` lineage.
- Candidate is a research object, never a recommendation.
- Unknown thresholds and weights stay absent or explicitly deferred. Do not invent product rules.
- Every behaviour change starts with a failing test. No behaviour change commits without failure evidence.

Additional constraints this slice introduces:

- **An engine that ends up in the default test path must not import an optional dependency at module scope.** `duckdb` and `akshare` are imported inside the function that needs them, and absence raises a message naming the extra to install.
- **A rule that is configured `true` but has no reviewed threshold is reported as `DEFERRED`, never silently dropped and never guessed into existence.**

## Slice Decisions

Each decision is a ruling this slice introduces. They are recorded so a reviewer can reject any of them before implementation is trusted.

**D1 — The Universe liquidity floor is 20,000,000 CNY (`min_average_turnover_20d: 20000000`).** Confirmed by the project owner on 2026-09-16 in answer to a direct question. This is the only number in the slice that came from a human rather than from a document. `configs/universe.yaml` keeps the value; no code default exists, so deleting the key is an error rather than a silent fallback.

**D2 — "Long suspension" stays deferred and is reported, not guessed.** `docs/ARCHITECTURE.md` §6 names a long-suspension exclusion but fixes no day count, and the design contains no candidate value. `configs/universe.yaml` therefore gains `long_suspension_days: null`, and `UniverseBuilder` records `LONG_SUSPENSION` in `UniverseSnapshot.deferred_rules` while excluding nobody on that basis. Recording the gap is the point: a reader can see the rule exists, is not applied, and why. *Cost if wrong: the Universe is wider than intended until the owner supplies a number.*

**D3 — Momentum gets real momentum factors before it gets a score.** The only factor in the repository is `avg_amount_20d`, a liquidity measure. Scoring a momentum strategy with it would rank symbols by turnover and label the result "momentum". This slice adds `ret_20d`, `ret_60d`, and `proximity_52w_high`, all derivable from the daily bars already stored, and scores only after they exist.

**D4 — Scoring is a cross-sectional percentile blend, and the weights are an equal-weight draft marked for review.** `docs/ARCHITECTURE.md` §8.3 puts weights in YAML. No weight has been reviewed, so `configs/strategies/momentum.yaml` carries an explicit `weights:` block whose entries are equal and whose comment says so. Equal weighting is chosen precisely because it is the only assignment that states no preference: any other split asserts that one named factor matters more than another, which is a product claim nobody has made. The mechanism is fixed and testable; the numbers are marked `PENDING REVIEW`.

**D5 — `next_action` follows from the score by ordering, with no magic number.** `eligible and score is not None` → `WATCH`; otherwise → `IGNORE`. No percentile cut, no threshold. `DEEP_RESEARCH` and `TRACK_SIGNAL` need the signal layer, which this slice does not build, so they stay unreachable rather than approximated.

**D6 — `confidence` stays `None`.** The design requires the field but defines no algorithm for it. With `required_factors` gating eligibility, every eligible symbol contributes every factor, so a "fraction of factors present" definition would be a constant `1.0` — a field that looks informative and is not. It stays `None` with a stated reason.

**D7 — DuckDB implements `SnapshotStore`; it does not replace it.** `docs/ARCHITECTURE.md` §14 specifies DuckDB, and the JSON store shipped in the previous slice was explicitly interim. The new `DuckDBSnapshotStore` satisfies the same Protocol, is selected by configuration, and is exercised by tests that skip when the `data` extra is absent.

**D8 — AkShare is verified against a recorded fixture, and the recording script is committed.** A provider tested only against hand-written rows proves the parser agrees with itself. `scripts/record_akshare_fixture.py` performs one real fetch and writes the raw response under `tests/fixtures/akshare/`; the contract test replays that file and needs no network. If the recording could not be performed, the fixture is marked as synthetic in its header and this plan says so — a fabricated fixture is never passed off as a recording.

**D9 — New fixtures are added, never substituted into old ones.** `tests/fixtures/csv/daily_bars.csv` is the input to five existing test modules with hand-computed expectations. Lengthening it would silently move the trailing windows those expectations were computed over, and the "fix" would look like an author editing tests to match output. The long-history fixture is therefore a new file, and every existing assertion stays byte-identical.

**D10 — Fixtures are generated by a committed script.** `scripts/generate_fixtures.py` writes the CSV fixtures from an explicit, reviewable formula. Hand-maintained 300-row files cannot be audited; a script that prints the formula can.

**D11 — An independent Artifact Validator lands with the first real scores.** `docs/ARCHITECTURE.md` §20.2 requires checks that do not trust internal implementation: snapshot completeness, score range, factor references that resolve, versions present, `available_at <= as_of`, candidate lineage consistency. Scores are the first artefact whose correctness cannot be read off a single function, so the validator stops being optional here.

## Out of Scope

Named so their absence is a decision, not an omission: Market Regime, Strategy Router, Market Validation, Signals, Watchlist lifecycle, the remaining six scanners, Parquet materialisation, Deep Research Adapter, and the React front end.

---

### Task 1: Universe Engine

**Files:**
- Create: `src/astock_lens/universe/config.py`
- Create: `src/astock_lens/universe/models.py`
- Create: `src/astock_lens/universe/builder.py`
- Modify: `src/astock_lens/universe/__init__.py`
- Modify: `src/astock_lens/domain/models.py` (add `SecurityProfile`)
- Modify: `src/astock_lens/data/contracts.py` (add `NormalizedDataset.securities`)
- Create: `src/astock_lens/data/normalize/csv_securities.py`
- Modify: `configs/universe.yaml`
- Create: `tests/fixtures/csv/securities.csv`
- Create: `tests/unit/test_universe_config.py`
- Create: `tests/unit/test_csv_security_normalizer.py`
- Create: `tests/unit/test_universe_builder.py`

**Interfaces:**

- Consumes: `data.contracts.NormalizedDataset`, `factors.contracts.FactorResult`, `domain.enums.DataStatus`
- Produces:
  - `SecurityProfile(symbol, name, exchange, list_date, is_st, is_delisting_board, suspended_trading_days)`
  - `UniverseConfig(exchanges, exclude_st, exclude_delisting_board, exclude_long_suspension, long_suspension_days, min_listing_days, min_average_turnover_20d, require_valid_market_data)` + `load_universe_config(path)`
  - `UniverseExclusion(symbol, rule, detail)`
  - `DeferredRule(rule, reason)`
  - `UniverseSnapshot(as_of, snapshot_id, config_digest, included, exclusions, deferred_rules, lineage)`
  - `UniverseBuilder(config).build(profiles, *, as_of, bars, liquidity) -> UniverseSnapshot`
  - `CsvSecurityNormalizer().normalize(dataset, *, as_of) -> NormalizedDataset`

**Error model (stated, not implied):**

- A *required* key that is absent is a configuration error, and `extra="forbid"` makes a mistyped key an error too — a misspelled threshold must not leave the previous value silently in force. The liquidity floor and the minimum listing age are required, so neither has a code default.
- Deferral is expressed by `exclude_long_suspension: true` together with `long_suspension_days: null`. The configuration still loads, the builder excludes nobody on that rule, and `UniverseSnapshot.deferred_rules` records why. A rule that cannot be evaluated is reported; it is never dropped and never guessed.
- `liquidity` is a mapping of symbol to that symbol's `avg_amount_20d` result. A symbol with no `VALUE` result is excluded with rule `NO_LIQUIDITY_MEASURE` when `require_valid_market_data` is set, and included otherwise. A measured value below the floor is excluded with `LOW_LIQUIDITY` regardless of that switch, because that is a product rule rather than a data-availability rule. The builder never substitutes `0`.

**Steps:**

- [ ] Write `tests/unit/test_universe_config.py` and `tests/unit/test_universe_builder.py` first; confirm both fail with `ModuleNotFoundError`.
- [ ] Add `SecurityProfile` to `domain/models.py` — it lives in `domain` and not in `universe` because the normalizer in `data` must produce it, and `data → universe` imports would reverse the dependency direction.
- [ ] Add `NormalizedDataset.securities: tuple[SecurityProfile, ...] = ()`.
- [ ] Implement `universe/config.py`, `universe/models.py`, `universe/builder.py`, `data/normalize/csv_securities.py`.
- [ ] Set `min_average_turnover_20d: 20000000` and add `long_suspension_days: null` in `configs/universe.yaml`, with a comment naming D1 and D2.
- [ ] Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`.
- [ ] Commit: `feat(universe): add universe engine and immutable universe snapshot`.

---

### Task 2: Long-History Fixture and Momentum Factors

**Files:**
- Create: `scripts/generate_fixtures.py`
- Create: `tests/fixtures/csv/daily_bars_long.csv`
- Modify: `src/astock_lens/factors/builtin.py`
- Create: `configs/factors/ret_20d.yaml`, `ret_60d.yaml`, `proximity_52w_high.yaml`
- Create: `tests/unit/test_trailing_return_factor.py`
- Create: `tests/unit/test_proximity_high_factor.py`

**Interfaces:**

- Produces:
  - `TrailingReturnFactor(factor_config)` where `params.window` is required; `raw_value = close_last / close_first - 1` over `window + 1` bars.
  - `ProximityToHighFactor(factor_config)`; `raw_value = close_last / max(high over window bars)`.

**Rules that must hold (each gets its own test):**

- Fewer than `window + 1` bars → `NULL`, `raw_value is None`. The window is never shortened to fit.
- Any `close` (respectively `high`) that is `None` inside the window → `NULL`. A hole is not interpolated.
- A `close_first` of `0` → `NULL`, because the ratio is undefined; the factor does not return infinity.
- Bars after `as_of` are never used, even when present in the dataset.
- `proximity_52w_high` declares `window: 252` in YAML with a comment recording that 52 weeks ≈ 252 trading days; the conversion is stated, not assumed silently.

**Steps:**

- [ ] Write `scripts/generate_fixtures.py`: it regenerates `securities.csv` and `daily_bars_long.csv` from explicit formulas and prints each symbol's intended Universe verdict and expected factor values, so the fixture and the assertions share one source of truth. It must **not** touch `daily_bars.csv` or `dirty_bars.csv` (D9).
- [ ] Generate `daily_bars_long.csv`: ~300 trading days ending 2026-09-04, covering the Universe edge cases (clean, ST, delisting-board, short listing age, low liquidity, no bar on `as_of`) and at least four symbols with distinct, hand-verifiable momentum profiles.
- [ ] Write the two factor test modules first; confirm failure.
- [ ] Implement both factors; no default window anywhere.
- [ ] Write the three YAML factor configs.
- [ ] Run the full gate; commit: `feat(factors): add momentum factors with explicit windows`.

---

### Task 3: Cross-Sectional Scoring and Next-Action Routing

**Files:**
- Modify: `src/astock_lens/strategies/contracts.py` (add `FactorContribution`, `StrategyResult.contributions`)
- Modify: `src/astock_lens/strategies/config.py` (add `weights`)
- Create: `src/astock_lens/strategies/scoring.py`
- Modify: `src/astock_lens/strategies/momentum.py` (add `score_cross_section`)
- Create: `src/astock_lens/candidates/routing.py`
- Modify: `src/astock_lens/factors/builtin.py` (add `build_factor`)
- Modify: `src/astock_lens/factors/registry.py` (add `build_registry`)
- Modify: `src/astock_lens/pipelines/first_slice.py` (compute every configured factor)
- Modify: `src/astock_lens/cli/app.py` (load every factor config; `ASTOCK_DATASET`)
- Modify: `configs/strategies/momentum.yaml`
- Create: `tests/unit/test_strategy_scoring.py`
- Create: `tests/unit/test_candidate_routing.py`
- Modify: `tests/unit/test_momentum_scanner.py` (read factor names from configuration)
- Modify: `tests/unit/test_cli.py` (scan against the long fixture)
- Modify: `tests/integration/test_first_slice.py` (state its own single-factor pairing)

**Deviation recorded during execution.** Changing `momentum`'s `required_factors`
turned out to force the CLI and the first-slice pipeline to compute every
configured factor rather than one hardcoded factor. Left alone, `astock scan`
would have printed `candidates: 0` — a configuration mismatch that reads
exactly like a market verdict, which the design's "data problems must be
visible" principle exists to prevent. That work was pulled forward from Task 6
into Task 3 instead of being committed as a known-broken intermediate state.

**Interfaces:**

- `StrategyConfig.weights: dict[str, float] = {}` — empty means "no reviewed weights, do not score", preserving the previous slice's behaviour exactly.
- A non-empty `weights` must cover `required_factors` exactly; a mismatch raises, so a configured factor cannot be silently unweighted.
- `percentile_ranks(values: Mapping[str, float]) -> Mapping[str, float]` in `scoring.py`: ties share the average rank, and a single-element input maps to `1.0`. The rule is stated once and tested, because two implementations of "percentile" is how rankings drift.
- `MomentumScanner.score_cross_section(contexts) -> tuple[StrategyResult, ...]`:
  1. `eligibility` per symbol (unchanged, requires every `required_factors` entry to be `VALUE`);
  2. over the **eligible** set only, percentile-rank each factor;
  3. `score = 100 * Σ(w_i * pct_i) / Σ(w_i)`;
  4. `rank_percentile` = percentile of `score` within the eligible set, `None` when fewer than two symbols are eligible;
  5. `contributions` records `(factor, percentile, weight, weighted)` per factor for explainability.
- `MomentumScanner.score(context)` keeps its current signature and keeps returning `None` for the ranking fields, because a single context has no cross-section to rank against.
- `route_next_action(result) -> NextAction` implements D5.

**Rules that must hold:**

- An ineligible symbol is excluded from the percentile population. Including it would let an ineligible name move an eligible name's rank.
- `score` is always within `[0, 100]`; the validator in Task 7 re-asserts this on the artefact rather than trusting the function.
- Weights are read from YAML at construction; no weight literal appears in `momentum.py`.

**Steps:**

- [ ] Write `tests/unit/test_strategy_scoring.py` and `tests/unit/test_candidate_routing.py` first; confirm failure.
- [ ] Extend the contract, config, scanner, and add `scoring.py` and `routing.py`.
- [ ] Add the `weights:` block to `momentum.yaml` with the equal-weight draft and a `PENDING REVIEW` comment naming D4.
- [ ] Update `tests/unit/test_momentum_scanner.py` to read factor names from the configuration. Its assertions keep their intent — `score()` still reports no score for a lone symbol — but they must stop naming `avg_amount_20d`, which momentum no longer requires.
- [ ] Run the full gate; commit: `feat(strategies): add cross-sectional scoring and next-action routing`.

---

### Task 4: DuckDB Snapshot Store

**Files:**
- Create: `src/astock_lens/data/snapshots/duckdb_store.py`
- Modify: `src/astock_lens/data/snapshots/__init__.py`
- Modify: `src/astock_lens/cli/app.py` (`doctor` reports backend availability)
- Create: `tests/unit/test_duckdb_snapshot_store.py`

**Interfaces:**

- `DuckDBSnapshotStore(database: Path)` implements `SnapshotStore` (`write`, `read`) plus:
  - `latest(kind) -> tuple[dict[str, object], ...]` — the most recent `as_of` for that kind;
  - `dates(kind) -> tuple[str, ...]` — dates that actually have a snapshot, so an empty database is answerable rather than an error.
- Schema: one table, `snapshots(kind VARCHAR, as_of DATE, payload JSON, written_at TIMESTAMPTZ)`, primary key `(kind, as_of)`. `write` replaces the row for the same key — re-running a scan for one date must not accumulate duplicates.
- `duckdb` is imported inside methods. When it is missing, the error names `uv sync --extra data`.

**Steps:**

- [ ] Write `tests/unit/test_duckdb_snapshot_store.py` first, with `pytest.importorskip("duckdb")` so the default environment still runs green; confirm it skips (not passes) before the extra is installed.
- [ ] Run `uv sync --extra data` and confirm the tests then execute and fail on the missing module.
- [ ] Implement the store.
- [ ] Prove store interchangeability: the same round-trip assertions run against both `JsonSnapshotStore` and `DuckDBSnapshotStore` through the Protocol.
- [ ] Run the full gate; commit: `feat(data): add duckdb snapshot store`.

---

### Task 5: AkShare Provider and Recorded Fixture

**Files:**
- Create: `src/astock_lens/data/providers/akshare_provider.py`
- Create: `scripts/record_akshare_fixture.py`
- Create: `tests/fixtures/akshare/*.csv` (recorded)
- Create: `tests/unit/test_akshare_provider.py`
- Modify: `src/astock_lens/data/providers/__init__.py`

**Interfaces:**

- `AkShareProvider(*, provider="akshare", version=...)` implements `DataProvider`.
- Datasets: `daily_bars` and `securities`.
- `fetch` maps AkShare's Chinese column names onto the raw column names the existing `LocalCsvProvider` already emits, so the same normalizer consumes both providers. That mapping is code; it contains no threshold.
- Every network failure, empty response, or unexpected column set returns a `RawDataset` with `DataStatus.SOURCE_ERROR` and a `row_count` matching reality — never a row of zeros, never an exception escaping to the caller.

**Steps:**

- [ ] Run `uv sync --extra providers` and confirm `import akshare` succeeds.
- [ ] Write `scripts/record_akshare_fixture.py` and execute it once against the live API, writing the raw response verbatim under `tests/fixtures/akshare/` with a header recording source, endpoint, fetch timestamp, and the AkShare version.
- [ ] If the recording cannot be made, stop and report it rather than substituting hand-written rows; a synthetic fixture must be labelled synthetic in its header (D8).
- [ ] Write the contract test against the recorded file; it performs no network call and asserts the column mapping, the `as_of` handling, and the source-error path.
- [ ] Run the full gate; commit: `feat(data): add akshare provider with recorded contract fixture`.

---

### Task 6: Daily Scan Pipeline, CLI, and API

**Files:**
- Create: `src/astock_lens/pipelines/daily_scan.py`
- Modify: `src/astock_lens/pipelines/__init__.py`
- Modify: `src/astock_lens/cli/app.py`
- Modify: `src/astock_lens/api/app.py`
- Create: `tests/integration/test_daily_scan.py`
- Modify: `tests/unit/test_cli.py`, `tests/unit/test_api.py`
- Modify: `README.md`

**Interfaces:**

- `run_daily_scan(*, csv_root, as_of, universe_config, factor_configs, strategy_config, store, dataset, securities_dataset) -> DailyScanResult`, running `NORMALIZE → BUILD_UNIVERSE → COMPUTE_FACTORS → RUN_STRATEGIES → BUILD_CANDIDATES` and writing `UNIVERSE`, `FACTOR`, `STRATEGY`, and `CANDIDATE` snapshots.
- `DailyScanResult` carries the universe snapshot, the quality report, factor results, strategy results, candidates, and the paths written.
- `astock universe build --as-of YYYY-MM-DD` — new.
- `astock factors compute --as-of YYYY-MM-DD` — now computes every factor configured under `configs/factors/`.
- `astock scan --as-of YYYY-MM-DD` — now runs the daily scan; prints symbols, scores, and next actions.
- `GET /universe?as_of=`, plus `GET /factors` and `GET /candidates` served through whichever store is configured. A missing snapshot is still a 404 naming the date.

**Steps:**

- [ ] Write `tests/integration/test_daily_scan.py` first: the full chain over `daily_bars_long.csv`, asserting that each Universe exclusion reason fires on the symbol designed to trigger it, that the ranking order matches the hand-computed order, that `next_action` follows D5, and that a second run for the same date overwrites rather than duplicates.
- [ ] Update `tests/unit/test_cli.py` and `tests/unit/test_api.py` to the new commands, using the long fixture. The assertions' *intent* is unchanged; only the fixture moves.
- [ ] Implement the pipeline, CLI, and API.
- [ ] Confirm `tests/integration/test_first_slice.py` still passes. It now states its own single-factor strategy pairing instead of borrowing `momentum.yaml`, because the previous slice's pairing is historical: the momentum strategy ranks on returns, not on liquidity. `run_first_slice` itself gained the multi-factor loop in Task 3.
- [ ] Run the whole chain by hand through the CLI and paste the real output into the PR body.
- [ ] Update `README.md`: the status table, the new commands, and an explicit list of what is still missing.
- [ ] Run the full gate; commit: `feat(pipeline): add daily scan pipeline with universe and scoring`.

---

### Task 7: Independent Artifact Validator

**Files:**
- Create: `tests/artifacts/__init__.py`
- Create: `tests/artifacts/validator.py`
- Create: `tests/artifacts/test_snapshot_validator.py`

**Interfaces:**

- `validate_snapshot(kind, records, *, as_of, known_factor_names, known_strategy_ids) -> tuple[ArtifactFinding, ...]`, where each finding names the check, the symbol, and what was observed.
- Checks, each traceable to `docs/ARCHITECTURE.md` §20.2: required keys present; `score` within `[0, 100]` when not `None`; `rank_percentile` within `[0, 1]` when not `None`; every `factor_snapshot` entry resolves to a name in `known_factor_names`; `factor_version` and `strategy_version` non-empty; every timestamp timezone-aware and not later than `as_of`; a candidate's lineage version equals the version on the strategy result it cites.

**Steps:**

- [ ] Write the validator and its tests first, driving it with deliberately corrupted records — the validator must be seen failing before it is trusted passing.
- [ ] Run it against the real snapshots produced by Task 6.
- [ ] Run the full gate; commit: `test(artifacts): add independent snapshot validator`.

---

## Verification

The slice is done when, on a clean clone:

```bash
uv sync --extra data --extra providers
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run astock doctor
uv run astock universe build --as-of 2026-09-04
uv run astock factors compute --as-of 2026-09-04
uv run astock scan --as-of 2026-09-04
```

all succeed, `uv sync` **without** the extras still yields a green default `uv run pytest`, and the Universe exclusions, the ranking order, and the `next_action` values in the final command match the values this plan's fixtures were designed to produce.
