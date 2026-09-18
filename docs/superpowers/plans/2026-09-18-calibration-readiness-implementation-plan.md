# Calibration Readiness / Research Universe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-ready calibration input pipeline that reduces the expensive research population from the full A-share listing (~5,500 symbols) to a strategy-independent Research Universe that normally lands around 2,000–3,000 symbols, then produces a decision-grade full-market calibration report for owner approval of six strategy absolute qualification rules.

**Architecture:** Keep the complete exchange listing as lightweight master data. Use only strategy-independent eligibility rules plus the already-approved 20-day average turnover threshold to form a Research Universe; only that Research Universe receives expensive history/fundamental/valuation enrichment and six-strategy scoring. Make cold-start sync resumable, eliminate the current `strategy_stage` quadratic factor lookup, add a canonical industry-membership pipeline, then upgrade calibration output so absolute-rule decisions can be made from real distributions and boundary samples.

**Tech Stack:** Python >=3.12, Pydantic 2.x, Typer, pytest, Ruff, mypy, existing AkShare/WeStock/neodata providers, current JSON/DuckDB snapshot abstractions.

**Spec:** `docs/superpowers/specs/2026-09-17-candidate-qualification-design.md`

## Approved Addendum — Research Universe

The owner approved the following additional product semantics on 2026-09-18:

1. The full exchange listing (~5,500 symbols) remains the authoritative lightweight master universe.
2. Expensive strategy/calibration processing should normally run on a smaller **Research Universe**, targeting approximately **2,000–3,000 symbols**.
3. **2,500 is a target center, not a hard quota.**
4. Never relax or tighten research criteria merely to force the result to exactly 2,500 symbols.
5. Research Universe filtering must be strategy-independent. It may use:
   - configured exchanges;
   - ST exclusion;
   - delisting-board exclusion;
   - minimum listing age;
   - valid market-data requirement;
   - the already-approved `avg_amount_20d >= 20,000,000` CNY liquidity threshold;
   - future owner-approved Universe rules.
6. Do not use Value/Growth/Quality/GARP/Dividend/Momentum scores to decide Research Universe membership.
7. The population used for Candidate Qualification calibration must match the population used by the actual production strategy scan. Do not calibrate on ~5,500 symbols and then operate on ~2,500.
8. A cold start may fetch a minimal liquidity-bootstrap history for the broad listing because `avg_amount_20d` must be measured before Research Universe membership is known. Expensive full-history/fundamental/valuation enrichment happens only after Research Universe selection.
9. Production Candidate publishing remains BLOCKED until six absolute qualification rules and Market/Validation/Signal upstream rules are approved and implemented.

## Global Constraints

- Do not invent any new investment/product threshold.
- Existing `configs/universe.yaml` is the single source of truth for Universe thresholds.
- Keep `min_average_turnover_20d = 20_000_000` exactly as currently approved.
- Keep `min_listing_days = 120` exactly as currently configured.
- Keep long-suspension threshold Deferred; do not assign a number.
- Do not create `configs/qualifications/*.yaml` production rules in this plan.
- Do not modify the approved Candidate policy: percentile floor 0.90, soft reserve 3, max 50, no hard minimum, no cross-strategy global score.
- `astock daily` remains the only formal Snapshot writer.
- Calibration commands remain read-only with respect to Snapshot / Watchlist / Job state.
- Provider failures must be visible and resumable; never fill missing data with zero.
- Any test touching a provider must inject a stub unless explicitly marked operator-run smoke/integration.
- Use TDD: failing test → minimal implementation → passing test → focused commit.
- Commit and push after every task. Commit messages and project documentation remain Chinese.
- At an explicit **STOP GATE**, do not continue by inventing a value or source.

---

## Locked Data Flow

```text
Exchange Listing (~5,500)
        │ lightweight master data
        ▼
Listing Eligibility
(exchange/ST/delisting/listing-age)
        │ minimal liquidity bootstrap history only
        ▼
avg_amount_20d + valid-market-data
        │
        ▼
Research Universe (~2,000–3,000 target, NOT fixed quota)
        │
        ├── full strategy-required price history
        ├── financial statements
        ├── valuation data
        └── industry membership
        │
        ▼
24 Factors
        ▼
6 StrategyResults
        ▼
Decision-grade Calibration Report
        ▼
OWNER APPROVES 6 ABSOLUTE QUALIFICATION RULES
```

The Research Universe is the denominator for strategy percentile ranking and calibration.

---

## File Structure Locked by This Plan

### Create

- `src/astock_lens/universe/prefilter.py` — listing-only prefilter using existing Universe semantics.
- `src/astock_lens/data/bootstrap.py` — bootstrap-history requirements and resumable chunk orchestration.
- `src/astock_lens/data/industry.py` — canonical `IndustryMembership` and map assembly.
- `src/astock_lens/data/normalize/industry.py` — neodata industry normalization.
- `src/astock_lens/calibration/factor_distribution.py` — factor distributions and boundary samples.
- `tests/unit/test_universe_prefilter.py`
- `tests/unit/test_bootstrap_sync.py`
- `tests/unit/test_strategy_factor_index.py`
- `tests/unit/test_industry_membership.py`
- `tests/unit/test_calibration_factor_distribution.py`
- `tests/integration/test_research_universe_flow.py`
- `tests/integration/test_calibration_readiness_cli.py`
- `docs/superpowers/plans/2026-09-18-calibration-readiness-implementation-plan.md`

### Modify

- `src/astock_lens/pipelines/stages.py`
- `src/astock_lens/pipelines/analysis.py`
- `src/astock_lens/data/sync.py`
- `src/astock_lens/data/providers/akshare_provider.py`
- `src/astock_lens/data/providers/neodata.py`
- `src/astock_lens/cli/app.py`
- `src/astock_lens/calibration/candidate_report.py`
- `src/astock_lens/calibration/render.py`
- `src/astock_lens/universe/builder.py` only if shared rule helpers must be extracted to avoid duplicated semantics.
- `docs/ROADMAP.md`
- `docs/REVIEW_NOTES.md`
- `configs/factors/README.md`
- `.workbuddy/memory/2026-09-18.md`

### Do Not Create Yet

- `configs/qualifications/value.yaml`
- `configs/qualifications/growth.yaml`
- `configs/qualifications/garp.yaml`
- `configs/qualifications/quality.yaml`
- `configs/qualifications/dividend.yaml`
- `configs/qualifications/momentum.yaml`

---

# Task 1: Pin the Research-Universe Contract and Repair Documentation Drift

**Files:**
- Create: `tests/unit/test_universe_prefilter.py`
- Create: `src/astock_lens/universe/prefilter.py`
- Modify: `docs/ROADMAP.md`
- Modify: `configs/factors/README.md`
- Modify: `.workbuddy/memory/2026-09-18.md`

**Interfaces:**

```python
class PrefilterResult(DomainRecord):
    included: tuple[str, ...]
    excluded: tuple[UniverseExclusion, ...]


def prefilter_listing(
    securities: Sequence[SecurityProfile],
    *,
    config: UniverseConfig,
    as_of: datetime,
) -> PrefilterResult:
    ...
```

The prefilter may apply only exchange/ST/delisting/min-listing-age rules. It must not evaluate liquidity, market-data validity, long suspension, or any strategy score.

- [ ] Write failing tests proving ST, wrong exchange, and <120-day listings are excluded; mature normal symbols pass; no strategy config is accepted.
- [ ] Run `uv run pytest tests/unit/test_universe_prefilter.py -v` and verify RED.
- [ ] Implement the prefilter by reusing/extracting existing `UniverseBuilder` rule helpers. Do not duplicate rule semantics.
- [ ] Run:

```bash
uv run pytest tests/unit/test_universe_prefilter.py tests/unit/test_universe_builder.py -v
uv run ruff check src/astock_lens/universe tests/unit/test_universe_prefilter.py
uv run mypy src/astock_lens/universe
```

- [ ] Repair Roadmap baseline using actual `git rev-parse HEAD` and `uv run pytest -q`; remove stale “d964422 / 674 / 3 symbols” claims.
- [ ] Expand `configs/factors/README.md` from stale 4-factor list to actual current factor configs.
- [ ] Commit:

```bash
git add src/astock_lens/universe/prefilter.py tests/unit/test_universe_prefilter.py docs/ROADMAP.md configs/factors/README.md .workbuddy/memory/2026-09-18.md
git commit -m "宇宙：钉住研究池前置筛选边界"
git push
```

---

# Task 2: Remove the Strategy-Stage Quadratic Factor Lookup

**Files:**
- Create: `tests/unit/test_strategy_factor_index.py`
- Modify: `src/astock_lens/pipelines/stages.py`

**Interfaces:**

```python
class FactorResultIndex:
    def __init__(self, results: Sequence[FactorResult]) -> None: ...
    def for_symbol(self, symbol: str) -> tuple[FactorResult, ...]: ...
```

- [ ] Write a behavioral parity test proving indexed and current strategy results are identical on fixtures.
- [ ] Write an anti-regression test using an observable `CountingSequence`; factor results must not be rescanned once per `(scanner, symbol)` pair.
- [ ] Run `uv run pytest tests/unit/test_strategy_factor_index.py -v` and verify current implementation fails the scan-count assertion.
- [ ] Build the index exactly once in `strategy_stage()` and replace repeated `results_for(factor_results, symbol)` scans with indexed lookup.
- [ ] Delete `results_for()` only if repository search proves no production references remain.
- [ ] Run:

```bash
uv run pytest tests/unit/test_strategy_factor_index.py tests/unit -q
uv run ruff check src/astock_lens/pipelines/stages.py tests/unit/test_strategy_factor_index.py
uv run mypy src/astock_lens/pipelines/stages.py
```

- [ ] Commit:

```bash
git add src/astock_lens/pipelines/stages.py tests/unit/test_strategy_factor_index.py
git commit -m "性能：为策略阶段建立因子结果索引"
git push
```

---

# Task 3: Derive the Minimal Liquidity-Bootstrap Requirement From Factor Config

**Files:**
- Create: `src/astock_lens/data/bootstrap.py`
- Create/Modify: `tests/unit/test_bootstrap_sync.py`
- Modify: `src/astock_lens/cli/app.py`

**Interfaces:**

```python
class BootstrapRequirement(DomainRecord):
    factor_name: str
    required_valid_bars: int


def liquidity_bootstrap_requirement(
    factor_configs: Sequence[FactorConfig],
) -> BootstrapRequirement:
    ...
```

- [ ] Write tests proving current configs resolve `avg_amount_20d` and its configured window.
- [ ] Prove removing the factor fails loudly.
- [ ] Prove a test config with another window changes `required_valid_bars`; implementation must not hard-code 20.
- [ ] Add read-only CLI `astock universe bootstrap-requirement`, returning JSON with factor name, required bars, current liquidity threshold, and min listing days.
- [ ] Run:

```bash
uv run pytest tests/unit/test_bootstrap_sync.py tests/unit/test_cli_lifecycle.py -v
```

- [ ] Commit:

```bash
git add src/astock_lens/data/bootstrap.py tests/unit/test_bootstrap_sync.py src/astock_lens/cli/app.py
git commit -m "数据：从配置推导研究池流动性启动窗口"
git push
```

---

# Task 4: Make Broad-Market Bootstrap Sync Resumable and Failure-Isolated

**Files:**
- Modify: `src/astock_lens/data/sync.py`
- Modify: `src/astock_lens/data/providers/akshare_provider.py`
- Modify: `src/astock_lens/data/bootstrap.py`
- Modify: `src/astock_lens/cli/app.py`
- Modify: `tests/unit/test_bootstrap_sync.py`
- Create: `tests/integration/test_research_universe_flow.py`

**Interfaces:**

```python
class ChunkSyncResult(DomainRecord):
    requested_symbols: tuple[str, ...]
    completed_symbols: tuple[str, ...]
    failed_symbols: tuple[str, ...]
    rows_written: int


def land_bar_chunks(
    *,
    provider: DataProvider,
    root: Path,
    as_of: datetime,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    chunk_size: int,
) -> ChunkSyncResult:
    ...
```

Use technical default `chunk_size=50`, exposed/configurable; it is not a product threshold.

- [ ] Create a fake provider where one symbol fails after previous symbols succeed; new expected behavior is previous success remains persisted and rerun retries only missing coverage.
- [ ] Refactor AkShare bar fetch to expose a single-symbol primitive while preserving the existing `fetch(FetchRequest)` contract.
- [ ] Implement deterministic chunk landing. Persist each completed chunk before proceeding. Collect symbol-level failures. Never fabricate missing rows.
- [ ] Add `astock sync-bootstrap --as-of YYYY-MM-DD --chunk-size 50`.
- [ ] Bootstrap flow:
  1. update securities listing;
  2. run listing prefilter;
  3. request a bounded recent range;
  4. validate **actual valid bar count** against the config-derived requirement;
  5. extend backward only for symbols still short until requirement is met or source history is exhausted.
- [ ] Do not use a fixed calendar-day count as the semantic success condition.
- [ ] Run:

```bash
uv run pytest tests/unit/test_bootstrap_sync.py tests/integration/test_research_universe_flow.py -v
```

- [ ] Commit:

```bash
git add src/astock_lens/data/bootstrap.py src/astock_lens/data/sync.py src/astock_lens/data/providers/akshare_provider.py src/astock_lens/cli/app.py tests/unit/test_bootstrap_sync.py tests/integration/test_research_universe_flow.py
git commit -m "数据：让全市场启动行情支持分块落地与断点续跑"
git push
```

---

# Task 5: Materialize the Research Universe Before Expensive Enrichment

**Files:**
- Modify: `src/astock_lens/pipelines/analysis.py`
- Modify: `src/astock_lens/pipelines/stages.py`
- Modify: `src/astock_lens/cli/app.py`
- Modify: `tests/integration/test_research_universe_flow.py`

**Interfaces:**

```python
class ResearchUniverseState(DomainRecord):
    as_of: datetime
    listing_prefilter_symbols: tuple[str, ...]
    research_symbols: tuple[str, ...]
    excluded: tuple[UniverseExclusion, ...]


def compute_research_universe(
    *,
    csv_root: Path,
    as_of: datetime,
    universe_config: UniverseConfig,
    factor_configs: Sequence[FactorConfig],
) -> ResearchUniverseState:
    ...
```

- [ ] Fixture must cover ST, recent IPO, invalid market data, low liquidity, and mature/liquid symbols.
- [ ] Required flow:

```text
securities
→ listing prefilter
→ bootstrap bars
→ compute only avg_amount_20d (or the liquidity factor referenced by Universe config)
→ UniverseBuilder
→ research_symbols
```

- [ ] Do not compute all 24 factors just to decide Research Universe membership.
- [ ] Add read-only CLI `astock universe research --as-of YYYY-MM-DD`.
- [ ] Output listing count, prefilter count, Research Universe count, exclusions by rule, and the message: `target size is observational (approximately 2,000–3,000), not a quota`.
- [ ] A result of 1,850 or 3,200 must not auto-change thresholds.
- [ ] Assert the command changes no Snapshot/Watchlist/Job state.
- [ ] Commit:

```bash
git add src/astock_lens/pipelines/analysis.py src/astock_lens/pipelines/stages.py src/astock_lens/cli/app.py tests/integration/test_research_universe_flow.py
git commit -m "宇宙：在昂贵数据补全前生成研究股票池"
git push
```

---

# Task 6: Enrich Only Research-Universe Symbols

**Files:**
- Modify: `src/astock_lens/data/bootstrap.py`
- Modify: `src/astock_lens/data/sync.py`
- Modify: `src/astock_lens/cli/app.py`
- Modify: `tests/integration/test_research_universe_flow.py`

**Interfaces:**

```python
class EnrichmentRequirement(DomainRecord):
    required_price_bars: int
    symbols: tuple[str, ...]


def strategy_history_requirement(
    factor_configs: Sequence[FactorConfig],
) -> int:
    ...
```

- [ ] Derive the longest required price-history window from active factor configs; do not hard-code 252.
- [ ] Add `astock sync-research --as-of YYYY-MM-DD`.
- [ ] The command must:
  1. compute/read Research Universe;
  2. ensure only those symbols have strategy-required price history;
  3. use resumable chunking;
  4. optionally refresh WeStock statements only for Research Universe symbols.
- [ ] Do not issue ~2,500 single-symbol neodata valuation calls in this task. Report `valuation enrichment: BLOCKED_PENDING_INDUSTRY_PATH` until Task 7 establishes a measured sector/industry path.
- [ ] Fixture proof: 100 broad symbols / 40 Research symbols causes expensive enrichment requests only for the 40.
- [ ] Commit:

```bash
git add src/astock_lens/data/bootstrap.py src/astock_lens/data/sync.py src/astock_lens/cli/app.py tests/unit/test_bootstrap_sync.py tests/integration/test_research_universe_flow.py
git commit -m "数据：只为研究股票池补齐策略所需重数据"
git push
```

---

# Task 7: Build the Canonical Industry-Membership Pipeline

**Files:**
- Create: `src/astock_lens/data/industry.py`
- Create: `src/astock_lens/data/normalize/industry.py`
- Create: `tests/unit/test_industry_membership.py`
- Modify: `src/astock_lens/data/providers/neodata.py`
- Modify: `src/astock_lens/data/sync.py`
- Modify: `src/astock_lens/cli/app.py`
- Modify: `docs/REVIEW_NOTES.md`

**Interfaces:**

```python
class IndustryMembership(DomainRecord):
    symbol: str
    industry_id: str
    industry_name: str
    as_of: datetime
    provider: str
    source_ref: str | None = None


def build_industry_map(
    memberships: Sequence[IndustryMembership],
    *,
    as_of: datetime,
) -> dict[str, str]:
    ...
```

## Task 7A — Sector Catalog Source Probe

- [ ] Run and record:

```bash
tools/bin/westock --help
tools/bin/westock sector --help
tools/bin/westock sector ranking --help
rg -n "sector|industry|板块|行业" src docs tests
```

If exact WeStock subcommands differ, use `--help` discovery only.

- [ ] Source acceptance order:
  1. existing provider/CLI with stable enumerable sector/industry IDs/names;
  2. another tested source already in this repo;
  3. otherwise STOP with `BLOCKED: no authoritative enumerable industry catalog source`.

**Never create a handwritten sector list.**

### STOP GATE 7A

If no authoritative enumerable catalog is demonstrated, commit the evidence, leave final calibration industry-blocked, and continue later tasks with fixture/external `--industry-map` only.

## Task 7B — Normalize neodata Industry Membership

Only if 7A succeeds.

- [ ] Record representative raw neodata industry responses as test fixtures.
- [ ] RED tests must prove canonical symbol parsing, industry id/name preservation, deterministic dedupe, and explicit failures for unparseable symbols.
- [ ] Normalize `data/raw/neodata/industry/YYYY-MM-DD.csv` into `IndustryMembership` records.
- [ ] Orchestrate catalog → neodata industry requests → raw landing with source evidence.
- [ ] If one symbol belongs to multiple thematic boards and the source exposes no explicit primary-industry semantics, STOP with `BLOCKED_PRIMARY_INDUSTRY_SEMANTICS`.
- [ ] Do not choose “first board wins”.
- [ ] When primary semantics are valid, add:

```text
astock sync-industry --as-of YYYY-MM-DD
astock industry export-map --as-of YYYY-MM-DD --output PATH
```

- [ ] `export-map` writes exactly `symbol,industry` CSV.
- [ ] Run:

```bash
uv run pytest tests/unit/test_industry_membership.py -v
uv run ruff check src/astock_lens/data tests/unit/test_industry_membership.py
uv run mypy src/astock_lens/data
```

- [ ] Commit:

```bash
git add src/astock_lens/data src/astock_lens/cli/app.py tests/unit/test_industry_membership.py docs/REVIEW_NOTES.md
git commit -m "行业：建立可审计的行业成员映射链路"
git push
```

---

# Task 8: Upgrade Calibration Report to Decision-Grade Evidence

**Files:**
- Create: `src/astock_lens/calibration/factor_distribution.py`
- Create: `tests/unit/test_calibration_factor_distribution.py`
- Modify: `src/astock_lens/calibration/candidate_report.py`
- Modify: `src/astock_lens/calibration/render.py`
- Modify: `tests/unit/test_candidate_calibration.py`

**Interfaces:**

```python
class FactorDistribution(DomainRecord):
    factor: str
    value_count: int
    null_count: int
    stale_count: int
    source_error_count: int
    quantiles: tuple[tuple[str, float], ...]
    min_value: float | None
    max_value: float | None


class BoundarySample(DomainRecord):
    symbol: str
    strategy_id: str
    score: float | None
    rank_percentile: float
    factor_values: tuple[tuple[str, float | None, str], ...]
```

- [ ] Add factor quantiles: `p10 p25 p50 p75 p90 p95`, computed only from VALUE + non-None values.
- [ ] Count NULL/STALE/SOURCE_ERROR separately.
- [ ] For each strategy include top 5, five immediately above 0.90, five immediately below, and relevant anomaly samples.
- [ ] Every sample must include strategy score, rank percentile, actual used factor values, and factor statuses.
- [ ] Derive strategy→factor membership from existing scanner/config/contribution contracts; do not maintain a second handwritten map if the relationship already exists.
- [ ] Replace misleading “Top 10% Boundary” with distinct `boundary_rank_percentile` and `boundary_strategy_score` fields.
- [ ] Add calibration population metadata: broad listing count, prefilter count, Research Universe count, ratio, exact Universe config values, factor/strategy versions.
- [ ] Final decision-grade report must fail if required canonical industry coverage is unavailable; fixture mode may still use explicit `--industry-map`.
- [ ] Deterministic rendering must remain byte-stable under shuffled inputs.
- [ ] Run:

```bash
uv run pytest tests/unit/test_calibration_factor_distribution.py tests/unit/test_candidate_calibration.py -v
```

- [ ] Commit:

```bash
git add src/astock_lens/calibration tests/unit/test_calibration_factor_distribution.py tests/unit/test_candidate_calibration.py
git commit -m "校准：补齐绝对门槛决策所需因子与边界证据"
git push
```

---

# Task 9: Align Calibration CLI With the Research Universe

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Modify: `tests/integration/test_candidate_calibration_cli.py`
- Create: `tests/integration/test_calibration_readiness_cli.py`
- Modify: `src/astock_lens/pipelines/analysis.py` if a restricted canonical analysis entry point is needed.

- [ ] RED test: broad listing 100 / Research Universe 40; calibration StrategyResults must contain no excluded broad symbol.
- [ ] Required flow:

```text
broad listing
→ Research Universe
→ full factors for Research Universe
→ six scanners on Research Universe
→ calibration report
```

- [ ] If `_preview_state()` analyzes the broad market before restriction, add a canonical `run_research_analysis(..., research_symbols=...)` entry point. Do not copy algorithms.
- [ ] Preserve read-only calibration guarantees for Snapshot/Watchlist/Job roots.
- [ ] If Task 7 succeeds, `astock calibrate candidates --as-of ... --output-dir ...` should auto-load canonical industry mapping. Keep `--industry-map` only as explicit override/testing escape hatch.
- [ ] If Task 7 is blocked, keep `--industry-map` required and clearly label the report as externally mapped evidence.
- [ ] Run:

```bash
uv run pytest tests/integration/test_candidate_calibration_cli.py tests/integration/test_calibration_readiness_cli.py -v
```

- [ ] Commit:

```bash
git add src/astock_lens/cli/app.py src/astock_lens/pipelines/analysis.py tests/integration/test_candidate_calibration_cli.py tests/integration/test_calibration_readiness_cli.py
git commit -m "校准：统一研究股票池与正式策略分析总体"
git push
```

---

# Task 10: Scale Ladder — 100 → 500 → Full Research Universe

**Files:**
- Modify: `docs/REVIEW_NOTES.md`
- Modify: `.workbuddy/memory/2026-09-18.md`
- Runtime only: `var/benchmarks/calibration-readiness-2026-09-18.json`

**No code changes should start in this task unless a measured failure proves a concrete bug.**

Record for 100, 500, and full Research Universe:

```text
listing_count
research_count
bootstrap_sync_seconds
bootstrap_failed_symbols
price_enrichment_seconds
financial_enrichment_seconds
normalization_seconds
normalization_peak_rss_mb
factor_seconds
strategy_seconds
calibration_seconds
factor_value_count
factor_null_count
factor_not_applicable_count
factor_source_error_count
industry_coverage_ratio
```

- [ ] Run `uv run astock doctor`. If required provider health fails, report and stop affected live measurement; never fabricate timing.
- [ ] Run deterministic 100-symbol benchmark.
- [ ] Run deterministic 500-symbol benchmark.
- [ ] Before full Research Universe, inspect time/RSS scaling. If clearly super-linear or unsafe, STOP and return evidence instead of blindly launching full scale.
- [ ] Run the actual Research Universe; do not force size to 2,500.
- [ ] Generate decision-grade calibration reports only when strategy analysis, required industry mapping, and coverage reporting are complete.
- [ ] Save runtime reports under e.g.:

```text
var/calibration/<date>-candidate-calibration.md
var/calibration/<date>-candidate-calibration.json
```

- [ ] Record actual metrics in REVIEW_NOTES and memory.
- [ ] Commit docs only:

```bash
git add docs/REVIEW_NOTES.md .workbuddy/memory/2026-09-18.md
git commit -m "验证：记录研究股票池全规模校准实测"
git push
```

---

# Task 11: Final Verification and Owner Decision Packet

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REVIEW_NOTES.md`

- [ ] Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

All must exit 0 before claiming completion.

- [ ] Verify Candidate remains BLOCKED:

```bash
uv run astock daily --as-of <latest-landed-trade-date> --allow-incomplete
```

Expected: absolute qualification rules and Market/Validation/Signal still prevent production Candidate publication.

- [ ] Search for forbidden accidental product rules:

```bash
find configs -maxdepth 2 -type f -path '*/qualifications/*' -print
rg -n "global_score|combined_strategy_score|cross_strategy_score" src tests configs
```

Expected: no production qualification YAML; no cross-strategy global score.

- [ ] Update ROADMAP next owner decision to:

```text
Review the Research-Universe Calibration Report and approve, per strategy:
- Value absolute quality rule
- Growth absolute quality rule
- GARP absolute quality rule
- Quality absolute quality rule
- Dividend absolute quality rule
- Momentum absolute quality rule

Still explicit owner decisions:
- Growth extreme-value treatment
- Dividend payout shape
- PEG source/value-domain treatment
```

- [ ] Commit:

```bash
git add docs/ROADMAP.md docs/REVIEW_NOTES.md
git commit -m "审计：完成全市场校准就绪阶段"
git push
```

---

# Mandatory STOP GATE

After Task 11, **STOP**.

The Agent is not authorized to:
- choose any absolute Candidate Qualification threshold;
- create production `configs/qualifications/*.yaml`;
- activate production Candidate publishing;
- invent Growth winsorization values;
- choose Dividend payout caps/bands;
- decide PEG interpretation;
- decide Market Regime / Validation / Signal thresholds;
- force Research Universe to exactly 2,500 symbols.

Return calibration evidence to the owner for explicit decisions.

---

# Agent Completion Report — Required Format

```text
1. Task 1–11 commit SHAs
2. Remote main HEAD
3. Research Universe rules actually applied
4. Broad listing count
5. Listing-prefilter count
6. Final Research Universe count
7. Confirmation that 2,500 was NOT used as a hard quota
8. Bootstrap-history requirement and which config produced it
9. Strategy full-history requirement and which config produced it
10. 100-symbol benchmark metrics
11. 500-symbol benchmark metrics
12. Full Research-Universe benchmark metrics
13. Peak RSS at full scale
14. Industry source used
15. Industry coverage ratio
16. If industry pipeline blocked: exact STOP GATE reason and evidence
17. Calibration Markdown path
18. Calibration JSON path
19. Six strategies: evaluable/ranked/Top-10% counts
20. Growth/Dividend/PEG anomaly summaries
21. Full pytest result
22. Full ruff check result
23. Full ruff format --check result
24. Full mypy result
25. Proof Candidate publishing remains BLOCKED
26. Proof no production qualification config was created
27. `git status --short` output proving clean worktree
28. Any plan deviation, exact reason, exact commit
```

---

# Self-Review

## Spec coverage

This plan preserves all Candidate Qualification semantics from the approved 2026-09-17 spec and adds only the approved 2026-09-18 Research Universe semantics. No task assigns any six-strategy absolute threshold.

## Architecture consistency

- Broad listing remains authoritative master data.
- Listing prefilter uses listing metadata only.
- Liquidity membership uses the existing `avg_amount_20d` factor and existing Universe threshold.
- Expensive enrichment happens only after Research Universe selection.
- Strategy percentile/calibration denominator is the Research Universe, matching production.
- Candidate publishing remains blocked after this plan.

## Performance-risk coverage

- Task 2 removes repeated full-factor scans in `strategy_stage`.
- Task 4 makes bootstrap sync resumable and failure-isolated.
- Task 6 avoids expensive enrichment for excluded symbols.
- Task 10 validates scaling in 100 → 500 → Research Universe order instead of jumping straight to ~5,500.

## Data-quality coverage

- Missing values remain missing.
- Industry classification cannot be invented.
- If the source exposes only thematic multi-membership and no primary-industry semantics, the plan explicitly stops.
- Calibration reports expose factor distributions, statuses, boundary samples, and anomaly samples.

## Placeholder scan

No implementation placeholder or unapproved product threshold is present. Explicit STOP GATE states are intentional owner-decision boundaries.
