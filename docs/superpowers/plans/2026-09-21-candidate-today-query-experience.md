# Candidate & Today Query Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a trusted Candidate snapshot into a simple daily experience: list research candidates, inspect why each was selected, and show a Today summary without recomputing analysis.

**Architecture:** Query stored snapshots only. `candidates` is a detailed Candidate list; `today` is a compact read-only aggregation over Candidate + stored market context. Neither command calls Providers or recomputes Factors/Strategies/Market/Signals.

**Tech Stack:** SnapshotStore, Typer, FastAPI, Pydantic discovery/query models, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md`

## Global Constraints

- Plan B acceptance must be green first.
- Query surfaces are read-only.
- No Provider calls and no recomputation.
- Candidate wording means research candidate, not investment recommendation.
- Existing `/candidates` remains backward-compatible unless explicitly versioned.

## Review Focus

1. Candidate snapshot absent -> explicit not-published state.
2. Candidate snapshot exists but zero rows -> valid empty publication.
3. Multi-strategy candidate -> all qualified strategies visible; primary marked.
4. Risk signal -> visible, not buried.
5. Query invocation leaves Snapshot/Watchlist/Job state unchanged.

---

### Task 1: Pure Candidate Discovery

**Files:**
- Create: `src/astock_lens/discovery/candidates.py`
- Modify: `src/astock_lens/discovery/models.py`
- Create: `tests/unit/test_candidate_discovery.py`

**Interfaces:**

```python
class CandidateScreenItem(DomainRecord):
    rank: int
    symbol: str
    primary_strategy_id: str
    qualified_strategy_ids: tuple[str, ...]
    best_rank_percentile: float
    market_validation: MarketValidation
    signal: Signal
    next_action: NextAction
    reasons: tuple[str, ...]
    risks: tuple[str, ...]

class CandidateScreenResult(DomainRecord):
    as_of: datetime
    total_count: int
    items: tuple[CandidateScreenItem, ...]
```

```python
def screen_candidates(records: Sequence[Candidate], *, limit: int) -> CandidateScreenResult: ...
```

Stored Candidate order is authoritative; do not invent a new ranking.

- [ ] **Step 1:** Preserve stored order.
- [ ] **Step 2:** Show all qualified strategies and primary strategy.
- [ ] **Step 3:** Keep signal/risks visible.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Commit.

```bash
git add src/astock_lens/discovery tests/unit/test_candidate_discovery.py
git commit -m "查询：增加正式候选股票发现服务"
git push
```

---

### Task 2: Add `astock candidates`

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Create: `tests/integration/test_candidates_cli.py`

**CLI:**

```bash
astock candidates --as-of YYYY-MM-DD --top 20
```

Output per row:

```text
rank | symbol | primary strategy | qualified strategies | market validation | signal | next action
```

- [ ] **Step 1:** Missing snapshot -> non-zero with `no CANDIDATE snapshot for YYYY-MM-DD`.
- [ ] **Step 2:** Published empty snapshot -> exit 0, `candidates: 0`.
- [ ] **Step 3:** Prove read-only.
- [ ] **Step 4:** Implement using only `SnapshotKind.CANDIDATE`.
- [ ] **Step 5:** Commit.

```bash
git add src/astock_lens/cli/app.py tests/integration/test_candidates_cli.py
git commit -m "命令：增加正式候选股票列表查询"
git push
```

---

### Task 3: Upgrade Stock Profile Candidate Explanation

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Modify: `src/astock_lens/api/app.py`
- Modify: stock/API tests

When published, show:

```text
candidate_status
primary_strategy
qualified_strategies
market_validation
signal
next_action
reasons
risks
lineage versions
```

- [ ] **Step 1:** Primary strategy visible.
- [ ] **Step 2:** Risk signal visible.
- [ ] **Step 3:** Implement without recomputation.
- [ ] **Step 4:** Commit.

```bash
git add src/astock_lens/cli/app.py src/astock_lens/api/app.py tests
git commit -m "画像：补齐候选主策略市场信号与风险解释"
git push
```

---

### Task 4: Add Today Read Model

**Files:**
- Create: `src/astock_lens/discovery/today.py`
- Create: `tests/integration/test_today_cli.py`
- Modify: `src/astock_lens/cli/app.py`

**CLI:**

```bash
astock today --as-of YYYY-MM-DD
```

Output:

```text
as_of
candidate_count
market_regime if stored/available
candidate counts by primary strategy
candidate counts by market validation
candidate counts by signal
top 10 candidates
```

No new ranking.

- [ ] **Step 1:** No Candidate publication -> explicit error/not-published.
- [ ] **Step 2:** Exact aggregation test.
- [ ] **Step 3:** Top list preserves Candidate snapshot order.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Commit.

```bash
git add src/astock_lens/discovery/today.py src/astock_lens/cli/app.py tests/integration/test_today_cli.py
git commit -m "命令：增加盘后候选研究概览"
git push
```

---

### Task 5: Add `/today` API

**Files:**
- Modify: `src/astock_lens/api/app.py`
- Modify: `tests/unit/test_api.py`

**API:**

```http
GET /today?as_of=YYYY-MM-DD
```

- [ ] **Step 1:** Same semantics as CLI read model.
- [ ] **Step 2:** Missing Candidate snapshot -> 404.
- [ ] **Step 3:** Implement via discovery read model.
- [ ] **Step 4:** Boundary test: no pipeline imports.
- [ ] **Step 5:** Commit.

```bash
git add src/astock_lens/api/app.py tests/unit/test_api.py
git commit -m "接口：增加盘后候选研究概览"
git push
```

---

### Task 6: Product Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REVIEW_NOTES.md`

- [ ] **Step 1:** Run `astock candidates`, `astock today`, `astock stock` on accepted Candidate-v2 date.
- [ ] **Step 2:** API smoke: `/candidates`, `/today`, `/stocks/{symbol}`.
- [ ] **Step 3:** Read-only fingerprint test.
- [ ] **Step 4:** Full quality gate.

```bash
PYTHONPATH= uv run --no-sync pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

- [ ] **Step 5:** Commit docs.

```bash
git add README.md docs/ROADMAP.md docs/REVIEW_NOTES.md
git commit -m "验收：候选与Today查询进入日常使用"
git push
```

## Final Acceptance

```text
想看策略排行        -> astock screen
想看双门槛合格股票  -> astock qualified
想看正式研究候选    -> astock candidates
想看当天整体结果    -> astock today
想看某只股票为何入选 -> astock stock SYMBOL
```

本计划不要求 Web UI。
