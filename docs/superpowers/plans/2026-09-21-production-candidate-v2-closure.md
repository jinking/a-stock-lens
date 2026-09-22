# Production Candidate v2 Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the standard `astock daily` path produce the same evidence-complete Candidate v2 semantics already proven in the acceptance sandbox, including a formal MARKET_REGIME snapshot and a new immutable canonical Candidate v2 publication.

**Architecture:** Load benchmark and industry evidence explicitly at the production composition root, make R2/5D evidence completeness enforceable contracts, and let `run_daily()` consume only already-landed evidence. Snapshot publication remains immutable and `daily` remains the only formal writer.

**Tech Stack:** Python >=3.12, Typer, Pydantic 2.x, existing Raw/Normalized/Snapshot stores, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-21-production-candidate-v2-web-mvp-design.md`

## Global Constraints

- Keep approved A1/B3/C1/D1/E1/F1 semantics unchanged.
- Do not change Qualification thresholds or Strategy weights.
- Do not overwrite or move historical canonical snapshots.
- Do not fetch benchmark data inside MarketRegime/MarketValidation logic.
- Missing required production evidence must fail closed.
- `daily` remains the only formal Snapshot writer.
- TDD: RED → GREEN → review → commit → push.

## Review Focus

1. Benchmark file missing or <60 valid bars → DETECT_REGIME fails closed and no Candidate snapshot is written.
2. One qualified symbol missing SW2 membership → MARKET_VALIDATE fails closed; it must not silently become NEUTRAL.
3. One qualified symbol with <20 valid volume bars → MARKET_VALIDATE fails closed.
4. Existing canonical snapshot on the same date differs → SnapshotConflictError remains effective.
5. MARKET_REGIME writes exactly one valid record and Today can read it without recomputation.

---

## Locked File Structure

### Create

- `src/astock_lens/data/benchmark.py`
- `tests/unit/test_benchmark_landing_reader.py`
- `tests/integration/test_daily_production_evidence.py`
- `tests/integration/test_market_regime_snapshot.py`

### Modify

- `src/astock_lens/cli/app.py`
- `src/astock_lens/pipelines/daily.py`
- `src/astock_lens/market/regime.py`
- `src/astock_lens/market/validation.py`
- `tests/unit/test_market_regime.py`
- `tests/unit/test_market_validator.py`
- `tests/integration/test_daily_candidate_pipeline.py`
- `tests/artifacts/validator.py`
- `README.md`
- `docs/ROADMAP.md`
- `docs/REMAINING_PRODUCT_BLOCKERS.md`
- `docs/REVIEW_NOTES.md`

### Forbidden

- Web code
- Candidate ranking redesign
- Cross-strategy global score
- Historical snapshot replacement
- Runtime network call from Market/Signal code

---

### Task 1: Make R2 Require Breadth + Approved Benchmark Trend

**Files:**
- Modify: `src/astock_lens/market/regime.py`
- Modify: `tests/unit/test_market_regime.py`

**Interfaces:**
- Consumes: `MarketRegimeContext`
- Produces: `MarketRegimeResult` or `MarketRegimeEvidenceIncomplete`

- [ ] **Step 1: Write the failing benchmark-missing test**

```python
def test_r2_requires_breadth_and_index_trend():
    detector = MarketRegimeDetector(version="v2")
    ctx = MarketRegimeContext(
        as_of=AS_OF,
        breadth_ratio=0.61,
        index_trend=None,
        extreme_volatility=False,
    )
    with pytest.raises(MarketRegimeEvidenceIncomplete):
        detector.detect(ctx)
```

- [ ] **Step 2: Run it and confirm baseline failure**

```bash
PYTHONPATH= uv run --no-sync pytest \
  tests/unit/test_market_regime.py::test_r2_requires_breadth_and_index_trend -v
```

Expected on baseline: FAIL because breadth-only currently produces a regime.

- [ ] **Step 3: Add the breadth-missing test**

`index_trend` present but `breadth_ratio=None` must also raise.

- [ ] **Step 4: Implement the approved completeness gate**

At the top of `detect()`:

```python
if context.breadth_ratio is None:
    raise MarketRegimeEvidenceIncomplete("R2 requires breadth_ratio")
if context.index_trend is None:
    raise MarketRegimeEvidenceIncomplete(
        "R2 A1 requires 000985.CSI benchmark trend"
    )
```

Keep B3 as an explicitly deferred gate; append a reason saying the volatility gate is deferred by approved decision B3.

- [ ] **Step 5: Run focused tests**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_market_regime.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/market/regime.py tests/unit/test_market_regime.py
git commit -m "市场环境：R2生产判定强制要求宽度与基准趋势"
git push
```

---

### Task 2: Make All Five Validation Dimensions Mandatory

**Files:**
- Modify: `src/astock_lens/market/validation.py`
- Modify: `tests/unit/test_market_validator.py`

**Interfaces:**
- Consumes: `MarketValidationContext`
- Produces: `MarketValidationResult` or `MarketValidationEvidenceIncomplete`

- [ ] **Step 1: Write RED tests for missing industry / relative strength / volume ratio**

```python
with pytest.raises(MarketValidationEvidenceIncomplete):
    validator.validate(valid_context.model_copy(update={"industry_excess_return": None}))

with pytest.raises(MarketValidationEvidenceIncomplete):
    validator.validate(valid_context.model_copy(update={"relative_strength_60d": None}))

with pytest.raises(MarketValidationEvidenceIncomplete):
    validator.validate(valid_context.model_copy(update={"vol_ratio": None}))
```

- [ ] **Step 2: Add RED tests for missing stock trend and liquidity inputs**

Missing any of:

```text
ret_20d
proximity_52w_high
avg_amount_20d
```

must raise.

- [ ] **Step 3: Implement one explicit evidence preflight**

```python
missing: list[str] = []
if factor_map.get("ret_20d") is None:
    missing.append("ret_20d")
if factor_map.get("proximity_52w_high") is None:
    missing.append("proximity_52w_high")
if factor_map.get("avg_amount_20d") is None:
    missing.append("avg_amount_20d")
if context.industry_excess_return is None:
    missing.append("industry_excess_return_20d")
if context.relative_strength_60d is None:
    missing.append("relative_strength_60d")
if context.vol_ratio is None:
    missing.append("volume_ratio_5_20")
if missing:
    raise MarketValidationEvidenceIncomplete(
        f"{context.symbol} missing required 5D evidence: {', '.join(missing)}"
    )
```

Delete the existing `relative_strength_60d is None → ret_60d` fallback.

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_market_validator.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/astock_lens/market/validation.py tests/unit/test_market_validator.py
git commit -m "市场验证：五维证据缺一即阻断"
git push
```

---

### Task 3: Add Canonical Benchmark-Bar Reader

**Files:**
- Create: `src/astock_lens/data/benchmark.py`
- Create: `tests/unit/test_benchmark_landing_reader.py`

**Interfaces:**

```python
BENCHMARK_BARS_ENV = "ASTOCK_BENCHMARK_BARS_PATH"
DEFAULT_BENCHMARK_BARS_PATH = Path("data/raw/benchmark_bars.csv")

def read_benchmark_bars(
    *,
    path: Path,
    benchmark_id: str,
    as_of: datetime,
) -> tuple[DailyBar, ...]:
    ...
```

Expected columns:

```text
symbol,trade_date,open,high,low,close,volume,amount
```

- [ ] **Step 1: RED future-row exclusion**
- [ ] **Step 2: RED wrong-symbol exclusion**
- [ ] **Step 3: RED malformed-column error**
- [ ] **Step 4: Implement with stdlib CSV; no dataframe dependency**
- [ ] **Step 5: Verify**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_benchmark_landing_reader.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/data/benchmark.py tests/unit/test_benchmark_landing_reader.py
git commit -m "数据：增加中证全指基准日线只读契约"
git push
```

---

### Task 4: Add Deterministic Production Industry Loader

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Modify/Create: focused CLI helper tests

**Interfaces:**

```python
def _latest_industry_file(day: datetime) -> Path:
    ...

def _production_industry_map(day: datetime) -> dict[str, str]:
    ...
```

Algorithm:

```text
directory = <ASTOCK_CSV_ROOT>/westock/industry
eligible = ISO-date *.csv where date <= as_of
choose latest
read_industry_memberships(file)
append load_supplemental_industry_memberships(as_of=day)
build_industry_map(...)
```

- [ ] **Step 1: RED exact-date test**
- [ ] **Step 2: RED latest-prior-date test**
- [ ] **Step 3: RED future-date exclusion**
- [ ] **Step 4: RED no-data test; no eligible file must raise**
- [ ] **Step 5: Implement and preserve `IndustryMembershipAmbiguous` fail-closed behavior**
- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/cli/app.py tests
git commit -m "生产接线：按时点加载申万二级行业映射"
git push
```

---

### Task 5: Wire Benchmark + Industry into Standard `astock daily`

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Create: `tests/integration/test_daily_production_evidence.py`

**Interfaces:**

`_run_daily()` must build:

```python
benchmark_bars = read_benchmark_bars(
    path=_benchmark_bars_path(),
    benchmark_id="000985.CSI",
    as_of=day,
)
industry_by_symbol = _production_industry_map(day)
```

and pass them to:

```python
run_daily(
    ...,
    benchmark_id="000985.CSI",
    benchmark_bars=benchmark_bars,
    industry_by_symbol=industry_by_symbol,
)
```

- [ ] **Step 1: RED composition test proving exact values reach `run_daily()`**
- [ ] **Step 2: RED missing benchmark file → non-zero and no new Candidate snapshot**
- [ ] **Step 3: RED 59 benchmark bars → DETECT_REGIME fail-closed**
- [ ] **Step 4: RED qualified symbol missing industry evidence → MARKET_VALIDATE fail-closed**
- [ ] **Step 5: RED qualified symbol with <20 valid volume bars → MARKET_VALIDATE fail-closed**
- [ ] **Step 6: Implement production composition; no network request from `_run_daily()`**
- [ ] **Step 7: Verify**

```bash
PYTHONPATH= uv run --no-sync pytest tests/integration/test_daily_production_evidence.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/astock_lens/cli/app.py tests/integration/test_daily_production_evidence.py
git commit -m "生产接线：daily装配候选v2完整市场证据"
git push
```

---

### Task 6: Persist MARKET_REGIME Snapshot

**Files:**
- Modify: `src/astock_lens/pipelines/daily.py`
- Create: `tests/integration/test_market_regime_snapshot.py`
- Modify: artifact validator tests

**Interfaces:**

Extend `_record()`:

```python
elif kind is SnapshotKind.MARKET_REGIME:
    records = (state.regime_result,) if state.regime_result is not None else ()
```

After successful `DETECT_REGIME`:

```python
_record(state, SnapshotKind.MARKET_REGIME, context.store, context.as_of)
```

- [ ] **Step 1: RED exactly-one-record test**
- [ ] **Step 2: RED lineage version test**
- [ ] **Step 3: RED same-date changed-content conflict test**
- [ ] **Step 4: Implement producer**
- [ ] **Step 5: Extend artifact validator for MARKET_REGIME vocabulary/as_of/version**
- [ ] **Step 6: Seed MARKET_REGIME + CANDIDATE and assert `astock today` prints it**
- [ ] **Step 7: Commit**

```bash
git add src/astock_lens/pipelines/daily.py tests/integration/test_market_regime_snapshot.py tests/artifacts
git commit -m "快照：正式持久化每日市场环境"
git push
```

---

### Task 7: Fresh Canonical Candidate v2 Production Acceptance

**Files:**
- Create: `docs/decision-packets/<accepted-date>-candidate-v2-production-audit.md`
- Modify: `docs/REVIEW_NOTES.md`

**Precondition:** Choose the latest local trading date that has all of:

```text
stock daily bars
000985.CSI >= 60 bars
SW2 industry membership
financial / valuation inputs required by existing pipeline
```

If no date satisfies this, STOP and report the exact missing dataset. Never reuse or overwrite `2026-09-19`.

- [ ] **Step 1: Record the chosen date and evidence paths**
- [ ] **Step 2: Run standard CLI only**

```bash
PYTHONPATH= uv run --no-sync astock daily --as-of <accepted-date>
```

- [ ] **Step 3: Verify five canonical snapshot kinds**

```text
UNIVERSE
FACTOR
STRATEGY
MARKET_REGIME
CANDIDATE
```

- [ ] **Step 4: Run independent artifact validation; expected 0 findings**
- [ ] **Step 5: Run user-facing queries**

```bash
PYTHONPATH= uv run --no-sync astock today --as-of <accepted-date>
PYTHONPATH= uv run --no-sync astock candidates --as-of <accepted-date> --top 20
PYTHONPATH= uv run --no-sync astock stock <first-candidate-symbol> --as-of <accepted-date>
```

- [ ] **Step 6: Record production counts**

At minimum: research universe, qualified unique symbols, confirmed, neutral, contradicted, signal distribution, candidate count, primary-strategy distribution.

- [ ] **Step 7: Commit audit docs only**

```bash
git add docs/decision-packets docs/REVIEW_NOTES.md
git commit -m "验收：标准daily正式发布候选v2"
git push
```

---

### Task 8: Collapse Stale Current-State Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REMAINING_PRODUCT_BLOCKERS.md`
- Create/Modify: a lightweight docs consistency test

- [ ] **Step 1: Remove current-state claims saying Market/Signal are unimplemented or Candidate is blocked by unapproved rules**
- [ ] **Step 2: Keep historical detail in `REVIEW_NOTES.md`; ROADMAP top status must match later sections**
- [ ] **Step 3: Move resolved blockers to a clearly labeled closed/history section**
- [ ] **Step 4: Add a test rejecting known stale phrases**

```python
assert "Candidate 阶段因为入选规则尚未批准而 `BLOCKED`" not in readme
```

- [ ] **Step 5: Commit**

```bash
git add README.md docs tests
git commit -m "文档：收敛候选v2当前状态并清理过期阻塞描述"
git push
```

---

### Task 9: Final Backend Gate

- [ ] **Step 1: Run full quality gate**

```bash
PYTHONPATH= uv run --no-sync pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

- [ ] **Step 2: Verify latest GitHub Actions run is `success`**
- [ ] **Step 3: Review for silent optional evidence**

```bash
rg -n "relative_strength_60d.*else|industry_excess_return.*None|vol_ratio.*None" \
  src/astock_lens/market src/astock_lens/pipelines
```

Any production Candidate path that silently downgrades missing required evidence is a blocker.

- [ ] **Step 4: Return Completion Report**

```text
1. task commit SHAs
2. remote HEAD
3. full pytest count
4. ruff / format / mypy
5. GitHub Actions URL + success
6. accepted canonical Candidate v2 date
7. five snapshot kinds present
8. independent validator findings
9. candidate count
10. proof standard astock daily received benchmark + industry evidence
11. proof 5D missing evidence fails closed
12. proof same-date snapshot conflict remains enforced
13. git status --short
```

## Mandatory STOP Gate

Do not begin Web implementation until Task 9 is green.
