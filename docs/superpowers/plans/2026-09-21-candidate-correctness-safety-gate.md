# Candidate Correctness Safety Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop incorrect Candidate publication immediately, preserve strategy identity through Market/Signal evaluation, and make Candidate lineage/artifact validation detect the current production wiring errors.

**Architecture:** Derive one deterministic `primary_strategy_id` from approved qualified strategies. Market Validation and Signal must consume that explicit strategy context. Until complete R2/5D evidence and Signal publication semantics are approved, Candidate Publishing fails closed.

**Tech Stack:** Python 3.12+, Pydantic 2.x, Typer, pytest, existing SnapshotStore/JobStore and independent artifact validator.

**Spec:** `docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md`

## Global Constraints

- Do not change approved Qualification thresholds.
- Do not add a cross-strategy weighted score.
- Do not default missing Market evidence to neutral values.
- Do not move/delete canonical snapshots to bypass `SnapshotConflictError`.
- Keep `screen`, `qualified`, `stock` read-only behavior intact.
- TDD: RED -> minimal GREEN -> fresh review -> commit -> push.

## Review Focus

1. Multi-strategy qualified symbol: primary strategy deterministic.
2. Missing Market/Signal evidence: Candidate not published.
3. BREAKDOWN/TREND_WEAKEN/NO_SIGNAL remain explicit.
4. Candidate lineage carries Qualification, Regime, Market Validation, Signal, Candidate Policy versions.
5. Existing canonical snapshot cannot be silently replaced.

---

## Locked File Structure

### Create
- `src/astock_lens/candidates/context.py`
- `tests/unit/test_candidate_primary_strategy.py`
- `tests/integration/test_candidate_correctness_gate.py`
- `tests/artifacts/test_candidate_semantic_validator.py`

### Modify
- `src/astock_lens/domain/models.py`
- `src/astock_lens/market/validation.py`
- `src/astock_lens/signals/contracts.py`
- `src/astock_lens/signals/detector.py`
- `src/astock_lens/pipelines/stages.py`
- `src/astock_lens/pipelines/daily.py`
- `src/astock_lens/candidates/models.py`
- `src/astock_lens/candidates/policy.py`
- `src/astock_lens/candidates/builder.py`
- `tests/artifacts/validator.py`
- `tests/integration/test_daily_candidate_pipeline.py`
- `docs/ROADMAP.md`
- `docs/REVIEW_NOTES.md`

### Forbidden
- `configs/qualifications/*.yaml`
- production threshold changes
- Candidate v2 publication before Plan B Owner Gate
- deleting/moving canonical snapshots to force a rerun

---

### Task 1: Lock Current Wiring Bugs with RED Tests

**Files:**
- Create: `tests/integration/test_candidate_correctness_gate.py`
- Modify: `tests/integration/test_daily_candidate_pipeline.py`

- [ ] **Step 1:** Add a test where a Value-qualified symbol has `ret_20d=-0.04`, sufficient liquidity, and must keep `strategy_id="value"` instead of Momentum semantics.
- [ ] **Step 2:** Run it and confirm baseline failure.

```bash
PYTHONPATH= uv run --no-sync pytest tests/integration/test_candidate_correctness_gate.py -v
```

- [ ] **Step 3:** Add a Growth case that must never fall through to `VALUE_CONTRARIAN` merely because `strategy_id=None`.
- [ ] **Step 4:** Add a no-breadth case and assert `DETECT_REGIME` does not succeed via synthetic `0.50`.
- [ ] **Step 5:** Add an incomplete-5D case and assert no CANDIDATE snapshot is written.
- [ ] **Step 6:** Commit tests only.

```bash
git add tests/integration/test_candidate_correctness_gate.py tests/integration/test_daily_candidate_pipeline.py
git commit -m "测试：锁定候选生产接线四类正确性缺口"
git push
```

---

### Task 2: Add Deterministic `primary_strategy_id`

**Files:**
- Create: `src/astock_lens/candidates/context.py`
- Create: `tests/unit/test_candidate_primary_strategy.py`
- Modify: `src/astock_lens/candidates/models.py`

**Interface:**

```python
def primary_qualified_strategy(
    qualifications: Sequence[StrategyQualification],
) -> str:
    """Highest qualified rank_percentile; tie -> strategy_id ASC."""
```

Candidate adds:

```python
primary_strategy_id: str
```

- [ ] **Step 1:** Highest qualified percentile wins.
- [ ] **Step 2:** Equal percentile resolves by `strategy_id` ascending.
- [ ] **Step 3:** Unqualified strategy never wins even with higher percentile.
- [ ] **Step 4:** No qualified strategy raises explicit `ValueError`.
- [ ] **Step 5:** Implement helper without introducing any score aggregation.
- [ ] **Step 6:** Persist `primary_strategy_id` on Candidate.
- [ ] **Step 7:** Verify.

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_candidate_primary_strategy.py -v
```

- [ ] **Step 8:** Commit.

```bash
git add src/astock_lens/candidates/context.py src/astock_lens/candidates/models.py tests/unit/test_candidate_primary_strategy.py
git commit -m "候选：增加确定性主策略上下文"
git push
```

---

### Task 3: Make Market Validation and Signal Strategy-Explicit

**Files:**
- Modify: `src/astock_lens/market/validation.py`
- Modify: `src/astock_lens/signals/contracts.py`
- Modify: `src/astock_lens/signals/detector.py`
- Modify: `src/astock_lens/pipelines/stages.py`
- Modify: relevant unit/integration tests

`SignalResult` adds:

```python
strategy_id: str
```

Change stage signatures to explicit mappings:

```python
def market_validation_stage(
    *,
    strategy_by_symbol: Mapping[str, str],
    factor_results: Sequence[FactorResult],
    as_of: datetime,
    ...,
) -> tuple[MarketValidationResult, ...]:
    ...
```

```python
def signal_stage(
    *,
    strategy_by_symbol: Mapping[str, str],
    factor_results: Sequence[FactorResult],
    as_of: datetime,
    market_regime: MarketRegime | None,
    ...,
) -> tuple[SignalResult, ...]:
    ...
```

- [ ] **Step 1:** Missing strategy mapping raises a named error.
- [ ] **Step 2:** Same factors under Value vs Momentum produce strategy-correct validation behavior.
- [ ] **Step 3:** Growth cannot hit Value/Dividend-only signal rules.
- [ ] **Step 4:** Remove `strategy_id="momentum"` default and `strategy_id=None` fallback.
- [ ] **Step 5:** Persist `strategy_id` in `SignalResult`.
- [ ] **Step 6:** Run focused tests.

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_market_validator.py tests/unit/test_signal_detector.py tests/integration/test_candidate_correctness_gate.py -v
```

- [ ] **Step 7:** Commit.

```bash
git add src/astock_lens/market/validation.py src/astock_lens/signals/contracts.py src/astock_lens/signals/detector.py src/astock_lens/pipelines/stages.py tests
git commit -m "修复：市场验证与信号强制绑定主策略"
git push
```

---

### Task 4: Move Qualification Evidence Forward in Daily State

**Files:**
- Modify: `src/astock_lens/pipelines/daily.py`
- Modify: `tests/integration/test_candidate_correctness_gate.py`
- Modify: `tests/integration/test_daily_candidate_pipeline.py`

Add private helpers:

```python
def _ensure_qualifications(context: _Context, state: _State) -> tuple[StrategyQualification, ...]: ...
def _primary_strategy_by_symbol(qualifications: Sequence[StrategyQualification]) -> dict[str, str]: ...
```

- [ ] **Step 1:** Test that only symbols with at least one qualified strategy enter downstream validation/signal preparation.
- [ ] **Step 2:** Test deterministic primary strategy mapping for multi-qualified symbols.
- [ ] **Step 3:** Implement `_ensure_qualifications` using existing `stages.qualification_stage()` once and cache `state.qualifications`.
- [ ] **Step 4:** `_market_validate` derives and uses the primary strategy mapping.
- [ ] **Step 5:** `_run_signals` reuses the exact same mapping.
- [ ] **Step 6:** `_build_candidates` reuses cached qualifications; no second qualification pass.
- [ ] **Step 7:** Commit.

```bash
git add src/astock_lens/pipelines/daily.py tests/integration/test_candidate_correctness_gate.py tests/integration/test_daily_candidate_pipeline.py
git commit -m "管线：资格证据前置并统一主策略上下文"
git push
```

---

### Task 5: Restore Fail-Closed Market Evidence

**Files:**
- Modify: `src/astock_lens/pipelines/daily.py`
- Modify: `src/astock_lens/market/regime.py`
- Modify: `src/astock_lens/market/validation.py`
- Modify: `tests/integration/test_candidate_correctness_gate.py`

Add:

```python
class MarketRegimeEvidenceIncomplete(RuntimeError): ...
class MarketValidationEvidenceIncomplete(RuntimeError): ...
```

- [ ] **Step 1:** No breadth -> no synthetic `0.50`.
- [ ] **Step 2:** Missing required 5D input -> `MarketValidationEvidenceIncomplete`.
- [ ] **Step 3:** Delete production fallback `breadth_ratio if ... else 0.50`.
- [ ] **Step 4:** Distinguish real neutral verdict from missing evidence.
- [ ] **Step 5:** `daily --allow-incomplete` may report the blocker but must not write CANDIDATE.
- [ ] **Step 6:** Commit.

```bash
git add src/astock_lens/pipelines/daily.py src/astock_lens/market/regime.py src/astock_lens/market/validation.py tests/integration/test_candidate_correctness_gate.py
git commit -m "安全：市场证据不完整时停止候选发布"
git push
```

---

### Task 6: Fix Candidate Lineage

**Files:**
- Modify: `src/astock_lens/domain/models.py`
- Modify: `src/astock_lens/market/validation.py`
- Modify: `src/astock_lens/candidates/builder.py`
- Modify: `src/astock_lens/pipelines/stages.py`
- Modify: candidate tests

`SnapshotLineage` adds:

```python
market_validation_version: str | None = None
```

and accessor:

```python
def market_validation_versions(self) -> frozenset[str]: ...
```

- [ ] **Step 1:** Test `MarketValidationResult.lineage.market_validation_version == "v1"` and `regime_version` is not reused.
- [ ] **Step 2:** Test Candidate carries non-empty factor/strategy/qualification/regime/market_validation/signal/policy versions.
- [ ] **Step 3:** Implement field/accessor.
- [ ] **Step 4:** Propagate actual stage versions; do not hard-code in CandidateBuilder.
- [ ] **Step 5:** Commit.

```bash
git add src/astock_lens/domain/models.py src/astock_lens/market/validation.py src/astock_lens/candidates/builder.py src/astock_lens/pipelines/stages.py tests
git commit -m "血缘：补齐市场验证与信号规则版本"
git push
```

---

### Task 7: Upgrade Independent Artifact Validation

**Files:**
- Modify: `tests/artifacts/validator.py`
- Create: `tests/artifacts/test_candidate_semantic_validator.py`

New independent checks:

```text
primary_strategy_id exists
primary_strategy_id has matching qualified qualification
Signal strategy_id == primary_strategy_id
Market Validation strategy_id == primary_strategy_id
Market/Signal version fields exist
```

- [ ] **Step 1:** Wrong-primary artifact must fail.
- [ ] **Step 2:** Signal strategy mismatch must fail.
- [ ] **Step 3:** Market Validation strategy mismatch must fail.
- [ ] **Step 4:** Missing lineage version must fail.
- [ ] **Step 5:** Implement structural semantic checks without importing production code.
- [ ] **Step 6:** Commit.

```bash
git add tests/artifacts/validator.py tests/artifacts/test_candidate_semantic_validator.py
git commit -m "审计：独立校验候选主策略与市场信号血缘"
git push
```

---

### Task 8: Lock Snapshot Immutability

**Files:**
- Modify: snapshot-store tests
- Modify: `docs/DEVELOPMENT.md`
- Modify: `docs/REVIEW_NOTES.md`

- [ ] **Step 1:** Regression test: same `(kind, as_of)` + different content must raise `SnapshotConflictError`.
- [ ] **Step 2:** Document historical re-evaluation output under `var/acceptance/<run-name>/` only.
- [ ] **Step 3:** Search repository and reject any production helper that auto-moves/deletes canonical snapshots to enable changed reruns.
- [ ] **Step 4:** Commit.

```bash
git add tests docs/DEVELOPMENT.md docs/REVIEW_NOTES.md
git commit -m "存储：禁止通过迁移旧快照绕过冲突保护"
git push
```

---

## Mandatory STOP Gate

Plan A 完成后：`screen / qualified / stock` 继续可用；历史 Candidate v1 可读；新 Candidate 允许 BLOCKED。不要执行 Plan C，直接进入 Plan B。

## Required Completion Report

```text
1. task commit SHAs
2. remote HEAD
3. focused tests
4. full pytest
5. ruff / format / mypy
6. proof Value no longer uses Momentum validation
7. proof Growth cannot hit Value/Dividend signal fallback
8. proof missing breadth no longer becomes 0.50
9. proof incomplete 5D evidence prevents Candidate publication
10. proof Candidate lineage contains validation/signal versions
11. proof canonical snapshot conflict cannot be bypassed
12. git status --short
```
