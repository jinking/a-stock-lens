# Market Evidence Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete missing R2 Market Regime and 5-dimensional Market Validation evidence, then produce an owner decision packet for the few semantics still not precisely defined.

**Architecture:** Add auditable evidence objects instead of hidden calculations inside verdict functions. Stock bars provide breadth and volume ratio; benchmark and volatility evidence get explicit contracts. Industry evidence is only produced when canonical membership supports the approved hierarchy without guessing.

**Tech Stack:** Existing normalized repository, Provider interfaces, Pydantic, pytest, calibration/report modules.

**Spec:** `docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md`

## Global Constraints

- Do not substitute Research Universe median for an approved benchmark index.
- Do not relabel second-level industry as first-level industry.
- Do not invent an extreme-volatility threshold.
- Do not publish Candidate until required evidence has an approved interpretation.
- Every derived metric must expose source period/as_of.

## Review Focus

1. Benchmark source unavailable -> explicit blocker.
2. Industry hierarchy unavailable -> explicit blocker.
3. Fewer than 20 valid volumes -> ratio missing, not zero.
4. Stock/benchmark windows misaligned -> reject future/incompatible data.
5. Volatility rule not owner-approved -> Candidate remains blocked.

---

### Task 1: Auditable Stock-Side Market Evidence

**Files:**
- Create: `src/astock_lens/market/evidence.py`
- Create: `tests/unit/test_market_evidence.py`

**Interface:**

```python
class StockMarketEvidence(DomainRecord):
    symbol: str
    as_of: datetime
    ret_20d: float | None
    proximity_52w_high: float | None
    avg_amount_20d: float | None
    volume_ratio_5_20: float | None
```

```python
def build_stock_market_evidence(*, symbol: str, factors: Sequence[FactorResult], bars: Sequence[DailyBar], as_of: datetime) -> StockMarketEvidence: ...
```

`volume_ratio_5_20 = mean(latest 5 valid volumes) / mean(latest 20 valid volumes)`.

- [ ] **Step 1:** Exact ratio RED test.
- [ ] **Step 2:** Fewer than 20 valid bars -> `None`.
- [ ] **Step 3:** Future bars excluded.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Commit.

```bash
git add src/astock_lens/market/evidence.py tests/unit/test_market_evidence.py
git commit -m "市场证据：增加可审计量价输入"
git push
```

---

### Task 2: Benchmark Source Probe with Hard Stop

**Files:**
- Create: `src/astock_lens/market/benchmark.py`
- Create: `tests/unit/test_benchmark_evidence.py`
- Create: `docs/decision-packets/2026-09-21-benchmark-source-probe.md`

**Interfaces:**

```python
class BenchmarkEvidenceUnavailable(RuntimeError): ...
class BenchmarkEvidence(DomainRecord):
    benchmark_id: str
    as_of: datetime
    ret_60d: float
    trend_value: float
    source: str
```

- [ ] **Step 1:** Search existing providers for stable index/benchmark daily-bars capability and record exact result.
- [ ] **Step 2:** If an existing provider supports it, add a narrow adapter only for approved benchmark series.
- [ ] **Step 3:** If no current provider supports it, implement contract + explicit blocker only; do not guess a new third-party endpoint.
- [ ] **Step 4:** Test unavailable source raises `BenchmarkEvidenceUnavailable`.
- [ ] **Step 5:** Commit.

```bash
git add src/astock_lens/market/benchmark.py tests/unit/test_benchmark_evidence.py docs/decision-packets/2026-09-21-benchmark-source-probe.md
git commit -m "市场证据：锁定基准指数数据源边界"
git push
```

---

### Task 3: Industry Evidence without Hierarchy Guessing

**Files:**
- Create: `src/astock_lens/market/industry.py`
- Create: `tests/unit/test_industry_market_evidence.py`

**Interfaces:**

```python
class IndustryEvidenceUnavailable(RuntimeError): ...
class IndustryEvidence(DomainRecord):
    symbol: str
    industry_id: str
    industry_level: str
    industry_return_20d: float
    benchmark_return_20d: float
    industry_excess_return_20d: float
    as_of: datetime
```

- [ ] **Step 1:** Inspect canonical industry fields and prove whether SW1/SW2 hierarchy exists.
- [ ] **Step 2:** If approved hierarchy cannot be derived, RED test must raise `IndustryEvidenceUnavailable`.
- [ ] **Step 3:** If hierarchy exists, calculate from the exact proved source fields; never rename SW2 as SW1.
- [ ] **Step 4:** Persist member count/denominator evidence.
- [ ] **Step 5:** Commit.

```bash
git add src/astock_lens/market/industry.py tests/unit/test_industry_market_evidence.py
git commit -m "市场证据：建立行业超额收益的层级安全边界"
git push
```

---

### Task 4: True Relative Strength

**Files:**
- Modify: `src/astock_lens/market/evidence.py`
- Modify: `tests/unit/test_market_evidence.py`

Add:

```python
relative_strength_60d: float | None
```

Definition:

```text
stock ret_60d - approved benchmark ret_60d
```

- [ ] **Step 1:** Exact subtraction test.
- [ ] **Step 2:** Missing benchmark -> `None`.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Commit.

```bash
git add src/astock_lens/market/evidence.py tests/unit/test_market_evidence.py
git commit -m "市场证据：相对强弱改为真实基准超额收益"
git push
```

---

### Task 5: Candidate-v2 Impact Report

**Files:**
- Create: `src/astock_lens/calibration/candidate_v2_impact.py`
- Create: `tests/unit/test_candidate_v2_impact.py`
- Modify: `src/astock_lens/cli/app.py`

**CLI:**

```bash
astock calibrate candidate-v2-impact --as-of YYYY-MM-DD --output-dir PATH
```

Report per primary strategy:

```text
qualified_count
complete_5d_evidence_count
missing_industry_count
missing_benchmark_count
missing_volume_ratio_count
candidate_v1_count
BREAKDOWN_count
TREND_WEAKEN_count
NO_SIGNAL_count
```

- [ ] **Step 1:** Explicit denominator tests.
- [ ] **Step 2:** Prove command is read-only.
- [ ] **Step 3:** Implement deterministic JSON + Markdown.
- [ ] **Step 4:** Run on 2026-09-19 data without rewriting canonical snapshots.
- [ ] **Step 5:** Commit.

```bash
git add src/astock_lens/calibration/candidate_v2_impact.py src/astock_lens/cli/app.py tests/unit/test_candidate_v2_impact.py
git commit -m "校准：增加候选v2市场证据影响审计"
git push
```

---

### Task 6: Build Owner Decision Packet

**Files:**
- Create: `docs/decision-packets/2026-09-21-candidate-v2-market-evidence-decision.md`
- Modify: `docs/REMAINING_PRODUCT_BLOCKERS.md`

Packet must contain measured evidence for:

```text
1. benchmark source/coverage
2. benchmark-trend formula candidates
3. volatility distribution and threshold choices
4. industry hierarchy availability
5. BREAKDOWN / TREND_WEAKEN / NO_SIGNAL population
6. Candidate count impact under each signal policy option
```

Required Owner decisions:

```text
A. benchmark composition/formula
B. extreme-volatility threshold
C. industry hierarchy/aggregation if ambiguous
D. BREAKDOWN Candidate semantics
E. TREND_WEAKEN Candidate semantics
F. NO_SIGNAL Candidate semantics
```

- [ ] **Step 1:** Show exact counts under each option.
- [ ] **Step 2:** Commit packet and blocker update.
- [ ] **Step 3:** STOP and wait for Owner approval before production wiring.

---

### Task 7: After Owner Approval, Wire Full R2 / 5D

**Files:**
- Modify: `src/astock_lens/market/regime.py`
- Modify: `src/astock_lens/market/validation.py`
- Modify: `src/astock_lens/pipelines/stages.py`
- Modify: `src/astock_lens/pipelines/daily.py`
- Modify: tests

**Precondition:** Owner choices from Task 6 are recorded verbatim in repo docs.

- [ ] **Step 1:** Contract tests encode the approved values.
- [ ] **Step 2:** Market Regime consumes every approved R2 input; no constant false volatility and no absent benchmark trend.
- [ ] **Step 3:** Market Validation consumes all five dimensions.
- [ ] **Step 4:** Signal-to-Candidate semantics follow the approved matrix.
- [ ] **Step 5:** Full quality gate.

```bash
PYTHONPATH= uv run --no-sync pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

- [ ] **Step 6:** Commit.

```bash
git add src tests docs
git commit -m "候选：按审批口径接通完整R2与五维验证"
git push
```

---

### Task 8: Independent Business Verdict Replay

**Files:**
- Modify: `tests/artifacts/validator.py`
- Modify: `tests/artifacts/test_candidate_semantic_validator.py`

- [ ] **Step 1:** Independently recalculate approved deterministic verdicts without importing `astock_lens.market`, `astock_lens.signals`, or `astock_lens.candidates`.
- [ ] **Step 2:** Check Candidate primary strategy + Signal.
- [ ] **Step 3:** Check Market Validation from serialized evidence.
- [ ] **Step 4:** Check approved signal publication policy.
- [ ] **Step 5:** Commit.

```bash
git add tests/artifacts
git commit -m "审计：独立复算候选市场验证与信号判定"
git push
```

---

### Task 9: Fresh Production Acceptance without Rewriting History

**Files:**
- Modify: `docs/REVIEW_NOTES.md`
- Modify: `docs/ROADMAP.md`
- Create: `docs/decision-packets/<new-trade-date>-candidate-v2-audit.md`

- [ ] **Step 1:** Use the next real trading-day data already present locally; do not overwrite 2026-09-19 canonical snapshot.
- [ ] **Step 2:** Run full daily pipeline.
- [ ] **Step 3:** Run independent artifact validator, expected 0 findings.
- [ ] **Step 4:** Report v1 vs v2 changed counts/symbols as research evidence.
- [ ] **Step 5:** Commit only documentation; runtime snapshots stay out of Git.

```bash
git add docs
git commit -m "验收：完成候选v2全链路独立审计"
git push
```

## Mandatory STOP Gate

Plan B complete only when R2 inputs complete, 5D inputs complete, strategy identity correct, Signal publication semantics owner-approved, independent replay 0 findings, and fresh production acceptance passes. Only then execute Plan C.
