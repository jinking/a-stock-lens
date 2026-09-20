# Dividend Data Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land and normalize authoritative dividend-event evidence from neodata so the owner can approve a future TTM dividend-yield definition, without changing the existing `dividend_yield_ttm` factor.

**Architecture:** Add a new raw dataset representing dividend distribution events. Parse only explicit source facts such as cash dividend per 10 shares, status, registration/ex-date and announcement fields. Produce coverage and sample reports. Do not derive a yield or change Dividend Qualification.

**Tech Stack:** Existing NeodataProvider, CSV raw landing conventions, Pydantic models, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-qualified-to-candidate-upgrade-design.md`

## Global Constraints

- No new `dividend_yield_ttm` calculation in this plan.
- No Qualification threshold changes.
- Preserve raw source text.
- Proposal vs implemented dividend must remain distinguishable.
- Do not guess missing dates.
- Do not convert per-10-share dividend to yield.
- Keep point-in-time evidence.
- TDD and frequent commits.

## Review Focus

1. Proposal vs implemented event remains distinguishable.
2. Multiple dividends within 12 months remain separate source events.
3. Missing ex-date remains missing.
4. Currency/unit is explicit.
5. Coverage is based on parsed content, not provider entity metadata.

---

## Locked File Structure

### Create

- `src/astock_lens/data/dividends/models.py`
- `src/astock_lens/data/dividends/normalize.py`
- `src/astock_lens/calibration/dividend_coverage.py`
- `tests/unit/test_dividend_event_normalizer.py`
- `tests/unit/test_dividend_coverage.py`
- `tests/integration/test_dividend_sync_cli.py`
- `docs/decision-packets/2026-09-20-dividend-yield-definition-decision.md`

### Modify

- `src/astock_lens/data/providers/neodata.py`
- existing module that owns `land_neodata_blocks`
- `src/astock_lens/cli/app.py`
- `docs/REMAINING_PRODUCT_BLOCKERS.md`
- `docs/REVIEW_NOTES.md`

### Forbidden

- `configs/factors/dividend_yield_ttm.yaml`
- `configs/qualifications/dividend.yaml`
- TTM dividend-yield implementation
- Candidate publishing

---

### Task 1: Add Fixed Neodata Dividend-History Dataset

**Files:**
- Modify: `src/astock_lens/data/providers/neodata.py`
- Modify: existing neodata provider tests

**Interface:**

Add exactly:

```python
QUERY_TEMPLATES["dividend_history"] = (
    "{names} 历史分红送配 每10股派息 股权登记日 除权日 实施状态"
)
```

- [ ] **Step 1: RED query-template test**

Assert the exact phrase is stable.

- [ ] **Step 2: RED content-coverage test**

Fixture requests two symbols but content contains one; missing symbols must include the absent one.

- [ ] **Step 3: Implement dataset registration**

Add `dividend_history` to symbol-coverage checking only if the fixture proves stock codes occur in content.

- [ ] **Step 4: Run focused provider tests**

- [ ] **Step 5: Commit**

```bash
git add src/astock_lens/data/providers/neodata.py tests
git commit -m "数据：增加分红派息历史固定查询数据集"
git push
```

---

### Task 2: Normalize Explicit Dividend Events

**Files:**
- Create: `src/astock_lens/data/dividends/models.py`
- Create: `src/astock_lens/data/dividends/normalize.py`
- Create: `tests/unit/test_dividend_event_normalizer.py`

**Interface:**

```python
class DividendEvent(DomainRecord):
    symbol: str
    announcement_date: date | None
    registration_date: date | None
    ex_date: date | None
    implementation_status: str
    cash_dividend_per_10_shares: float | None
    currency: str | None
    available_at: datetime
    source_text: str
```

- [ ] **Step 1: RED implemented-event parse**

Parse a fixture with actual cash dividend and ex-date.

- [ ] **Step 2: RED proposal-event parse**

Proposal status must remain the source status and must not be upgraded to implemented.

- [ ] **Step 3: RED missing-date behavior**

Missing dates remain `None`.

- [ ] **Step 4: RED source evidence preservation**

`source_text` keeps the relevant source row/block.

- [ ] **Step 5: Implement parser**

No TTM aggregation, no annualization, no price join.

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/data/dividends tests/unit/test_dividend_event_normalizer.py
git commit -m "归一化：建立分红事件证据模型"
git push
```

---

### Task 3: Add Resumable Dividend-History Sync

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Create: `tests/integration/test_dividend_sync_cli.py`

**Interface:**

```bash
astock sync-dividends   --as-of YYYY-MM-DD   --universe PATH   --max-rounds N   --batch-size N
```

- [ ] **Step 1: RED partial-response resume**

Round 1 returns subset; round 2 requests only still-missing symbols.

- [ ] **Step 2: RED no-progress stop**

Zero newly landed symbols stops further requests and prints remaining gap.

- [ ] **Step 3: Implement through existing `land_neodata_blocks` semantics**

Raw destination:

```text
data/raw/neodata/dividend_history/YYYY-MM-DD.csv
```

Previously landed blocks must survive later rounds.

- [ ] **Step 4: Verify**

```bash
PYTHONPATH= uv run --no-sync pytest tests/integration/test_dividend_sync_cli.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/astock_lens/cli/app.py tests/integration/test_dividend_sync_cli.py
git commit -m "命令：增加研究池分红事件缺口补抓"
git push
```

---

### Task 4: Add Dividend Event Coverage Audit

**Files:**
- Create: `src/astock_lens/calibration/dividend_coverage.py`
- Create: `tests/unit/test_dividend_coverage.py`
- Modify: `src/astock_lens/cli/app.py`

**Interface:**

```bash
astock dividend-coverage   --as-of YYYY-MM-DD   --universe PATH   --output PATH
```

Report:

```text
universe_size
symbols_with_any_event
symbols_with_implemented_cash_event
symbols_with_ex_date
symbols_with_registration_date
event_count
proposal_count
implemented_count
missing_symbols
```

- [ ] **Step 1: RED explicit-denominator test**

Coverage denominator must come from `--universe`.

- [ ] **Step 2: RED status-split test**

Proposal and implemented events counted separately.

- [ ] **Step 3: Implement deterministic report**

JSON + Markdown output.

- [ ] **Step 4: Prove read-only**

Only output path changes.

- [ ] **Step 5: Commit**

```bash
git add src/astock_lens/calibration/dividend_coverage.py         src/astock_lens/cli/app.py         tests/unit/test_dividend_coverage.py
git commit -m "校准：增加分红事件覆盖审计"
git push
```

---

### Task 5: Build Owner Dividend-Yield Definition Packet

**Files:**
- Create: `docs/decision-packets/2026-09-20-dividend-yield-definition-decision.md`
- Modify: `docs/REMAINING_PRODUCT_BLOCKERS.md`
- Modify: `docs/REVIEW_NOTES.md`

- [ ] **Step 1: Run current Research Universe coverage**

Record real denominator and coverage.

- [ ] **Step 2: Include representative cases**

At minimum:
- bank;
- utility;
- energy;
- multiple dividends in 12 months;
- proposal-only;
- missing-date.

- [ ] **Step 3: Present owner choices without selecting**

```text
A. TTM event window:
   ex-date based
   registration-date based
   implementation-date based

B. Proposal handling:
   exclude proposals
   include proposals as explicitly provisional

C. Price denominator:
   as-of close
   ex-date close
   another approved price definition

D. Aggregation:
   sum approved event types within the selected TTM window
```

- [ ] **Step 4: Prove no product rule changed**

Diff-check Dividend factor and qualification config.

- [ ] **Step 5: Commit decision evidence**

```bash
git add docs/decision-packets/2026-09-20-dividend-yield-definition-decision.md         docs/REMAINING_PRODUCT_BLOCKERS.md docs/REVIEW_NOTES.md
git commit -m "决策材料：形成TTM股息率口径数据证据包"
git push
```

---

## Mandatory STOP Gate

STOP after Task 5.

Do not calculate `dividend_yield_ttm`, modify Dividend Qualification, or publish Candidate until the owner approves the definition.

## Required Agent Completion Report

```text
1. task commit SHAs
2. Research Universe denominator
3. symbols with any event
4. symbols with implemented cash event
5. proposal vs implemented counts
6. missing symbols
7. decision packet path
8. proof dividend_yield_ttm code unchanged
9. proof Dividend qualification YAML unchanged
10. git status --short
```
