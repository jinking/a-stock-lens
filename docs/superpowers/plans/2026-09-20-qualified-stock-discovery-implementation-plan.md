# Qualified Stock Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose existing Strategy Qualification results as a fast read-only CLI/API stock-discovery surface without calling them Candidate or recomputing Factor/Strategy.

**Architecture:** Read stored FACTOR + STRATEGY snapshots, strict-load approved qualifiers, evaluate qualification deterministically in the discovery layer, and return only dual-pass results. No Candidate snapshot is written and no Market/Signal evidence is synthesized.

**Tech Stack:** Python >=3.12, Pydantic 2.x, Typer, FastAPI, existing SnapshotStore and qualification rules, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-20-qualified-to-candidate-upgrade-design.md`

## Global Constraints

- Read stored FACTOR and STRATEGY snapshots only.
- Do not recompute Factor or Strategy.
- Do not write Snapshot/Watchlist/Job state.
- `qualified` means `StrategyQualification.qualified == True`.
- `qualified` is not Candidate and not an investment recommendation.
- Do not implement Market Regime / Validation / Signal.
- Do not wire `RepresentativeCandidatePolicy`.
- Invalid qualification config fails loudly.
- TDD: RED → GREEN → review → commit → push.
- Chinese commit messages and docs.

## Review Focus

1. FACTOR exists but STRATEGY does not: explicit error.
2. Requested strategy is absent: explicit not-found.
3. Invalid Qualification config: fail loudly, never pretend qualified count is zero.
4. Dividend currently has zero dual-pass: valid empty answer + warning.
5. Query must not mutate Snapshot/Watchlist/Job roots.

---

## Locked File Structure

### Create

- `src/astock_lens/discovery/qualified.py`
- `tests/unit/test_qualified_discovery.py`
- `tests/integration/test_qualified_cli.py`
- `.github/workflows/ci.yml`

### Modify

- `src/astock_lens/discovery/models.py`
- `src/astock_lens/discovery/__init__.py`
- `src/astock_lens/cli/app.py`
- `src/astock_lens/api/app.py`
- `tests/unit/test_api.py`
- `tests/integration/test_screen_cli.py`
- `README.md`
- `docs/ROADMAP.md`
- `docs/REVIEW_NOTES.md`

### Forbidden

- Candidate policy semantics
- Market/Signal implementation
- production Qualification thresholds
- Candidate Snapshot publication

---

### Task 1: Add Pure Qualified Discovery

**Files:**
- Modify: `src/astock_lens/discovery/models.py`
- Create: `src/astock_lens/discovery/qualified.py`
- Modify: `src/astock_lens/discovery/__init__.py`
- Create: `tests/unit/test_qualified_discovery.py`

**Interfaces:**

```python
class QualifiedScreenQuery(DomainRecord):
    strategy_id: str
    limit: int = 20

class QualifiedCoverage(DomainRecord):
    strategy_id: str
    strategy_eligible_count: int
    ranked_count: int
    percentile_pass_count: int
    absolute_pass_count: int
    qualified_count: int

class QualifiedScreenItem(DomainRecord):
    rank: int
    symbol: str
    strategy_id: str
    strategy_version: str
    qualification_version: str
    score: float | None
    rank_percentile: float
    reasons: tuple[str, ...]
    risks: tuple[str, ...]

class QualifiedScreenResult(DomainRecord):
    strategy_id: str
    coverage: QualifiedCoverage
    items: tuple[QualifiedScreenItem, ...]
    warnings: tuple[str, ...] = ()
```

Service:

```python
def screen_qualified(
    *,
    factor_results: Sequence[FactorResult],
    strategy_results: Sequence[StrategyResult],
    qualifiers: Mapping[str, StrategyQualifier],
    query: QualifiedScreenQuery,
) -> QualifiedScreenResult:
    ...
```

- [ ] **Step 1: Write RED dual-pass test**

AAA = percentile pass + absolute pass; BBB = percentile pass + absolute fail; CCC = absolute pass + percentile fail. Assert only AAA returns.

- [ ] **Step 2: Write RED deterministic order test**

Sort:

```text
rank_percentile DESC
score DESC
symbol ASC
```

- [ ] **Step 3: Write RED coverage-before-limit test**

`limit=1` must not alter full-population coverage counts.

- [ ] **Step 4: Write RED zero-qualified test**

Assert:

```python
assert result.items == ()
assert result.coverage.qualified_count == 0
assert result.warnings
```

- [ ] **Step 5: Implement without pipeline imports**

Build one-pass factor index locally, construct `QualificationContext`, call existing qualifier. Do not import `astock_lens.pipelines`.

- [ ] **Step 6: Verify**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_qualified_discovery.py -v
uv run ruff check src/astock_lens/discovery tests/unit/test_qualified_discovery.py
uv run mypy src/astock_lens/discovery
```

- [ ] **Step 7: Commit**

```bash
git add src/astock_lens/discovery tests/unit/test_qualified_discovery.py
git commit -m "查询：增加双门槛合格股票发现服务"
git push
```

---

### Task 2: Add `astock qualified`

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Create: `tests/integration/test_qualified_cli.py`
- Modify: `tests/integration/test_screen_cli.py`

**Interface:**

```bash
astock qualified STRATEGY --as-of YYYY-MM-DD [--top N]
```

- [ ] **Step 1: RED happy path**

Seed FACTOR + STRATEGY snapshots and temp qualification configs. Assert only dual-pass rows display.

- [ ] **Step 2: RED missing FACTOR**

Expected non-zero:

```text
no FACTOR snapshot for YYYY-MM-DD
```

- [ ] **Step 3: RED missing STRATEGY**

Expected non-zero:

```text
no STRATEGY snapshot for YYYY-MM-DD
```

- [ ] **Step 4: RED invalid config**

Malformed `ASTOCK_QUALIFICATION_DIR` must raise `QualificationConfigInvalid`; do not print a normal zero-result screen.

- [ ] **Step 5: RED Dividend zero result**

Exit 0, `qualified: 0`, explicit warning.

- [ ] **Step 6: Implement stored-snapshot flow**

```python
factors = _snapshot_records(SnapshotKind.FACTOR, day, FactorResult)
strategies = _snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)
factor_names = frozenset(c.name for c in _factor_configs())
qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
result = screen_qualified(...)
```

No Provider / `_preview_state` / factor-stage / strategy-stage call.

- [ ] **Step 7: Fix stale copy**

Change `screen --top` help from “candidates” to “strategy results”.

Change missing Candidate copy in `astock stock` to:

```text
candidate: not published for this date
```

Do not claim Qualification is unapproved.

- [ ] **Step 8: Prove read-only**

Hash Snapshot/Watchlist/Job roots before and after command; assert identical.

- [ ] **Step 9: Commit**

```bash
git add src/astock_lens/cli/app.py         tests/integration/test_qualified_cli.py         tests/integration/test_screen_cli.py
git commit -m "命令：开放只读双门槛合格股票查询"
git push
```

---

### Task 3: Add Qualification Results API

**Files:**
- Modify: `src/astock_lens/api/app.py`
- Modify: `tests/unit/test_api.py`

**Interface:**

```http
GET /qualifications/{strategy_id}/results?as_of=YYYY-MM-DD&limit=20
```

- [ ] **Step 1: RED results test** — dual-pass only.
- [ ] **Step 2: RED validation** — 422 for `limit <= 0` or `limit > 500`.
- [ ] **Step 3: RED unknown strategy** — 404.
- [ ] **Step 4: RED invalid config** — fail loudly, not empty 200.
- [ ] **Step 5: Implement using discovery + qualification modules only.**
- [ ] **Step 6: Add source-boundary test**

Forbidden imports in API:

```text
astock_lens.pipelines
run_analysis
factor_stage
strategy_stage
```

- [ ] **Step 7: Commit**

```bash
git add src/astock_lens/api/app.py tests/unit/test_api.py
git commit -m "接口：开放策略双门槛合格股票查询"
git push
```

---

### Task 4: Real 2026-09-19 Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REVIEW_NOTES.md`

- [ ] **Step 1: Run five usable strategies**

Expected accepted dual-pass counts:

```text
Value 132
Growth 151
GARP 61
Quality 111
Momentum 166
```

If actual counts differ, STOP and diagnose. Do not change thresholds.

- [ ] **Step 2: Run Dividend**

Expected current result: zero qualified with explicit data-health warning.

- [ ] **Step 3: API smoke**

Test growth/value/dividend qualification routes.

- [ ] **Step 4: Document semantics**

```text
screen = ranking
qualified = dual gate
candidate = later market/signal validated research candidate
```

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ROADMAP.md docs/REVIEW_NOTES.md
git commit -m "验收：双门槛合格股票查询进入日常使用"
git push
```

---

### Task 5: Add Minimal GitHub CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create CI using repository Python version + uv**

Run:

```bash
PYTHONPATH= uv run --no-sync pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

- [ ] **Step 2: Keep real-provider tests mocked or excluded by existing conventions**

No secrets committed.

- [ ] **Step 3: Push and inspect Actions**

Expected all jobs green on the commit.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "工程：增加核心测试与静态检查CI"
git push
```

---

## Mandatory STOP Gate

After Task 5 STOP.

Do not publish Candidate, implement Market/Signal, alter Dividend rules, derive TTM yield, or create a cross-strategy score.

## Required Agent Completion Report

```text
1. Task commit SHAs
2. remote main HEAD
3. pytest result
4. ruff / format / mypy
5. GitHub Actions status
6. Value qualified count
7. Growth qualified count
8. GARP qualified count
9. Quality qualified count
10. Momentum qualified count
11. Dividend qualified count
12. proof qualified query is read-only
13. proof API imports no pipeline compute layer
14. proof no CANDIDATE snapshot exists
15. git status --short
```
