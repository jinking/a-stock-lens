# Candidate Qualification & Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Candidate Qualification architecture and calibration tooling without inventing any unapproved absolute quality thresholds; production Candidate publishing must remain BLOCKED until those thresholds and the upstream Market/Signal rules are approved.

**Architecture:** Insert a dedicated `StrategyQualification` layer between `StrategyResult` and `CandidatePolicy`. Each strategy owns an independent qualifier class; qualifiers combine the approved Top-10% percentile gate with a separately injected absolute-quality rule. `CandidatePolicy` becomes a cross-sectional selection policy that enforces per-strategy soft representation, deduplication, deterministic ordering, Market Validation veto, and a hard cap of 50 without creating a cross-strategy global score. A separate calibration module produces evidence for the owner to approve the still-deferred absolute rules.

**Tech Stack:** Python >=3.12, Pydantic 2.x, Typer, pytest, Ruff, mypy, existing JSON/DuckDB snapshot abstractions.

**Spec:** `docs/superpowers/specs/2026-09-17-candidate-qualification-design.md`

## Global Constraints

- Candidate is a research object, never an investment recommendation.
- Daily target range is 20–50, but only 50 is a hard limit; never lower quality standards to reach 20.
- Each enabled/runnable strategy has a soft reserve of 3 qualified symbols.
- Strategy Qualification requires both an approved absolute rule and `rank_percentile >= 0.90`.
- `MarketValidation.CONTRADICTED` vetoes Candidate selection.
- `MarketValidation.CONFIRMED` and `NEUTRAL` are eligible for selection; `None` is incomplete input, not `NEUTRAL`.
- Signal does not determine Candidate eligibility; `None` is incomplete input, not `NO_SIGNAL`.
- One symbol produces at most one Candidate even if multiple strategies qualify it.
- Global ordering is lexicographic: best single-strategy percentile, number of qualified strategies, Market Validation, then an approved Signal priority when one exists; symbol is the deterministic final tie-breaker.
- Do not sum, average, normalize, or weight scores from different strategies into a global score.
- Do not invent Value/Growth/GARP/Quality/Dividend/Momentum absolute thresholds in this plan.
- Do not implement Market Regime, Market Validation detectors, or Signal detectors in this plan.
- Production Candidate publishing stays BLOCKED until absolute rules and upstream Market/Signal implementations are available.
- Preserve the canonical rule that `astock daily` is the only formal Snapshot writer.
- Follow TDD for every behavioral change: failing test → minimal implementation → passing test → focused commit.
- After every task, inspect `git diff --check`; after the final task run the complete verification suite.
- Commit messages and project documentation remain Chinese.

---

## File Structure Locked by This Plan

Create:

- `src/astock_lens/qualifications/__init__.py` — public qualification exports.
- `src/astock_lens/qualifications/models.py` — `StrategyQualification`, absolute-rule verdict models.
- `src/astock_lens/qualifications/contracts.py` — `StrategyQualifier`, `AbsoluteQualificationRule` protocols and explicit “not configured” error.
- `src/astock_lens/qualifications/common.py` — shared Top-10% check and result assembly helper only; no strategy-specific thresholds.
- `src/astock_lens/qualifications/value.py`
- `src/astock_lens/qualifications/growth.py`
- `src/astock_lens/qualifications/garp.py`
- `src/astock_lens/qualifications/quality.py`
- `src/astock_lens/qualifications/dividend.py`
- `src/astock_lens/qualifications/momentum.py` — six independent qualifier classes.
- `src/astock_lens/qualifications/registry.py` — explicit strategy-id → qualifier builder mapping; refuses missing approved absolute rules.
- `src/astock_lens/calibration/__init__.py`
- `src/astock_lens/calibration/candidate_report.py` — calibration statistics/data model.
- `src/astock_lens/calibration/render.py` — deterministic Markdown/JSON rendering.
- `tests/unit/test_strategy_qualification.py`
- `tests/unit/test_candidate_selection_policy.py`
- `tests/unit/test_candidate_evidence.py`
- `tests/unit/test_candidate_calibration.py`
- `tests/integration/test_candidate_qualification_pipeline.py`
- `tests/integration/test_candidate_calibration_cli.py`

Modify:

- `src/astock_lens/candidates/policy.py` — replace per-symbol `qualify()` policy with cross-sectional `select()`.
- `src/astock_lens/candidates/models.py` — persist qualification evidence and policy version.
- `src/astock_lens/candidates/builder.py` — assemble only selected qualified evidence.
- `src/astock_lens/candidates/routing.py` — keep WATCH/IGNORE translation semantics, adapted to selection result.
- `src/astock_lens/domain/models.py` — add qualification/policy lineage fields.
- `src/astock_lens/pipelines/stages.py` — add pure qualification step and cross-sectional candidate selection.
- `src/astock_lens/pipelines/daily.py` — expose missing qualification rules as a BUILD_CANDIDATES blocking reason.
- `src/astock_lens/cli/app.py` — add calibration CLI surface only; do not enable production Candidate publishing.
- `tests/unit/test_candidate_policy.py` — migrate old per-symbol fake policies to the cross-sectional contract.
- `tests/integration/test_daily_pipeline.py` — assert qualification/upstream blocking semantics.
- `tests/artifacts/validator.py`
- `tests/artifacts/test_validator.py` — independent Candidate qualification/policy checks.
- `docs/ROADMAP.md`
- `docs/REVIEW_NOTES.md`
- `.workbuddy/memory/2026-09-17.md` or the repository's active memory file for this date.

Do **not** create production files under `configs/qualifications/` yet. Those files would contain owner-approved absolute rules; this plan deliberately stops before inventing them.

---

### Task 1: Land the Approved Design Spec and Pin the New Contract With Failing Tests

**Files:**
- Create: `docs/superpowers/specs/2026-09-17-candidate-qualification-design.md`
- Create: `tests/unit/test_candidate_selection_policy.py`
- Create: `tests/unit/test_strategy_qualification.py`
- Modify: `docs/ROADMAP.md`

**Interfaces:**
- Consumes: current `StrategyResult`, `MarketValidation`, `Signal`, `Candidate`.
- Produces: executable tests naming the future interfaces `StrategyQualification`, `CandidateEvidence`, `CandidateSelection`, `CandidatePolicy.select()`.

- [ ] **Step 1: Copy the approved spec byte-for-byte into the repository**

Use the approved artifact supplied with this plan as:

```text
docs/superpowers/specs/2026-09-17-candidate-qualification-design.md
```

Do not rewrite thresholds or terminology while copying.

- [ ] **Step 2: Write failing tests for the qualification contract**

Create tests that import the not-yet-existing models and establish these behaviors:

```python
def test_percentile_below_top_ten_percent_cannot_qualify() -> None:
    result = strategy_result(rank_percentile=0.899999)
    qualification = qualifier_with_absolute_pass().qualify(result)
    assert qualification.percentile_pass is False
    assert qualification.absolute_pass is True
    assert qualification.qualified is False


def test_percentile_and_absolute_gate_must_both_pass() -> None:
    result = strategy_result(rank_percentile=0.90)
    qualification = qualifier_with_absolute_pass().qualify(result)
    assert qualification.percentile_pass is True
    assert qualification.absolute_pass is True
    assert qualification.qualified is True
```

Also pin `qualification_version` as non-empty.

- [ ] **Step 3: Write failing tests for cross-sectional selection**

Use synthetic `CandidateEvidence` and assert:

```python
def test_selection_never_exceeds_fifty_symbols() -> None:
    selected = policy().select(make_evidence(80))
    assert len(selected) == 50


def test_selection_does_not_fill_to_twenty() -> None:
    selected = policy().select(make_evidence(12))
    assert len(selected) == 12
```

Add separate tests for `CONTRADICTED` veto and symbol uniqueness.

- [ ] **Step 4: Run only the new tests and verify collection/import failure**

Run:

```bash
uv run pytest tests/unit/test_strategy_qualification.py tests/unit/test_candidate_selection_policy.py -v
```

Expected: FAIL during import because the new qualification/evidence/selection interfaces do not exist.

- [ ] **Step 5: Update ROADMAP decision state**

Change Candidate Qualification from “owner decision unresolved” to “architecture approved; absolute per-strategy thresholds still blocked pending calibration.” Preserve the separate Growth/Dividend/PEG owner decisions.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-09-17-candidate-qualification-design.md \
        docs/ROADMAP.md \
        tests/unit/test_strategy_qualification.py \
        tests/unit/test_candidate_selection_policy.py
git commit -m "测试：钉住候选资格与横截面选择契约"
git push
```

---

### Task 2: Introduce StrategyQualification as a First-Class Domain Boundary

**Files:**
- Create: `src/astock_lens/qualifications/__init__.py`
- Create: `src/astock_lens/qualifications/models.py`
- Create: `src/astock_lens/qualifications/contracts.py`
- Create: `src/astock_lens/qualifications/common.py`
- Modify: `src/astock_lens/domain/models.py`
- Test: `tests/unit/test_strategy_qualification.py`

**Interfaces:**
- Consumes: `StrategyResult`.
- Produces:
  - `AbsoluteQualificationVerdict(passed: bool, reasons: tuple[str, ...], risks: tuple[str, ...])`
  - `StrategyQualification(...)`
  - `AbsoluteQualificationRule.evaluate(result: StrategyResult) -> AbsoluteQualificationVerdict`
  - `StrategyQualifier.qualify(result: StrategyResult) -> StrategyQualification`
  - `QualificationRuleNotConfigured`

- [ ] **Step 1: Implement the immutable qualification result models**

Required model shape:

```python
class StrategyQualification(DomainRecord):
    symbol: str
    strategy_id: str
    strategy_version: str
    qualification_version: str
    qualified: bool
    percentile_pass: bool
    absolute_pass: bool
    rank_percentile: float
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
```

Reject a missing `rank_percentile`; qualification cannot silently turn an unranked strategy result into a research verdict.

- [ ] **Step 2: Implement protocols**

```python
class AbsoluteQualificationRule(Protocol):
    version: str

    def evaluate(
        self, result: StrategyResult
    ) -> AbsoluteQualificationVerdict: ...


class StrategyQualifier(Protocol):
    strategy_id: str
    qualification_version: str

    def qualify(self, result: StrategyResult) -> StrategyQualification: ...
```

Create `QualificationRuleNotConfigured(RuntimeError)` for missing owner-approved absolute rules.

- [ ] **Step 3: Implement the shared percentile helper**

Only this approved common rule belongs in `common.py`:

```python
TOP_TEN_PERCENT_FLOOR = 0.90

def passes_percentile(result: StrategyResult) -> bool:
    percentile = result.rank_percentile
    if percentile is None:
        raise ValueError("rank_percentile is required for qualification")
    return percentile >= TOP_TEN_PERCENT_FLOOR
```

Do not put ROE, PE, growth, payout, PEG, or momentum thresholds here.

- [ ] **Step 4: Extend lineage**

Add to `SnapshotLineage`:

```python
qualification_version: str | None = None
candidate_policy_version: str | None = None
```

Do not change the existing factor/strategy version behavior in this task.

- [ ] **Step 5: Run qualification tests**

```bash
uv run pytest tests/unit/test_strategy_qualification.py -v
uv run mypy src/astock_lens/qualifications src/astock_lens/domain/models.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/qualifications src/astock_lens/domain/models.py \
        tests/unit/test_strategy_qualification.py
git commit -m "候选：引入独立策略资格判定模型"
git push
```

---

### Task 3: Add Six Independent Qualifier Classes Without Inventing Absolute Rules

**Files:**
- Create: `src/astock_lens/qualifications/value.py`
- Create: `src/astock_lens/qualifications/growth.py`
- Create: `src/astock_lens/qualifications/garp.py`
- Create: `src/astock_lens/qualifications/quality.py`
- Create: `src/astock_lens/qualifications/dividend.py`
- Create: `src/astock_lens/qualifications/momentum.py`
- Create: `src/astock_lens/qualifications/registry.py`
- Modify: `src/astock_lens/qualifications/common.py`
- Test: `tests/unit/test_strategy_qualification.py`

**Interfaces:**
- Consumes: one `AbsoluteQualificationRule` injected per strategy.
- Produces: six concrete `StrategyQualifier` implementations and `build_qualifiers(absolute_rules)`.

- [ ] **Step 1: Implement one shared assembly helper, not a generic strategy engine**

`common.py` may expose:

```python
def build_qualification(
    *,
    result: StrategyResult,
    expected_strategy_id: str,
    qualification_version: str,
    absolute_rule: AbsoluteQualificationRule,
) -> StrategyQualification:
    ...
```

It must:
- reject a mismatched `strategy_id`;
- apply the Top-10% check;
- evaluate the injected absolute rule;
- set `qualified = percentile_pass and absolute_pass`;
- preserve explicit reasons/risks.

- [ ] **Step 2: Implement six explicit qualifier classes**

Example shape:

```python
class ValueQualifier:
    strategy_id = "value"

    def __init__(
        self,
        *,
        absolute_rule: AbsoluteQualificationRule,
        qualification_version: str,
    ) -> None:
        self.absolute_rule = absolute_rule
        self.qualification_version = qualification_version

    def qualify(self, result: StrategyResult) -> StrategyQualification:
        return build_qualification(
            result=result,
            expected_strategy_id=self.strategy_id,
            qualification_version=self.qualification_version,
            absolute_rule=self.absolute_rule,
        )
```

Repeat as separate concrete classes for `growth`, `garp`, `quality`, `dividend`, and `momentum`. Do not alias all six names to one generic class.

- [ ] **Step 3: Implement an explicit registry**

Use an explicit mapping from strategy id to qualifier class. If an enabled strategy has no injected approved absolute rule, raise `QualificationRuleNotConfigured` with the strategy id.

Do not load non-existent production threshold YAML.

- [ ] **Step 4: Add tests proving strategy independence**

At minimum:
- each qualifier rejects a StrategyResult for another strategy;
- each qualifier carries its own `qualification_version`;
- a fake absolute rule can make the same 0.95 percentile result pass or fail without changing the percentile result;
- missing absolute rule fails loudly.

- [ ] **Step 5: Run focused tests**

```bash
uv run pytest tests/unit/test_strategy_qualification.py -v
uv run ruff check src/astock_lens/qualifications tests/unit/test_strategy_qualification.py
uv run mypy src/astock_lens/qualifications
```

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/qualifications tests/unit/test_strategy_qualification.py
git commit -m "策略：建立六类独立候选资格判定器"
git push
```

---

### Task 4: Replace Per-Symbol CandidatePolicy With Cross-Sectional Selection

**Files:**
- Modify: `src/astock_lens/candidates/policy.py`
- Create: `tests/unit/test_candidate_evidence.py`
- Modify: `tests/unit/test_candidate_selection_policy.py`
- Modify: `tests/unit/test_candidate_policy.py`

**Interfaces:**
- Consumes: `StrategyQualification`, `StrategyResult`, `MarketValidation`, `Signal`.
- Produces:
  - `CandidateEvidence`
  - `CandidateSelection`
  - `CandidatePolicy.select(evidence: Sequence[CandidateEvidence]) -> tuple[CandidateSelection, ...]`
  - `RepresentativeCandidatePolicy(version="v1", soft_reserve_per_strategy=3, max_candidates=50)`

- [ ] **Step 1: Define evidence and selection models**

Required shape:

```python
class CandidateEvidence(DomainRecord):
    symbol: str
    strategy_results: tuple[StrategyResult, ...]
    strategy_qualifications: tuple[StrategyQualification, ...]
    market_validation: MarketValidation | None
    signal: Signal | None


class CandidateSelection(DomainRecord):
    symbol: str
    policy_version: str
    reasons: tuple[str, ...] = ()
```

Validation rules:
- every contained StrategyResult/Qualification must use the same symbol;
- at least one qualification must have `qualified=True` for evidence passed to selection;
- `market_validation=None` and `signal=None` remain representable so the policy can reject incomplete evidence explicitly.

- [ ] **Step 2: Replace protocol**

```python
class CandidatePolicy(Protocol):
    version: str

    def select(
        self, evidence: Sequence[CandidateEvidence]
    ) -> tuple[CandidateSelection, ...]: ...
```

Delete the old per-symbol `qualify(strategy_results=..., market_validation=..., signal=...)` contract after tests have been migrated.

- [ ] **Step 3: Implement veto and deterministic priority helpers**

Priority semantics:

```text
best qualified rank_percentile DESC
qualified strategy count DESC
MarketValidation.CONFIRMED before NEUTRAL
symbol ASC
```

Signal is deliberately absent from the active sort key until an approved signal-priority map exists.

If any evidence has `market_validation is None` or `signal is None`, raise an explicit `CandidateEvidenceIncomplete`. Do not reinterpret either value.

`CONTRADICTED` evidence is filtered out before quota selection.

- [ ] **Step 4: Implement soft representation**

For every strategy id represented by qualified evidence:
- rank that strategy's qualified symbols by that strategy's own `rank_percentile` descending, symbol ascending;
- take at most 3;
- union symbols across strategies;
- deduplicate by symbol.

A symbol selected for multiple strategies still appears once and may satisfy representation for multiple strategies.

- [ ] **Step 5: Implement global fill and 50 hard cap**

After the soft-reserve union, sort remaining eligible symbols by the lexicographic global priority and append until reaching 50 or exhausting the pool.

There is no code path that relaxes qualification to reach 20.

- [ ] **Step 6: Pin all selection behaviors**

Tests must include:
- 80 eligible → exactly 50;
- 12 eligible → exactly 12;
- 3-or-fewer per strategy soft representation;
- strategy with only 1 qualified item contributes 1, not 3;
- one multi-strategy symbol appears once;
- best single-strategy percentile beats a lower-ranked symbol with more strategy matches;
- equal best percentile uses qualified strategy count as second key;
- equal first two keys use CONFIRMED before NEUTRAL;
- final ties are symbol deterministic;
- CONTRADICTED never selected;
- `None` market/signal raises incomplete evidence.

- [ ] **Step 7: Run focused tests and commit**

```bash
uv run pytest tests/unit/test_candidate_evidence.py \
              tests/unit/test_candidate_selection_policy.py \
              tests/unit/test_candidate_policy.py -v
uv run ruff check src/astock_lens/candidates tests/unit/test_candidate*.py
uv run mypy src/astock_lens/candidates
git add src/astock_lens/candidates tests/unit/test_candidate*
git commit -m "候选：实现横截面代表性选择策略"
git push
```

---

### Task 5: Persist Qualification Evidence and Policy Version in Candidate

**Files:**
- Modify: `src/astock_lens/candidates/models.py`
- Modify: `src/astock_lens/candidates/builder.py`
- Modify: `src/astock_lens/candidates/routing.py`
- Modify: `tests/unit/test_candidate_policy.py`
- Test: `tests/unit/test_candidate_evidence.py`

**Interfaces:**
- Consumes: one `CandidateSelection` and its matching `CandidateEvidence`.
- Produces: Candidate containing selected strategy evidence, qualification evidence, market/signal evidence, and policy lineage.

- [ ] **Step 1: Extend Candidate**

Add:

```python
strategy_qualifications: tuple[StrategyQualification, ...] = ()
candidate_policy_version: str
```

Candidate must retain only StrategyResults corresponding to `qualified=True` qualifications, not every merely eligible StrategyResult.

- [ ] **Step 2: Change CandidateBuilder signature**

Use:

```python
def build(
    self,
    *,
    evidence: CandidateEvidence,
    selection: CandidateSelection,
    as_of: datetime,
    lineage: SnapshotLineage,
) -> Candidate:
    ...
```

The builder:
- confirms `evidence.symbol == selection.symbol`;
- keeps all qualified strategy results/qualifications for the selected symbol;
- stores `market_validation` and `signal`;
- stores `selection.policy_version`;
- sets lineage `qualification_version` from the participating qualification versions and `candidate_policy_version` from the selection;
- assembles explanations but makes no selection decision.

- [ ] **Step 3: Keep routing semantic**

Selected Candidate → `NextAction.WATCH`.

Do not introduce `DEEP_RESEARCH` or `TRACK_SIGNAL` triggers.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_candidate_policy.py tests/unit/test_candidate_evidence.py -v
```

Assert a Candidate can be traced to:
- at least one qualified StrategyQualification;
- matching StrategyResult;
- qualification version;
- policy version;
- non-None Market Validation and Signal.

- [ ] **Step 5: Commit**

```bash
git add src/astock_lens/candidates tests/unit/test_candidate_policy.py \
        tests/unit/test_candidate_evidence.py src/astock_lens/domain/models.py
git commit -m "候选：持久化资格证据与策略版本"
git push
```

---

### Task 6: Rewire Pipeline Stages While Keeping Production Candidate BLOCKED

**Files:**
- Modify: `src/astock_lens/pipelines/stages.py`
- Modify: `src/astock_lens/pipelines/daily.py`
- Create: `tests/integration/test_candidate_qualification_pipeline.py`
- Modify: `tests/integration/test_daily_pipeline.py`

**Interfaces:**
- Consumes: strategy results, a mapping of strategy qualifiers, per-symbol market validation, per-symbol signal, cross-sectional CandidatePolicy.
- Produces:
  - pure `qualification_stage(...) -> tuple[StrategyQualification, ...]`
  - cross-sectional `candidate_stage(...) -> tuple[Candidate, ...]`

- [ ] **Step 1: Add a pure qualification helper**

Required signature:

```python
def qualification_stage(
    *,
    strategy_results: Sequence[StrategyResult],
    qualifiers: Mapping[str, StrategyQualifier],
) -> tuple[StrategyQualification, ...]:
    ...
```

Behavior:
- only qualifying strategy results with `eligible=True` are evaluated;
- every eligible strategy id must have a configured qualifier;
- missing qualifier raises `QualificationRuleNotConfigured`;
- no candidate objects are created here.

- [ ] **Step 2: Rewrite candidate_stage around cross-sectional evidence**

Required inputs:

```python
def candidate_stage(
    *,
    strategy_results: Sequence[StrategyResult],
    qualifications: Sequence[StrategyQualification],
    market_validation_by_symbol: Mapping[str, MarketValidation],
    signal_by_symbol: Mapping[str, Signal],
    lineage: SnapshotLineage,
    as_of: datetime,
    policy: CandidatePolicy | None,
) -> tuple[Candidate, ...]:
    ...
```

It must:
- fail clearly when policy is missing;
- build one `CandidateEvidence` per symbol with at least one qualified StrategyQualification;
- fail incomplete evidence instead of synthesizing NEUTRAL/NO_SIGNAL;
- call `policy.select(...)` once for the whole cross-section;
- build candidates only for returned selections.

- [ ] **Step 3: Extend daily context with qualifiers but do not fake upstream market/signal output**

Add a qualifier collection/config input to `run_daily`.

`BUILD_CANDIDATES` remains BLOCKED when:
- Market Regime/Market Validation/Signal upstream is still unimplemented;
- qualification rules are not configured;
- CandidatePolicy is not configured.

The job manifest must list all applicable reasons, not only the first one.

- [ ] **Step 4: Write integration tests**

Pin:
- no approved absolute rules → BUILD_CANDIDATES BLOCKED;
- no Market Validation implementation → BLOCKED;
- no Signal implementation → BLOCKED;
- an isolated test that directly calls `candidate_stage` with complete synthetic market/signal evidence can produce candidates;
- `Signal.NO_SIGNAL` does not disqualify a fully qualified symbol;
- `MarketValidation.CONTRADICTED` does.

Do not enable formal Candidate snapshots in `astock daily` in this task because the real upstream modules remain blocked.

- [ ] **Step 5: Run integration tests**

```bash
uv run pytest tests/integration/test_candidate_qualification_pipeline.py \
              tests/integration/test_daily_pipeline.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/pipelines tests/integration/test_candidate_qualification_pipeline.py \
        tests/integration/test_daily_pipeline.py
git commit -m "管线：接入策略资格层并保持候选发布阻塞"
git push
```

---

### Task 7: Build the Calibration Report Engine

**Files:**
- Create: `src/astock_lens/calibration/__init__.py`
- Create: `src/astock_lens/calibration/candidate_report.py`
- Create: `src/astock_lens/calibration/render.py`
- Create: `tests/unit/test_candidate_calibration.py`

**Interfaces:**
- Consumes:
  - `Sequence[StrategyResult]`
  - `Sequence[FactorResult]`
  - mandatory `Mapping[str, str]` industry mapping
- Produces:
  - `CandidateCalibrationReport`
  - deterministic Markdown and JSON rendering.

- [ ] **Step 1: Define report models**

At minimum:

```python
class StrategyCalibration(DomainRecord):
    strategy_id: str
    evaluable_count: int
    ranked_count: int
    percentile_boundary_90: float | None
    top_symbols: tuple[str, ...]
    boundary_above_symbols: tuple[str, ...]
    boundary_below_symbols: tuple[str, ...]
    industry_counts: tuple[tuple[str, int], ...]
    overlap_counts: tuple[tuple[str, int], ...]


class CandidateCalibrationReport(DomainRecord):
    as_of: datetime
    warning: str
    strategies: tuple[StrategyCalibration, ...]
```

The warning value must be exactly prominent in rendered output:

```text
CALIBRATION ONLY — NOT APPROVED PRODUCT RULE
```

- [ ] **Step 2: Compute distribution statistics**

For each strategy:
- evaluable count;
- ranked count;
- score quantiles;
- actual Top-10% membership and boundary;
- top samples;
- samples immediately above and below the 0.90 boundary;
- industry counts;
- pairwise overlap with other strategies.

Use deterministic sorting.

- [ ] **Step 3: Surface known factor anomalies**

The report must explicitly summarize available distributions/outliers for:

```text
net_profit_parent_yoy
dividend_payout_ttm
peg
```

If a named factor is not present in the input, say “not available in this calibration input”; do not fabricate zeroes.

Also summarize DataStatus counts so missing/stale/source-error populations are visible.

- [ ] **Step 4: Add sensitivity table**

Calibration-only percentile scenarios:

```text
0.80
0.85
0.90
0.95
```

Report the number of ranked results above each cutoff per strategy. These are evidence only and must never write production config.

- [ ] **Step 5: Require industry coverage**

The report builder must reject an empty industry mapping. It must also report industry coverage ratio and unknown-symbol count.

This prevents a “complete” calibration report that silently omits the approved industry-concentration evidence.

- [ ] **Step 6: Test deterministic rendering**

Given the same inputs in different order, JSON/Markdown output must be byte-for-byte stable.

- [ ] **Step 7: Run tests and commit**

```bash
uv run pytest tests/unit/test_candidate_calibration.py -v
uv run ruff check src/astock_lens/calibration tests/unit/test_candidate_calibration.py
uv run mypy src/astock_lens/calibration
git add src/astock_lens/calibration tests/unit/test_candidate_calibration.py
git commit -m "校准：建立候选资格全市场证据报告"
git push
```

---

### Task 8: Add a Calibration CLI That Cannot Mutate Production State

**Files:**
- Modify: `src/astock_lens/cli/app.py`
- Create: `tests/integration/test_candidate_calibration_cli.py`

**Interfaces:**
- Consumes: canonical non-persistent `run_analysis()` output plus an explicit industry-map CSV.
- Produces: calibration `.md` and `.json` files only.

- [ ] **Step 1: Add a Typer group**

Add:

```text
astock calibrate candidates
```

Required options:

```text
--as-of YYYY-MM-DD
--industry-map PATH
--output-dir PATH
```

Industry CSV contract:

```csv
symbol,industry
600000.SH,银行
...
```

Missing/duplicate symbol rows are errors.

- [ ] **Step 2: Reuse the non-persistent analysis chain**

The command must use the existing analysis path that computes factor/strategy results without formal Snapshot writes.

It must not call `run_daily`, `SnapshotStore.write`, Watchlist mutation, or research adapters.

- [ ] **Step 3: Write exactly two report artifacts**

Example paths:

```text
<output-dir>/2026-09-17-candidate-calibration.json
<output-dir>/2026-09-17-candidate-calibration.md
```

Both must contain the calibration-only warning.

- [ ] **Step 4: Pin “no production mutation”**

The integration test must place sentinels around:
- snapshot root;
- watchlist root;
- job root.

After the command, only calibration output files may be new/changed.

- [ ] **Step 5: Run the CLI test**

```bash
uv run pytest tests/integration/test_candidate_calibration_cli.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/astock_lens/cli/app.py tests/integration/test_candidate_calibration_cli.py
git commit -m "命令：增加只读候选资格校准报告"
git push
```

---

### Task 9: Upgrade the Independent Artifact Validator and Finalize Documentation

**Files:**
- Modify: `tests/artifacts/validator.py`
- Modify: `tests/artifacts/test_validator.py`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REVIEW_NOTES.md`
- Modify: `.workbuddy/memory/2026-09-17.md` or current memory file

**Interfaces:**
- Consumes: serialized Candidate records only; validator must continue importing zero production code.
- Produces: independent findings for qualification/policy integrity.

- [ ] **Step 1: Extend Candidate required fields in the independent validator**

Require Candidate artifacts to include:
- `strategy_qualifications`;
- `candidate_policy_version`;
- `market_validation`;
- `signal`.

Validate:
- at least one cited qualification has `qualified == true`;
- every cited qualified strategy has a matching cited StrategyResult;
- no Candidate has `market_validation == "CONTRADICTED"`;
- qualification and policy versions are non-empty;
- symbols are unique within one Candidate snapshot;
- Candidate count is <= 50.

Do not import enums/models from `astock_lens`.

- [ ] **Step 2: Extend cross-snapshot validation**

Candidate → qualified StrategyResult → Factor citation must remain resolvable.

Do not weaken the existing point-in-time checks.

- [ ] **Step 3: Document the actual end state**

`docs/ROADMAP.md` must distinguish:
- **approved architecture**: Top 10%, soft reserve 3, max 50, no min-fill, Market Validation veto, no global score;
- **implemented infrastructure**: qualification models, selection policy, calibration command;
- **still blocked**: six absolute quality rules, Market Regime/Validation/Signal implementations.

`docs/REVIEW_NOTES.md` records why Candidate remains BLOCKED after this plan: this is intentional product safety, not unfinished wiring.

- [ ] **Step 4: Run artifact tests**

```bash
uv run pytest tests/artifacts -v
```

- [ ] **Step 5: Run complete repository verification**

Run from a clean working tree except for intended changes:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

All must exit 0.

- [ ] **Step 6: Run CLI smoke tests**

At minimum:

```bash
uv run astock --help
uv run astock calibrate --help
uv run astock calibrate candidates --help
```

Then run one fixture-based calibration command and verify:
- two calibration report files are produced;
- no Snapshot/Watchlist/Job state is mutated.

- [ ] **Step 7: Commit and push**

```bash
git add tests/artifacts docs/ROADMAP.md docs/REVIEW_NOTES.md .workbuddy/memory
git commit -m "审计：完成候选资格架构与校准阶段验证"
git push
```

---

## Execution Stop Gate

This plan **must stop here**.

Do not create real production files such as:

```text
configs/qualifications/value.yaml
configs/qualifications/growth.yaml
configs/qualifications/garp.yaml
configs/qualifications/quality.yaml
configs/qualifications/dividend.yaml
configs/qualifications/momentum.yaml
```

until the owner reviews a real full-market Calibration Report and explicitly approves the six absolute-rule definitions.

The next owner decision packet must show, per strategy:

- full-market eligible/ranked counts;
- Top-10% boundary and samples immediately above/below it;
- main factor distributions;
- Growth/Dividend/PEG anomaly samples;
- industry concentration;
- cross-strategy overlap;
- sensitivity counts;
- proposed absolute-rule alternatives with projected Candidate counts.

The agent may recommend threshold options in that report, but may not select one or commit it as production configuration.

---

## Final Completion Report Required From the Agent

The agent must return evidence, not a prose claim. Report:

```text
1. Task 1–9 commit SHAs
2. GitHub push confirmation / remote HEAD
3. Actual pytest result
4. Actual ruff check result
5. Actual ruff format --check result
6. Actual mypy result
7. CandidatePolicy active settings:
   - percentile floor = 0.90
   - soft reserve = 3
   - hard max = 50
   - no hard minimum
8. Proof that cross-strategy global_score does not exist
9. Proof that astock daily still BLOCKS production Candidate publishing
10. Calibration report output paths
11. Snapshot/watchlist/job roots unchanged by calibration CLI
12. Remaining owner decisions:
    - six absolute qualification rules
    - Market Regime thresholds
    - Market Validation thresholds
    - Signal thresholds / Signal priority
13. Any plan deviation, with reason and exact commit
14. `git status --short` output proving the worktree is clean
```

Do not claim completion if any verification command was not actually run.

---

## Plan Self-Review

**Spec coverage:** All approved semantics are assigned to explicit tasks: qualification boundary (Tasks 2–3), 0.90 rule (Tasks 2–3), soft reserve/dedup/50 cap/no min-fill/order/veto (Task 4), persisted evidence/versioning (Task 5), pipeline BLOCKED semantics (Task 6), calibration evidence (Tasks 7–8), independent artifact validation and docs (Task 9).

**Intentional gap:** No production absolute thresholds are implemented because the approved spec explicitly requires full-market calibration before owner approval. Market/Signal detectors are also outside scope and remain blocked.

**Placeholder scan:** This plan contains no implementation placeholders. “Still blocked” items are deliberate product gates, not unfinished task instructions.

**Type consistency:** `StrategyQualification` is created in Task 2, consumed by Tasks 3–9. `CandidateEvidence` and `CandidateSelection` are created in Task 4, consumed by Tasks 5–6. `CandidatePolicy.select()` replaces the old `qualify()` contract in Task 4 and is the only policy interface used afterward.
