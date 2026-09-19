# Stock Discovery MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the already-computed full Research-Universe strategy results into a fast, read-only stock discovery surface through CLI and API, without bypassing the still-blocked Candidate Qualification / Market Validation / Signal gates.

**Architecture:** Add a pure `discovery` query layer over stored `StrategyResult` records. `astock screen` and new FastAPI strategy/stock-profile routes consume formal snapshots only; existing `astock strategy run` / `astock scan` remain recomputation previews. No cross-strategy score or synthetic Candidate is introduced.

**Tech Stack:** Python >=3.12, Pydantic 2.x, Typer, FastAPI, existing SnapshotStore resolver, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-19-stock-discovery-mvp-design.md`

## Global Constraints

- Strategy Screener is a research ranking, not an investment recommendation.
- Candidate remains a separate domain object and stays BLOCKED until existing product gates are approved.
- Never create a cross-strategy global score.
- Never synthesize MarketValidation or Signal values.
- CLI/API query paths must not call Providers or recompute factors/strategies.
- Formal Snapshot writes remain owned by `astock daily`.
- `astock screen` reads stored `STRATEGY` snapshots and writes nothing.
- Default `--top 20` is presentation pagination only, not a Candidate/product threshold.
- Missing Strategy snapshot must be explicit; never silently recompute.
- Existing `astock strategy run` and `astock scan` behavior remains unchanged.
- Commit messages and project documentation remain Chinese.
- TDD for every behavioral task: RED → minimal implementation → GREEN → commit → push.

## Review Focus

1. Strategy snapshot exists but requested strategy id does not: return an explicit not-found result, never rows from another strategy.
2. Rows have `score=None` or `rank_percentile=None`: preserve `None`, sort behind ranked/scored rows, never coerce missing values into real measurements.
3. Candidate snapshot is absent: Stock Profile must still return Universe/Factor/Strategy with `candidate_status=not_published`.
4. Value/GARP partial coverage: CLI/API must expose denominator/scored counts.
5. API import boundary: no pipeline/scanner/factor computation imports.

---

## Locked File Structure

### Create

- `src/astock_lens/discovery/__init__.py`
- `src/astock_lens/discovery/models.py`
- `src/astock_lens/discovery/service.py`
- `tests/unit/test_discovery_service.py`
- `tests/integration/test_screen_cli.py`
- `tests/integration/test_stock_discovery_workflow.py`
- `docs/superpowers/specs/2026-09-19-stock-discovery-mvp-design.md`
- `docs/superpowers/plans/2026-09-19-stock-discovery-mvp-implementation-plan.md`

### Modify

- `src/astock_lens/cli/app.py`
- `src/astock_lens/api/app.py`
- `tests/unit/test_api.py`
- `README.md`
- `docs/ROADMAP.md`
- `docs/REVIEW_NOTES.md`
- `.workbuddy/memory/2026-09-19.md`

### Do Not Modify for Product Semantics

- `src/astock_lens/candidates/policy.py`
- `src/astock_lens/qualifications/**`
- `configs/qualifications/**`
- Candidate absolute thresholds
- Market Regime / Market Validation / Signal rules
- strategy weights

---

## Task 1: Land the Spec and Correct Current-State Drift

**Files:**
- Create: `docs/superpowers/specs/2026-09-19-stock-discovery-mvp-design.md`
- Create: `docs/superpowers/plans/2026-09-19-stock-discovery-mvp-implementation-plan.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REVIEW_NOTES.md`
- Modify: `.workbuddy/memory/2026-09-19.md`

**Interfaces:** No runtime change.

- [ ] **Step 1: Record actual repository baseline**

Run:

```bash
git rev-parse HEAD
git status --short
uv run --no-sync pytest tests/unit tests/contract tests/integration tests/artifacts -q
```

Record actual values in `docs/REVIEW_NOTES.md`. Do not reuse stale counts.

- [ ] **Step 2: Confirm committed research baseline**

Verify committed evidence for:

```text
Research Universe = 2,303
FactorResult = 55,272
StrategyResult = 13,818
```

If local acceptance artifacts exist, verify them. If not, explicitly label the numbers as committed baseline evidence rather than a fresh run.

- [ ] **Step 3: Fix ROADMAP drift**

Remove or replace statements that:
- only five stocks can be strategy-scored;
- strategy-length history is still the active blocker if current evidence disproves it;
- Industry Trend has no landed industry membership.

Replace Industry Trend blocker with:

```text
行业 membership 已可用；缺口是行业聚合指标、Industry Trend 打分口径及对应实现仍未批准/完成。
```

Keep Value/GARP valuation coverage limitation explicit.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-09-19-stock-discovery-mvp-design.md         docs/superpowers/plans/2026-09-19-stock-discovery-mvp-implementation-plan.md         docs/ROADMAP.md docs/REVIEW_NOTES.md .workbuddy/memory/2026-09-19.md
git commit -m "文档：锁定股票发现MVP与当前真实基线"
git push
```

---

## Task 2: Build the Pure Strategy Discovery Query Layer

**Files:**
- Create: `src/astock_lens/discovery/__init__.py`
- Create: `src/astock_lens/discovery/models.py`
- Create: `src/astock_lens/discovery/service.py`
- Create: `tests/unit/test_discovery_service.py`

**Interfaces:**

```python
class StrategyScreenQuery(DomainRecord):
    strategy_id: str
    limit: int = 20
    eligible_only: bool = True
    min_percentile: float | None = None

class StrategyScreenItem(DomainRecord):
    rank: int
    symbol: str
    strategy_id: str
    strategy_version: str
    score: float | None
    rank_percentile: float | None
    confidence: float | None
    eligible: bool
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()

class StrategyCoverage(DomainRecord):
    strategy_id: str
    total_count: int
    eligible_count: int
    scored_count: int
    ranked_count: int

class StrategyScreenResult(DomainRecord):
    strategy_id: str
    coverage: StrategyCoverage
    items: tuple[StrategyScreenItem, ...]

def screen_strategy(
    results: Sequence[StrategyResult],
    query: StrategyScreenQuery,
) -> StrategyScreenResult:
    ...

def summarize_strategies(
    results: Sequence[StrategyResult],
) -> tuple[StrategyCoverage, ...]:
    ...
```

- [ ] **Step 1: Write RED ranking test**

```python
def test_screen_strategy_orders_ranked_results_best_first() -> None:
    result = screen_strategy(
        (
            strategy_result("BBB", percentile=0.91, score=70),
            strategy_result("AAA", percentile=0.99, score=60),
            strategy_result("CCC", percentile=0.95, score=80),
        ),
        StrategyScreenQuery(strategy_id="growth", limit=20),
    )
    assert [item.symbol for item in result.items] == ["AAA", "CCC", "BBB"]
```

- [ ] **Step 2: Add RED tests for missing values**

Pin this order:

```text
ranked/scored rows
→ unranked scored rows
→ unranked/unscored rows
```

Returned values must remain `None`.

- [ ] **Step 3: Add RED tests for filters**

Cover:
- `eligible_only=True`;
- `eligible_only=False`;
- `min_percentile=0.95`;
- `limit=2`;
- `limit <= 0` rejected;
- percentile outside `[0,1]` rejected.

- [ ] **Step 4: Add RED coverage tests**

Coverage is calculated before `limit`.

Assert:

```text
total_count
eligible_count
scored_count
ranked_count
```

- [ ] **Step 5: Implement**

Use deterministic key:

```python
def _screen_sort_key(result: StrategyResult) -> tuple[int, float, int, float, str]:
    return (
        result.rank_percentile is None,
        -(result.rank_percentile or 0.0),
        result.score is None,
        -(result.score or 0.0),
        result.symbol,
    )
```

The zeroes only participate after the `is None` discriminator; they are never returned as measurements.

- [ ] **Step 6: Verify**

```bash
uv run --no-sync pytest tests/unit/test_discovery_service.py -v
uv run ruff check src/astock_lens/discovery tests/unit/test_discovery_service.py
uv run mypy src/astock_lens/discovery
```

- [ ] **Step 7: Commit**

```bash
git add src/astock_lens/discovery tests/unit/test_discovery_service.py
git commit -m "查询：建立独立策略股票发现服务"
git push
```

---

## Task 3: Add the Stored-Snapshot CLI Screener

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Create: `tests/integration/test_screen_cli.py`

**Interfaces:**

```bash
astock screen STRATEGY --as-of YYYY-MM-DD     [--top N]     [--min-percentile FLOAT]     [--all-results]
```

Semantics:
- `--top` default 20;
- default eligible-only;
- `--all-results` sets `eligible_only=False`;
- read `SnapshotKind.STRATEGY`;
- no Provider access;
- no factor/scanner recomputation;
- no Snapshot write.

- [ ] **Step 1: RED test with mixed strategy snapshot**

Seed one STRATEGY snapshot containing Growth + Momentum.

Run:

```bash
astock screen growth --as-of 2026-09-17 --top 2
```

Assert only Growth rows and exactly two items.

- [ ] **Step 2: RED missing-snapshot test**

Expected stderr:

```text
no STRATEGY snapshot for 2026-09-17
run `astock daily --as-of 2026-09-17 --allow-incomplete` first
```

Exit non-zero.

- [ ] **Step 3: RED unknown-strategy test**

When the snapshot exists but contains no requested strategy:

```text
strategy 'foo' has no stored results for 2026-09-17
```

- [ ] **Step 4: Implement using stored snapshot only**

Flow:

```python
records = _snapshot_records(SnapshotKind.STRATEGY, day, StrategyResult)
screened = screen_strategy(
    records,
    StrategyScreenQuery(
        strategy_id=strategy,
        limit=top,
        eligible_only=not all_results,
        min_percentile=min_percentile,
    ),
)
```

Do not call `_analysis`, `_preview_state`, `normalize_stage`, `factor_stage`, or `strategy_stage`.

- [ ] **Step 5: Print coverage**

Example:

```text
growth — 2026-09-17
coverage: total=2303 eligible=2302 scored=2302 ranked=2302
showing: 20
  1  600000.SH  score=...  percentile=...
```

If `scored_count / total_count < 0.90`, print:

```text
coverage warning: only X/Y stored results have a score; ranking reflects available data
```

Define:

```python
LOW_COVERAGE_WARNING_RATIO = 0.90
```

This is UI diagnostics only and has zero selection effect.

- [ ] **Step 6: Prove read-only ownership**

Hash/sentinel Snapshot, Watchlist, Job roots before and after `screen`; assert unchanged.

- [ ] **Step 7: Verify**

```bash
uv run --no-sync pytest tests/integration/test_screen_cli.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/astock_lens/cli/app.py tests/integration/test_screen_cli.py
git commit -m "命令：增加只读策略选股榜单"
git push
```

---

## Task 4: Add Strategy Discovery API Endpoints

**Files:**
- Modify: `src/astock_lens/api/app.py`
- Modify: `tests/unit/test_api.py`

**Interfaces:**

```http
GET /strategies?as_of=YYYY-MM-DD
GET /strategies/{strategy_id}/results?as_of=YYYY-MM-DD&limit=20&eligible_only=true&min_percentile=0.95
```

- [ ] **Step 1: Extend API seed fixture**

Add a STRATEGY snapshot with:
- at least two strategies;
- ranked rows;
- one unranked/unscored row.

- [ ] **Step 2: RED `/strategies` test**

Assert summaries are grouped correctly and sorted by strategy id.

- [ ] **Step 3: RED results endpoint test**

Assert:
- `limit`;
- `eligible_only`;
- `min_percentile`;
- deterministic order.

- [ ] **Step 4: RED invalid query tests**

422 for:
- `limit <= 0`;
- `limit > 500`;
- percentile < 0;
- percentile > 1.

The 500 limit is an API payload guard only.

- [ ] **Step 5: RED unknown-strategy test**

If STRATEGY snapshot exists but id does not:

```http
404
```

with:

```text
strategy 'foo' has no stored results for YYYY-MM-DD
```

- [ ] **Step 6: Implement via discovery service only**

Allowed imports:

```python
from astock_lens.discovery...
from astock_lens.strategies.contracts import StrategyResult
```

Do not import scanner implementations/pipelines.

- [ ] **Step 7: Strengthen API boundary test**

Reject source imports/references:

```text
astock_lens.pipelines
build_scanner
strategy_stage
factor_stage
run_analysis
```

- [ ] **Step 8: Verify**

```bash
uv run --no-sync pytest tests/unit/test_api.py -v
```

- [ ] **Step 9: Commit**

```bash
git add src/astock_lens/api/app.py tests/unit/test_api.py
git commit -m "接口：开放策略榜单与覆盖率查询"
git push
```

---

## Task 5: Add a Real Stock Profile API

**Files:**
- Modify: `src/astock_lens/api/app.py`
- Modify: `tests/unit/test_api.py`

**Interfaces:**

```http
GET /stocks/{symbol}?as_of=YYYY-MM-DD
```

Response:

```json
{
  "as_of": "2026-09-17",
  "symbol": "600519.SH",
  "universe": {
    "included": true,
    "exclusion_rules": []
  },
  "factors": [],
  "strategies": [],
  "candidate_status": "published | not_published | not_selected",
  "candidate": null,
  "watchlist": null
}
```

Definitions:

```text
published     = Candidate snapshot exists and contains symbol
not_selected  = Candidate snapshot exists but excludes symbol
not_published = no Candidate snapshot exists for that date
```

- [ ] **Step 1: RED no-Candidate test**

Seed Universe + Factor + Strategy, no Candidate.

Assert 200:

```json
"candidate_status": "not_published",
"candidate": null
```

- [ ] **Step 2: RED Candidate-not-selected test**

Seed Candidate snapshot containing another symbol; expect `not_selected`.

- [ ] **Step 3: RED Candidate-published test**

Seed Candidate containing requested symbol; expect `published`.

- [ ] **Step 4: RED excluded-Universe test**

Return recorded exclusion rules.

- [ ] **Step 5: RED watchlist test**

Existing entry is returned; no entry returns `null`.

- [ ] **Step 6: Implement optional snapshot read**

Add:

```python
def _read_optional(...) -> tuple[dict[str, object], ...]:
    ...
```

Missing optional Candidate snapshot returns `()` only for this aggregation path. Do not weaken `_read()` used by existing strict routes.

- [ ] **Step 7: Deterministic ordering**

- factors by `factor`;
- strategies by `strategy_id`.

- [ ] **Step 8: Verify**

```bash
uv run --no-sync pytest tests/unit/test_api.py -v
```

- [ ] **Step 9: Commit**

```bash
git add src/astock_lens/api/app.py tests/unit/test_api.py
git commit -m "接口：补齐单股研究画像查询"
git push
```

---

## Task 6: Make Daily-to-Screener Workflow an Integration Contract

**Files:**
- Create: `tests/integration/test_stock_discovery_workflow.py`
- Modify: `README.md`

**Interfaces:** Existing daily pipeline → formal STRATEGY snapshot → screen/API.

- [ ] **Step 1: Write integration test**

Use fixture data to produce:
- Universe snapshot;
- Factor snapshot;
- Strategy snapshot;
- Candidate absent/blocked.

Then query stored Strategy through discovery.

Assert:

```text
strategy rows exist
Candidate snapshot absent
screen path still works
```

- [ ] **Step 2: Add read-after-write consistency**

For one strategy, verify:

```text
stored StrategyResult
→ discovery service
→ API response
```

preserves symbol, score, rank_percentile, strategy_version.

- [ ] **Step 3: Document exact user workflow**

README:

```bash
# 1. Produce formal strategy state. Candidate may still be blocked.
uv run astock daily --as-of 2026-09-17 --allow-incomplete

# 2. Query stored strategy ranking.
uv run astock screen growth --as-of 2026-09-17 --top 20

# 3. Inspect one stock.
uv run astock stock 600519.SH --as-of 2026-09-17
```

Also document API routes.

Explicit wording:

```text
screen = research ranking
candidates = formal research candidate pool, currently blocked
```

- [ ] **Step 4: Verify**

```bash
uv run --no-sync pytest tests/integration/test_stock_discovery_workflow.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_stock_discovery_workflow.py README.md
git commit -m "验证：打通每日策略快照到选股查询链路"
git push
```

---

## Task 7: Run the Real 2,303-Symbol Read-Only Acceptance Check

**Files:**
- Modify: `docs/REVIEW_NOTES.md`
- Modify: `.workbuddy/memory/2026-09-19.md`

**No Provider fetch is allowed in this task.**

- [ ] **Step 1: Confirm formal STRATEGY snapshot**

For accepted baseline date, inspect existing snapshot first.

If absent, run with already-landed data only:

```bash
uv run astock daily --as-of 2026-09-17 --allow-incomplete
```

Do not use `--sync`.

- [ ] **Step 2: Query four well-covered strategies**

```bash
uv run astock screen growth --as-of 2026-09-17 --top 20
uv run astock screen momentum --as-of 2026-09-17 --top 20
uv run astock screen quality --as-of 2026-09-17 --top 20
uv run astock screen dividend --as-of 2026-09-17 --top 20
```

Record:
- total;
- eligible;
- scored;
- ranked;
- returned;
- query wall-clock time.

- [ ] **Step 3: Query Value and GARP**

Same top-20 queries.

Record actual coverage warnings. Do not demand full 2,303 coverage.

- [ ] **Step 4: API smoke**

Query:

```text
/strategies
/strategies/growth/results
/stocks/<one-top-growth-symbol>
```

- [ ] **Step 5: Confirm Candidate boundary**

`/candidates?as_of=...` may 404 if Candidate snapshot is absent. That is correct.

`/stocks/<symbol>` must still return 200 with:

```text
candidate_status=not_published
```

- [ ] **Step 6: Commit evidence only**

```bash
git add docs/REVIEW_NOTES.md .workbuddy/memory/2026-09-19.md
git commit -m "验收：记录两千三百只研究池的选股查询实测"
git push
```

---

## Task 8: Final Verification and Stop Gate

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REVIEW_NOTES.md`

- [ ] **Step 1: Run repository checks**

At minimum:

```bash
make test-fast PYTHONPATH=
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

Then run the documented full test command in the supported environment.

Report environment-sensitive stress failures by exact name; do not hide them.

- [ ] **Step 2: Search forbidden semantic leakage**

```bash
rg -n "global_score|combined_strategy_score|cross_strategy_score" src configs
find configs -maxdepth 2 -type f -path '*/qualifications/*' -print
```

Expected:
- no cross-strategy aggregate score;
- no newly invented qualification production config.

- [ ] **Step 3: Confirm API computation isolation**

```bash
rg -n "astock_lens\.pipelines|build_scanner|strategy_stage|factor_stage|run_analysis"   src/astock_lens/api
```

Expected: no computation-engine imports.

- [ ] **Step 4: Update ROADMAP**

Mark Stock Discovery MVP implemented.

Keep next phases separate:

```text
P1: complete valuation coverage for Value/GARP
P2: review real calibration evidence and approve six absolute qualification rules
P3: implement/approve Market Regime, Market Validation, Signal
P4: wire real Candidate publishing
P5: build Today/Web around formal Candidate
```

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md docs/REVIEW_NOTES.md
git commit -m "审计：完成股票发现MVP并锁定候选阶段后续入口"
git push
```

---

## Mandatory STOP Gate

After Task 8, STOP.

This plan does **not** authorize the Agent to:

- create six absolute Qualification production rules;
- turn Strategy top results into Candidate objects;
- implement a cross-strategy combined ranking;
- synthesize `MarketValidation.NEUTRAL`;
- synthesize `Signal.NO_SIGNAL`;
- call screen results buy recommendations;
- initialize React Web;
- modify strategy weights;
- invent valuation data to fix Value/GARP.

Return the working Stock Discovery surface and evidence first.

---

## Required Agent Completion Report

```text
1. Task 1–8 commit SHAs
2. Remote main HEAD
3. Actual repository test baseline
4. Discovery service tests
5. `astock screen growth --top 20` summary
6. Growth coverage: total / eligible / scored / ranked
7. Momentum coverage
8. Quality coverage
9. Dividend coverage
10. Value coverage
11. GARP coverage
12. Query wall-clock times for all six screens
13. `/strategies` smoke result
14. `/strategies/growth/results` smoke result
15. `/stocks/<symbol>` smoke result
16. Candidate status on Stock Profile
17. Proof API does not import computation engines
18. Proof `screen` mutates no Snapshot/Watchlist/Job state
19. Proof no qualification production config was created
20. Proof no cross-strategy global score was introduced
21. Ruff result
22. Ruff format result
23. mypy result
24. full pytest result / exact environment-sensitive exception
25. `git status --short`
26. Remaining product blockers:
    - valuation coverage
    - six absolute qualification rules
    - Market Regime
    - Market Validation
    - Signal
27. Any plan deviation, exact reason, exact commit
```

Correct completion wording:

```text
Strategy-based Stock Discovery is usable.
Formal Candidate publishing remains blocked by the approved product gates.
```

Do not report “股票推荐已经完成”.

---

## Self-Review

### Spec coverage

- Fast strategy ranking query: Tasks 2–4.
- Single-stock profile query: Task 5.
- Stored-snapshot boundary: Tasks 3–6.
- Coverage transparency: Tasks 2–4 and 7.
- Candidate separation: Tasks 5–8.
- Documentation drift: Tasks 1 and 8.
- Real 2,303-symbol acceptance: Task 7.

### Placeholder scan

No implementation `TODO`, `TBD`, or undefined product thresholds are present.

### Type consistency

`StrategyScreenQuery`, `StrategyCoverage`, `StrategyScreenItem`, and `StrategyScreenResult` are defined in Task 2 and reused unchanged.

### Review Focus coverage

1. Unknown strategy: Task 3 Step 3 / Task 4 Step 5.
2. Missing score/rank: Task 2 Step 2.
3. Missing Candidate snapshot: Task 5 Step 1.
4. Partial Value/GARP coverage: Task 3 Step 5 / Task 7 Step 3.
5. API computation isolation: Task 4 Step 7 / Task 8 Step 3.
