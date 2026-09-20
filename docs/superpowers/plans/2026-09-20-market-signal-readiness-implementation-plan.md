# Market & Signal Decision Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce reproducible evidence for owner approval of Market Regime, Market Validation, Signal, and Candidate global-readiness semantics without activating any of those product rules.

**Architecture:** Build read-only diagnostic reports from existing normalized bars, FACTOR/STRATEGY snapshots, industry membership, and approved Qualification results. Reports expose distributions and representative cases only; they do not emit `MarketRegime`, `MarketValidation`, `Signal`, or Candidate verdicts.

**Tech Stack:** Existing normalized repository, stored snapshots, Pydantic report models, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-qualified-to-candidate-upgrade-design.md`

## Global Constraints

- Do not instantiate fake `MarketRegime`.
- Do not output `MarketValidation.CONFIRMED/NEUTRAL/CONTRADICTED`.
- Do not output Signal enums.
- Do not publish Candidate.
- Do not modify `BLOCKED_REASONS`.
- Do not wire `RepresentativeCandidatePolicy`.
- Diagnostics may measure only already-defined data.
- Candidate readiness Mode A/B remains an owner decision.

## Review Focus

1. Missing market benchmark evidence remains missing, not RANGE/NEUTRAL.
2. Missing industry evidence remains visible.
3. Diagnostic percentiles never become product thresholds automatically.
4. Qualified stocks with missing technical history remain explicitly missing.
5. Same snapshots/configs produce deterministic reports.

---

## Locked File Structure

### Create

- `src/astock_lens/calibration/market_signal_readiness.py`
- `tests/unit/test_market_signal_readiness.py`
- `tests/integration/test_market_signal_readiness_cli.py`
- `docs/decision-packets/2026-09-20-market-signal-owner-decisions.md`

### Modify

- `src/astock_lens/cli/app.py`
- `docs/ROADMAP.md`
- `docs/REMAINING_PRODUCT_BLOCKERS.md`
- `docs/REVIEW_NOTES.md`

### Forbidden

- removing Market/Signal blockers in `pipelines/daily.py`
- Candidate policy production wiring
- production Market/Signal modules
- Candidate Snapshot

---

### Task 1: Build Existing-Evidence Distribution Report

**Files:**
- Create: `src/astock_lens/calibration/market_signal_readiness.py`
- Create: `tests/unit/test_market_signal_readiness.py`

**Interfaces:**

```python
class MetricDistribution(DomainRecord):
    metric: str
    count: int
    missing: int
    p10: float | None
    p25: float | None
    p50: float | None
    p75: float | None
    p90: float | None

class StrategyTechnicalReadiness(DomainRecord):
    strategy_id: str
    qualified_count: int
    metrics: tuple[MetricDistribution, ...]

class MarketSignalReadinessReport(DomainRecord):
    as_of: datetime
    strategies: tuple[StrategyTechnicalReadiness, ...]
    missing_inputs: tuple[str, ...]
```

Initial allowed existing metrics only:

```text
ret_20d
ret_60d
proximity_52w_high
avg_amount_20d
```

- [ ] **Step 1: RED deterministic quantile test**

Same values in different input order must produce identical p10/p25/p50/p75/p90.

- [ ] **Step 2: RED missing-value test**

NULL/NOT_APPLICABLE/STALE do not become numeric zero.

- [ ] **Step 3: RED qualified-population scope**

Only stocks with at least one `StrategyQualification.qualified=True` for the relevant strategy enter its diagnostic distribution.

- [ ] **Step 4: Implement report builder**

Reuse canonical qualifiers and stored Factor/Strategy results. Do not emit any Market/Signal enum.

- [ ] **Step 5: Verify**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_market_signal_readiness.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/calibration/market_signal_readiness.py         tests/unit/test_market_signal_readiness.py
git commit -m "校准：建立市场与信号规则证据分布报告"
git push
```

---

### Task 2: Add Read-Only CLI

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Create: `tests/integration/test_market_signal_readiness_cli.py`

**Interface:**

```bash
astock calibrate market-signal-readiness   --as-of YYYY-MM-DD   --output-dir PATH
```

- [ ] **Step 1: RED read-only test**

Fingerprint Snapshot/Watchlist/Job roots before and after.

- [ ] **Step 2: RED missing snapshot test**

Missing FACTOR or STRATEGY snapshot exits non-zero with the missing kind named.

- [ ] **Step 3: RED invalid qualification-config test**

Fail loudly; never generate a normal report with empty qualified populations.

- [ ] **Step 4: Implement**

Read:
- stored FACTOR Snapshot;
- stored STRATEGY Snapshot;
- canonical approved qualifiers.

Write only:

```text
market-signal-readiness-YYYY-MM-DD.json
market-signal-readiness-YYYY-MM-DD.md
```

- [ ] **Step 5: Verify**

```bash
PYTHONPATH= uv run --no-sync pytest   tests/integration/test_market_signal_readiness_cli.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/cli/app.py         tests/integration/test_market_signal_readiness_cli.py
git commit -m "命令：增加市场与信号规则只读准备报告"
git push
```

---

### Task 3: Add Representative Case Sampling

**Files:**
- Modify: `src/astock_lens/calibration/market_signal_readiness.py`
- Modify: `tests/unit/test_market_signal_readiness.py`

For each strategy sample deterministic symbols from:

```text
highest ret_20d
lowest ret_20d
highest ret_60d
lowest ret_60d
closest to 52w high
farthest from 52w high
highest avg_amount_20d
lowest avg_amount_20d within Research Universe
```

- [ ] **Step 1: RED deterministic sampling**

Ties resolve by symbol ascending.

- [ ] **Step 2: Include raw value + DataStatus**

Every sample carries the source factor status/value.

- [ ] **Step 3: Assert vocabulary boundary**

Report must not contain:

```text
CONFIRMED
NEUTRAL
CONTRADICTED
BREAKOUT
PULLBACK
TREND_CONTINUE
TREND_WEAKEN
BREAKDOWN
```

except inside an explicit “future vocabulary requiring approval” documentation section, never as a verdict field.

- [ ] **Step 4: Commit**

```bash
git add src/astock_lens/calibration/market_signal_readiness.py         tests/unit/test_market_signal_readiness.py
git commit -m "校准：补充市场信号边界代表样本"
git push
```

---

### Task 4: Produce Owner Decision Packet

**Files:**
- Create: `docs/decision-packets/2026-09-20-market-signal-owner-decisions.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REMAINING_PRODUCT_BLOCKERS.md`
- Modify: `docs/REVIEW_NOTES.md`

- [ ] **Step 1: Run real 2026-09-19 report**

Record actual qualified population and technical-factor coverage per strategy.

- [ ] **Step 2: Market Regime decision section**

List available evidence and missing evidence.

Present rule families only:

```text
R1: broad-market trend + medium-term return
R2: broad-market trend + breadth + volatility
```

If breadth/volatility data does not exist, mark `MISSING`. Do not invent them.

- [ ] **Step 3: Market Validation decision section**

For desired evidence categories:

```text
individual trend
industry trend
relative strength
price/volume
liquidity
```

mark:

```text
AVAILABLE
PARTIAL
MISSING
```

and identify exact current source/factor when available.

- [ ] **Step 4: Signal input matrix**

For each future signal vocabulary, list the measurable inputs that would be required, without thresholds.

Example:

```text
BREAKOUT:
- breakout reference level
- crossing condition
- optional volume confirmation
```

- [ ] **Step 5: Candidate readiness semantics**

Present both unresolved modes:

```text
Mode A — per-strategy degraded
Mode B — global all-core-strategies readiness
```

Explain the current Dividend data gap impact under each. Do not choose one.

- [ ] **Step 6: Update Roadmap**

Set P3 state to:

```text
DECISION EVIDENCE READY — OWNER APPROVAL REQUIRED
```

only if the packet is complete. Do not mark P3 implemented.

- [ ] **Step 7: Commit**

```bash
git add docs/decision-packets/2026-09-20-market-signal-owner-decisions.md         docs/ROADMAP.md docs/REMAINING_PRODUCT_BLOCKERS.md docs/REVIEW_NOTES.md
git commit -m "决策材料：形成市场验证与信号规则审批包"
git push
```

---

## Mandatory OWNER STOP Gate

After Task 4 STOP.

Do not:
- implement Market Regime;
- implement Market Validation;
- implement Signal;
- remove P3 blockers;
- wire CandidatePolicy;
- publish Candidate.

A new implementation plan is required after the owner approves the actual inputs/thresholds and Candidate readiness mode.

## Required Agent Completion Report

```text
1. task commit SHAs
2. report JSON/Markdown paths
3. qualified population per strategy
4. technical metric coverage per strategy
5. missing Market Regime inputs
6. Market Validation input availability matrix
7. Signal input matrix
8. Candidate readiness Mode A/B comparison
9. decision packet path
10. proof no MarketRegime/MarketValidation/Signal verdict produced
11. proof no CANDIDATE snapshot written
12. git status --short
```
