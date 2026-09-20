# Valuation → Qualification Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the newly landed 2026-09-19 valuation data into the canonical Factor/Strategy path, publish a new formal Strategy snapshot without touching historical baselines, and produce decision-grade evidence for owner approval of six absolute Candidate Qualification rules.

**Architecture:** First prove point-in-time visibility and reproduce the new valuation data through the read-only canonical Research Analysis flow. Only after that result is verified may `astock daily --allow-incomplete` publish FACTOR/UNIVERSE/STRATEGY for the same unused `as_of`. Then validate all six Stock Discovery rankings, resolve or explicitly preserve industry gaps, generate a matching Calibration Report and Owner Decision Packet, and stop before any production qualification threshold or Candidate publication.

**Tech Stack:** Python >=3.12, Pydantic 2.x, Typer, existing `CsvNormalizedRepository`, SnapshotStore, Calibration engine, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-20-candidate-readiness-upgrade-design.md`

## Global Constraints

- Preserve the frozen 2026-09-17 research baseline.
- Never let 2026-09-19 valuation Raw leak into an earlier `as_of`.
- Do not run `scripts/migrate_storage.py` in this plan.
- Do not overwrite an existing formal Snapshot with different content.
- Formal Snapshot writes remain owned by `astock daily`.
- `astock screen` remains read-only.
- Do not change strategy weights.
- Do not change Research Universe thresholds.
- Do not invent a Value/GARP minimum coverage target.
- Do not create production qualification threshold files.
- Do not implement or fake Market Regime / Market Validation / Signal.
- Do not publish Candidate.
- TDD for code changes: RED → implementation → GREEN → commit.
- Every task ends with focused verification, commit, and push unless a STOP GATE triggers.
- Documentation and commit messages remain Chinese.

## Review Focus

1. **Point-in-time leakage:** a later valuation Raw file must never affect an earlier analysis date.
2. **Formal-vs-preview drift:** formal STRATEGY Snapshot must semantically equal the verified read-only canonical analysis for the same `as_of`.
3. **Historical snapshot conflict:** existing different-content snapshots must never be overwritten to refresh rankings.
4. **Raw coverage vs strategy coverage:** 97.3% valuation Raw coverage must not be reported as Value/GARP strategy coverage.
5. **Diagnostic vs approval-grade calibration:** incomplete canonical industry evidence must remain visibly diagnostic-only.

---

## Locked File Structure

### Create

- `tests/integration/test_post_valuation_analysis_flow.py`
- `docs/decision-packets/2026-09-20-candidate-qualification-decision-packet.md`
- `docs/superpowers/specs/2026-09-20-candidate-readiness-upgrade-design.md`
- `docs/superpowers/plans/2026-09-20-valuation-to-qualification-readiness-implementation-plan.md`

### Modify

- `tests/unit/test_normalized_repository.py`
- `docs/ROADMAP.md`
- `docs/REVIEW_NOTES.md`
- `docs/REMAINING_PRODUCT_BLOCKERS.md`
- `.workbuddy/memory/2026-09-20.md`

### Modify Only If a Real Bug Is Proven

- `src/astock_lens/data/repository/csv.py`
- `src/astock_lens/pipelines/analysis.py`
- `src/astock_lens/pipelines/daily.py`
- `src/astock_lens/calibration/**`
- `src/astock_lens/cli/app.py`

### Forbidden in This Plan

- `configs/qualifications/**`
- strategy weights
- Candidate policy semantics
- Market/Signal thresholds
- Research Universe thresholds
- `scripts/migrate_storage.py`

---

## Task 1: Baseline Current Main and Pin Point-in-Time Valuation Visibility

**Files:**
- Modify: `tests/unit/test_normalized_repository.py`
- Modify: `docs/REVIEW_NOTES.md`
- Modify/Create: `.workbuddy/memory/2026-09-20.md`

**Interfaces:**
- Consumes: `CsvNormalizedRepository.valuation_inputs(as_of=...)`
- Produces: regression evidence that valuation selection is strictly `file_date <= as_of`.

- [ ] **Step 1: Record the actual repository baseline**

Run:

```bash
git rev-parse HEAD
git status --short
PYTHONPATH= uv run --no-sync pytest -q
uv run ruff check .
uv run mypy
```

Record actual HEAD and test count. Do not reuse an older 959/976 count.

- [ ] **Step 2: Add/strengthen the PIT regression test**

Build a temporary raw tree containing:

```text
neodata/valuation/2026-09-17.csv
neodata/valuation/2026-09-19.csv
```

Use distinguishable values for the same symbol.

Pin:

```python
older = repo.valuation_inputs(as_of=as_of("2026-09-17"))
newer = repo.valuation_inputs(as_of=as_of("2026-09-19"))

assert older.source_file is not None
assert newer.source_file is not None
assert older.source_file.name == "2026-09-17.csv"
assert newer.source_file.name == "2026-09-19.csv"
```

Also assert the same metric has different values in `older` and `newer`, proving the later file was not accidentally consumed by the old date.

- [ ] **Step 3: Run focused tests**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_normalized_repository.py -v
```

If this fails, fix only the real PIT bug in `data/repository/csv.py` / `latest_neodata_file`.

- [ ] **Step 4: Prove frozen Raw is untouched**

```bash
git status --short data/raw/neodata/valuation/2026-09-17.csv
git diff -- data/raw/neodata/valuation/2026-09-17.csv
```

Expected: no change.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_normalized_repository.py         docs/REVIEW_NOTES.md .workbuddy/memory/2026-09-20.md
git commit -m "验证：钉住估值数据的时点可见性边界"
git push
```

---

## Task 2: Capture a New Read-Only Post-Valuation Research Baseline

**Files:**
- Runtime artifact: `var/acceptance/post-valuation-20260919/analysis/`
- Modify: `docs/REVIEW_NOTES.md`

**Interfaces:**
- Consumes current Raw CSV including `data/raw/neodata/valuation/2026-09-19.csv`.
- Produces a read-only canonical Research Analysis baseline.

- [ ] **Step 1: Confirm valuation files**

```bash
test -f data/raw/neodata/valuation/2026-09-19.csv
sha256sum data/raw/neodata/valuation/2026-09-17.csv           data/raw/neodata/valuation/2026-09-19.csv
```

Record the 2026-09-19 block/row count through the repository's existing raw inspection path.

- [ ] **Step 2: Run the existing canonical baseline capture**

Use the existing script, a new output directory, and current industry evidence:

```bash
PYTHONPATH= uv run --no-sync python scripts/capture_research_baseline.py   --csv-root data/raw   --as-of 2026-09-19   --output-dir var/acceptance/post-valuation-20260919/analysis   --config-root configs   --industry-path <canonical/exported-industry-map>
```

If an industry map export is required, obtain it through existing canonical tooling. Do not hand-edit it.

- [ ] **Step 3: Record exact new layer counts**

From the generated artifacts, record:

```text
Research Universe
FactorResult count
StrategyResult count

growth: evaluable / ranked
momentum: evaluable / ranked
quality: evaluable / ranked
dividend: evaluable / ranked
value: evaluable / ranked
garp: evaluable / ranked
```

Do not copy `1,578` / `850` from valuation coverage into strategy counts; those are different layers.

- [ ] **Step 4: Prove valuation factors entered the analysis**

Record DataStatus distribution for:

```text
pe_ttm
pb
ps_ttm
pe_percentile
pcf_operating_ttm
peg
```

If Value/GARP remain near the old 2/1 level, STOP and debug the data path. Do not change strategy rules.

- [ ] **Step 5: Hash the baseline**

Store sha256 for:

```text
research-universe.json
factors.jsonl
strategies.jsonl
calibration.json
calibration.md
```

- [ ] **Step 6: Commit evidence**

```bash
git add docs/REVIEW_NOTES.md
git commit -m "验收：固化估值补齐后的只读研究分析基线"
git push
```

---

## Task 3: Pin Formal Snapshot = Verified Read-Only Analysis

**Files:**
- Create: `tests/integration/test_post_valuation_analysis_flow.py`

**Interfaces:**
- Consumes `run_research_analysis(...)` and `run_daily(...)`.
- Produces an invariant that formal FACTOR/STRATEGY results equal the canonical read-only computation for identical input/as-of.

- [ ] **Step 1: Build the integration fixture**

Fixture must contain:
- sufficient daily bars;
- financial observations;
- two valuation dates;
- complete factor inputs for at least one Value symbol and one GARP symbol.

- [ ] **Step 2: Write the equivalence test**

```python
research, preview = run_research_analysis(
    ...,
    as_of=NEW_AS_OF,
)

formal = run_daily(
    ...,
    as_of=NEW_AS_OF,
    candidate_policy=None,
    qualifiers=None,
)

assert canonicalize(formal.factor_results) == canonicalize(preview.factor_results)
assert canonicalize(formal.strategy_results) == canonicalize(preview.strategy_results)
```

`BUILD_CANDIDATES` being BLOCKED is expected.

- [ ] **Step 3: Prove newer valuation changes only valuation-dependent evidence**

Compare OLD_AS_OF vs NEW_AS_OF.

Assert:
- at least one Value/GARP factor/result changes because valuation evidence changed;
- a Growth-only result remains unchanged when only valuation data differs.

- [ ] **Step 4: Prove Candidate remains absent**

```python
assert formal.candidates == ()
assert JobStage.BUILD_CANDIDATES in formal.blocked_stages
```

- [ ] **Step 5: Run**

```bash
PYTHONPATH= uv run --no-sync pytest   tests/integration/test_post_valuation_analysis_flow.py -v
```

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_post_valuation_analysis_flow.py
git commit -m "测试：钉住最新估值进入正式策略快照的等价链路"
git push
```

---

## Task 4: Publish the New Formal Factor/Strategy Snapshot

**Files:**
- Runtime state: Snapshot / Job stores.
- Modify: `docs/REVIEW_NOTES.md`

**No production code change unless Task 3 proved a defect.**

- [ ] **Step 1: Preflight target date**

Preferred target is `2026-09-19`, matching the valuation Raw date.

Inspect whether FACTOR / UNIVERSE / STRATEGY snapshots already exist for that date.

If existing content differs from Task 2's verified result:

```text
STOP — SNAPSHOT DATE ALREADY OWNS A DIFFERENT TRUTH
```

Do not disable conflict protection and do not silently invent another date.

- [ ] **Step 2: Publish through the only formal writer**

If preflight is clean:

```bash
PYTHONPATH= uv run --no-sync astock daily   --as-of 2026-09-19   --allow-incomplete
```

Do not use `--sync`.

- [ ] **Step 3: Verify stage state**

Expected:

```text
NORMALIZE          SUCCEEDED
COMPUTE_FACTORS    SUCCEEDED
BUILD_UNIVERSE     SUCCEEDED
RUN_STRATEGIES     SUCCEEDED

DETECT_REGIME      BLOCKED
MARKET_VALIDATE    BLOCKED
RUN_SIGNALS        BLOCKED
BUILD_CANDIDATES   BLOCKED
```

- [ ] **Step 4: Compare formal snapshots to Task 2**

Read formal FACTOR and STRATEGY snapshots and compare canonicalized model records against `factors.jsonl` / `strategies.jsonl`.

Expected: semantic equality.

- [ ] **Step 5: Verify Candidate did not appear**

Expected:
- no CANDIDATE snapshot;
- `/candidates?as_of=2026-09-19` returns 404.

- [ ] **Step 6: Commit evidence**

```bash
git add docs/REVIEW_NOTES.md
git commit -m "发布：写入估值补齐后的正式因子与策略快照"
git push
```

---

## Task 5: Accept All Six Stock Discovery Rankings

**Files:**
- Modify: `docs/REVIEW_NOTES.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REMAINING_PRODUCT_BLOCKERS.md`

- [ ] **Step 1: Run all six stored-snapshot screens**

```bash
PYTHONPATH= uv run --no-sync astock screen growth   --as-of 2026-09-19 --top 20
PYTHONPATH= uv run --no-sync astock screen momentum --as-of 2026-09-19 --top 20
PYTHONPATH= uv run --no-sync astock screen quality  --as-of 2026-09-19 --top 20
PYTHONPATH= uv run --no-sync astock screen dividend --as-of 2026-09-19 --top 20
PYTHONPATH= uv run --no-sync astock screen value    --as-of 2026-09-19 --top 20
PYTHONPATH= uv run --no-sync astock screen garp     --as-of 2026-09-19 --top 20
```

Record for each:

```text
total
eligible
scored
ranked
returned
wall-clock query time
```

- [ ] **Step 2: Verify read-only behavior**

Fingerprint Snapshot / Watchlist / Job roots before and after the six queries.

Expected: zero mutations.

- [ ] **Step 3: Inspect one Value and one GARP stock profile**

For one returned symbol from each:

```http
GET /stocks/{symbol}?as_of=2026-09-19
```

Confirm valuation Factor evidence and corresponding Strategy result are visible.

- [ ] **Step 4: Correct P1 product-state docs**

Replace stale wording that valuation coverage is “only a few stocks”.

Document:
- Raw valuation 2,241 / 2,303;
- actual formal Value ranked count;
- actual formal GARP ranked count;
- remaining denominator limitations as data semantics / factor eligibility, not missing whole-market ingestion.

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md docs/REVIEW_NOTES.md docs/REMAINING_PRODUCT_BLOCKERS.md
git commit -m "验收：六策略选股榜切换到最新估值正式快照"
git push
```

---

## Task 6: Close Canonical Industry Gaps or Preserve the Calibration Blocker

**Files:**
- Modify only if a real existing-industry-path bug is proven:
  - `src/astock_lens/data/industry.py`
  - matching industry tests
- Modify: `docs/REVIEW_NOTES.md`

- [ ] **Step 1: Compute the actual current missing set**

Using the Task 2 Research Universe and canonical industry map, record:

```text
known_count
total_count
coverage_ratio
missing_symbols
```

Do not assume the old list of nine symbols.

- [ ] **Step 2: Retry missing symbols using only the existing authoritative source chain**

Rules:
- no handwritten map;
- no company-name inference;
- no arbitrary choice among thematic boards if primary-industry semantics are absent.

- [ ] **Step 3: Recompute coverage**

If missing count becomes zero, canonical industry evidence is approval-grade.

If missing remains non-zero due source limitation, preserve that exact blocker.

- [ ] **Step 4: Add a regression test only if a real code bug was fixed**

The test must reproduce the exact missing-mapping failure.

- [ ] **Step 5: Commit**

Documentation-only case:

```bash
git add docs/REVIEW_NOTES.md
git commit -m "校准：核验并记录最新研究池行业覆盖"
git push
```

If code changed, include implementation + focused tests in the same commit.

---

## Task 7: Generate Updated Candidate Qualification Calibration and Decision Packet

**Files:**
- Runtime:
  - `var/calibration/2026-09-19-candidate-calibration.json`
  - `var/calibration/2026-09-19-candidate-calibration.md`
- Create: `docs/decision-packets/2026-09-20-candidate-qualification-decision-packet.md`

- [ ] **Step 1: Run canonical calibration first**

```bash
PYTHONPATH= uv run --no-sync astock calibrate candidates   --as-of 2026-09-19   --output-dir var/calibration
```

Use the actual CLI syntax if the output option name differs; do not change semantics.

- [ ] **Step 2: Respect the industry gate**

If canonical calibration rejects incomplete industry coverage:

1. keep the rejection;
2. optionally generate an external-map diagnostic report with the supported override;
3. label it:

```text
DIAGNOSTIC ONLY — INDUSTRY COVERAGE INCOMPLETE
```

Do not call the packet approval-grade.

- [ ] **Step 3: Validate population identity**

Calibration must use the same:
- Research Universe count;
- factor versions;
- strategy versions;
- `as_of`;

as Tasks 2–5.

Population drift is a failure.

- [ ] **Step 4: Extract six strategy evidence sections**

For each strategy include:

```text
evaluable count
ranked count
0.90 boundary rank_percentile
boundary strategy score
0.80 / 0.85 / 0.90 / 0.95 sensitivity counts
top samples
boundary-above samples
boundary-below samples
factor distributions
industry concentration
cross-strategy overlap
```

- [ ] **Step 5: Add explicit anomaly sections**

### Growth
- extreme `revenue_yoy`;
- extreme `net_profit_parent_yoy`;
- whether 3-year persistence factors disagree with one-period spikes.

### Dividend
- extreme `dividend_paid_ratio`;
- examples around normal high payout vs extraordinary payout.

### GARP
- PEG raw field count;
- positive/usable PEG factor count;
- negative/non-applicable count;
- observed PEG value scale;
- whether PEG semantic interpretation remains unresolved.

### Value
- actual ranked denominator;
- missing/non-applicable valuation factor patterns.

- [ ] **Step 6: Present 2–3 threshold alternatives per strategy**

Every proposal section begins:

```text
PROPOSAL ONLY — NOT APPROVED PRODUCT RULE
```

For each alternative show projected qualified counts and representative boundary samples.

Do not identify a “best”, “recommended”, or winning option.

- [ ] **Step 7: Prove no production rule files exist**

```bash
find configs -maxdepth 2 -type f -path '*/qualifications/*' -print
```

Expected: no files.

- [ ] **Step 8: Commit the packet**

Only if canonical calibration is approval-grade:

```bash
git add docs/decision-packets/2026-09-20-candidate-qualification-decision-packet.md
git commit -m "决策材料：生成六策略绝对资格门槛校准包"
git push
```

If diagnostic-only, use a filename/title that says `diagnostic` and keep P2 blocked.

---

## Task 8: Final Verification, Documentation, and Owner STOP Gate

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REVIEW_NOTES.md`
- Modify: `.workbuddy/memory/2026-09-20.md`

- [ ] **Step 1: Run repository gates**

```bash
make test-fast PYTHONPATH=
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

Then run the repository's documented full test command in a supported environment.

- [ ] **Step 2: Prove Candidate remains blocked**

Inspect the Task 4 daily run.

Expected blockers remain explicit:
- qualification rules unapproved;
- Market Regime absent;
- Market Validation absent;
- Signal absent.

- [ ] **Step 3: Search for unauthorized changes**

```bash
find configs -maxdepth 2 -type f -path '*/qualifications/*' -print
rg -n "global_score|combined_strategy_score|cross_strategy_score" src configs
```

Also inspect changes under pipelines/candidates to confirm no fake upstream verdict was introduced.

- [ ] **Step 4: Update ROADMAP with the real phase state**

If all gates pass:

```text
Stock Discovery: COMPLETE on latest valuation-aware formal snapshot
P1 valuation backfill/formal recompute: COMPLETE or exact residual source gaps recorded
P2 calibration evidence: READY FOR OWNER DECISION
P3 Market Regime / Validation / Signal: BLOCKED pending owner rules
P4 Candidate Publishing: BLOCKED
P5 Today/Web around Candidate: NOT STARTED
```

If canonical industry coverage is incomplete, P2 remains BLOCKED and the report is diagnostic-only.

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md docs/REVIEW_NOTES.md .workbuddy/memory/2026-09-20.md
git commit -m "审计：完成最新估值到候选资格审批的准备阶段"
git push
```

---

# MANDATORY OWNER STOP GATE

After Task 8, **STOP**.

The Agent is not authorized to:

```text
create configs/qualifications/*.yaml
choose one threshold proposal
enable Candidate publishing
implement Market Regime thresholds
implement Market Validation thresholds
implement Signal thresholds
fabricate NEUTRAL / NO_SIGNAL
create a combined cross-strategy score
call StrategyScreenResult a buy recommendation
```

Return the Decision Packet to the project owner.

The next implementation plan must be written only after the owner explicitly decides:

1. Growth extreme-value treatment;
2. Dividend payout rule shape;
3. PEG treatment;
4. Value absolute quality rule;
5. Growth absolute quality rule;
6. GARP absolute quality rule;
7. Quality absolute quality rule;
8. Dividend absolute quality rule;
9. Momentum absolute quality rule.

Market Regime / Validation / Signal remain a separate design-and-approval plan even after qualification rules are approved.

---

# Post-Gate Upgrade Roadmap — Do Not Execute Yet

After owner approval, split into separate Superpowers plans:

```text
Plan Q — Production Qualification Rules
    approved absolute rules
    config/versioning
    qualifier wiring
    calibration regression

Plan M — Market Regime & Market Validation
    approved inputs/thresholds
    evidence models
    daily pipeline stages

Plan S — Signal Detection
    approved signal definitions
    objective signal evidence

Plan C — Candidate Publishing
    load approved qualifiers
    RepresentativeCandidatePolicy
    real MarketValidation + Signal
    CANDIDATE Snapshot
    astock candidates / API

Plan T — Today & Web
    Today shortlist
    Candidate explanations
    Stock Profile
    Watchlist
    Data Health
```

Do not combine these into one implementation session.

---

# Required Agent Completion Report

```text
1. Task 1–8 commit SHAs
2. Remote main HEAD
3. Full test baseline before work
4. PIT valuation test result
5. 2026-09-17 frozen valuation sha256
6. 2026-09-19 valuation sha256 / block count
7. New Research Universe count
8. New FactorResult count
9. New StrategyResult count
10. Growth total/eligible/scored/ranked
11. Momentum total/eligible/scored/ranked
12. Quality total/eligible/scored/ranked
13. Dividend total/eligible/scored/ranked
14. Value total/eligible/scored/ranked
15. GARP total/eligible/scored/ranked
16. Formal-vs-read-only Strategy equality result
17. Candidate snapshot existence: must be NO
18. Canonical industry coverage ratio
19. Canonical missing industry symbols
20. Calibration approval-grade or diagnostic-only
21. Calibration JSON path
22. Calibration Markdown path
23. Decision Packet path
24. Growth extreme-value evidence summary
25. Dividend payout anomaly summary
26. PEG evidence summary
27. Proof no configs/qualifications files were created
28. Proof no fake MarketValidation/Signal was introduced
29. Proof no cross-strategy global score exists
30. Ruff result
31. Ruff format result
32. mypy result
33. full pytest result
34. git diff --check result
35. git status --short
36. Any STOP GATE triggered
37. Any plan deviation, reason, exact commit
```

Correct completion statement:

```text
Latest valuation-aware Strategy Discovery is formally published.
Candidate Qualification evidence is ready for owner review.
Formal Candidate publishing remains blocked.
```

---

# Self-Review

## Spec Coverage

- New valuation enters canonical analysis: Tasks 1–3.
- Formal Snapshot publication without historical overwrite: Task 4.
- Six-strategy query acceptance: Task 5.
- Canonical industry gate: Task 6.
- Decision-grade calibration and anomaly evidence: Task 7.
- Candidate remains blocked: Tasks 3, 4, 8 and STOP Gate.
- Storage migration explicitly separated: Global Constraints.

## Placeholder Scan

No implementation TODO/TBD placeholders are present. STOP conditions are intentional owner-decision boundaries.

## Type Consistency

The plan uses existing repository interfaces (`CsvNormalizedRepository`, `run_research_analysis`, `run_daily`, `StrategyResult`, Calibration CLI) and introduces no speculative production domain type.

## Review Focus Coverage

1. PIT leakage → Task 1.
2. Formal-vs-preview drift → Tasks 3–4.
3. Snapshot conflict → Task 4.
4. Raw vs strategy coverage → Tasks 2, 5, 7.
5. Diagnostic vs approval-grade calibration → Tasks 6–7.
