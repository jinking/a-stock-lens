# Qualification Correctness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the production Candidate Qualification layer so the six strategy rules exactly match the owner's approved decision, qualification can read complete per-symbol Factor evidence instead of only strategy-scoring factors, invalid configuration fails closed, and the corrected rules are audited against the formal full-market research baseline.

**Architecture:** Introduce an explicit `QualificationContext` carrying `StrategyResult + all FactorResult evidence for that symbol`. Qualification rules evaluate that context; strategy scoring remains unchanged. Production YAML is locked by contract tests to the owner-approved rules, and a new read-only qualification-impact calibration command verifies real full-pool effects without publishing Candidate.

**Tech Stack:** Python >=3.12, Pydantic 2.x, PyYAML, Typer, existing SnapshotStore, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-20-qualification-correctness-hardening-design.md`

## Global Constraints

- Current audit baseline: `main` HEAD `44e3e15238a1bd3797210bcc256beb0a0b38da33`.
- Preserve all formal historical FACTOR / STRATEGY snapshots.
- Do not modify Strategy weights.
- Do not modify Research Universe thresholds.
- Do not implement Market Regime / Market Validation / Signal.
- Do not wire Candidate publishing.
- Do not synthesize MarketValidation or Signal.
- Do not create a cross-strategy global score.
- Do not reinterpret the approved business thresholds to fit current interfaces.
- Qualification configuration must fail closed.
- Strategy scoring factors and Qualification factors remain separate concepts.
- `astock calibrate qualification-impact` must be read-only.
- TDD: RED → minimal implementation → GREEN → focused commit → push.
- Chinese commit messages and project docs.
- Use an isolated worktree if the execution harness supports `superpowers:using-git-worktrees`.

## Review Focus

1. **Approved-rule drift:** production YAML factor names or values differ from the owner decision but tests still pass.
2. **Unit mismatch:** percent-valued factors are configured as ratios (the current Dividend failure mode).
3. **Evidence narrowing:** a qualification rule silently reads only `StrategyResult.factor_snapshot` and cannot access an approved factor.
4. **Fail-open config:** empty/malformed thresholds produce `passed=True`.
5. **Full-pool shock:** corrected rules technically work but qualify zero/all/nearly-all symbols unexpectedly without a visible audit report.

---

## Locked File Structure

### Create

- `src/astock_lens/qualifications/config.py`
- `src/astock_lens/calibration/qualification_impact.py`
- `tests/contract/test_qualification_production_rules.py`
- `tests/unit/test_qualification_config.py`
- `tests/unit/test_qualification_context.py`
- `tests/unit/test_qualification_impact.py`
- `tests/integration/test_qualification_pipeline.py`
- `tests/integration/test_qualification_impact_cli.py`
- `docs/superpowers/specs/2026-09-20-qualification-correctness-hardening-design.md`
- `docs/superpowers/plans/2026-09-20-qualification-correctness-hardening-implementation-plan.md`
- `docs/decision-packets/2026-09-20-qualification-repair-audit.md`

### Modify

- `configs/qualifications/value.yaml`
- `configs/qualifications/growth.yaml`
- `configs/qualifications/garp.yaml`
- `configs/qualifications/quality.yaml`
- `configs/qualifications/dividend.yaml`
- `configs/qualifications/momentum.yaml`
- `src/astock_lens/qualifications/models.py`
- `src/astock_lens/qualifications/contracts.py`
- `src/astock_lens/qualifications/common.py`
- `src/astock_lens/qualifications/rules.py`
- `src/astock_lens/qualifications/registry.py`
- `src/astock_lens/qualifications/value.py`
- `src/astock_lens/qualifications/growth.py`
- `src/astock_lens/qualifications/garp.py`
- `src/astock_lens/qualifications/quality.py`
- `src/astock_lens/qualifications/dividend.py`
- `src/astock_lens/qualifications/momentum.py`
- `src/astock_lens/pipelines/stages.py`
- `src/astock_lens/pipelines/daily.py`
- `src/astock_lens/cli/app.py`
- `tests/unit/test_strategy_qualification.py`
- `tests/unit/test_candidate_routing.py`
- `docs/ROADMAP.md`
- `docs/REMAINING_PRODUCT_BLOCKERS.md`
- `docs/REVIEW_NOTES.md`
- `.workbuddy/memory/2026-09-20.md`

### Forbidden

- `src/astock_lens/candidates/policy.py` semantics
- Strategy configs/weights
- Universe config values
- Market Regime rules
- Market Validation rules
- Signal rules
- Candidate Snapshot publication
- Today/Web work

---

# Task 1: Lock the Owner-Approved Production Rules with Contract Tests

**Files:**
- Create: `tests/contract/test_qualification_production_rules.py`

**Interfaces:**
- Consumes the six production YAML files.
- Produces a hard contract that later tasks must make green.

- [ ] **Step 1: Write exact expected production rules**

```python
EXPECTED = {
    "value": {
        "pe_ttm": {"max": 25.0},
        "pb": {"max": 2.5},
        "roe_ttm": {"min": 5.0},
    },
    "growth": {
        "net_profit_parent_yoy": {"min": 15.0},
        "revenue_yoy": {"min": 5.0},
        "roe_ttm": {"min": 8.0},
    },
    "garp": {
        "pe_ttm": {"max": 35.0},
        "net_profit_parent_yoy": {"min": 15.0},
        "roe_ttm": {"min": 10.0},
    },
    "quality": {
        "roe_ttm": {"min": 12.0},
        "gross_margin": {"min": 20.0},
        "debt_to_asset": {"max": 65.0},
    },
    "dividend": {
        "dividend_yield_ttm": {"min": 3.0},
        "dividend_payout_ttm": {"min": 0.10, "max": 0.80},
    },
    "momentum": {
        "proximity_52w_high": {"min": 0.80},
    },
}
```

- [ ] **Step 2: Write a RED test reading the actual YAML**

```python
@pytest.mark.parametrize("strategy_id", EXPECTED)
def test_production_rule_matches_owner_approval(strategy_id: str) -> None:
    raw = yaml.safe_load(
        (ROOT / "configs" / "qualifications" / f"{strategy_id}.yaml")
        .read_text(encoding="utf-8")
    )

    assert raw["strategy_id"] == strategy_id
    assert raw["version"] == "v1"
    assert raw["thresholds"] == EXPECTED[strategy_id]
```

Expected RED on current main:
- Growth mismatch;
- Dividend mismatch;
- GARP mismatch;
- Value mismatch because current config adds unapproved positive minima.

- [ ] **Step 3: Add explicit unit-regression test**

```python
def test_dividend_rule_uses_approved_metrics_not_percent_ratio_substitute() -> None:
    thresholds = load_raw_thresholds("dividend")
    assert thresholds["dividend_yield_ttm"]["min"] == 3.0
    assert thresholds["dividend_payout_ttm"] == {"min": 0.10, "max": 0.80}
    assert "dividend_paid_ratio" not in thresholds
```

- [ ] **Step 4: Pin Momentum liquidity boundary as upstream Universe policy**

```python
def test_momentum_liquidity_is_an_upstream_universe_gate() -> None:
    universe = yaml.safe_load((ROOT / "configs/universe.yaml").read_text())
    assert universe["min_average_turnover_20d"] == 150_000_000

    momentum = load_raw_thresholds("momentum")
    assert momentum == {"proximity_52w_high": {"min": 0.80}}
```

Do not invent “above cross-sectional mean” logic.

- [ ] **Step 5: Run and preserve RED evidence**

```bash
PYTHONPATH= uv run --no-sync pytest   tests/contract/test_qualification_production_rules.py -v
```

Record the exact mismatches in `docs/REVIEW_NOTES.md`.

- [ ] **Step 6: Commit the RED contract only**

```bash
git add tests/contract/test_qualification_production_rules.py docs/REVIEW_NOTES.md
git commit -m "测试：锁定所有者批准的六策略资格规则"
git push
```

---

# Task 2: Introduce QualificationContext and Separate Scoring Evidence from Qualification Evidence

**Files:**
- Modify: `src/astock_lens/qualifications/models.py`
- Modify: `src/astock_lens/qualifications/contracts.py`
- Modify: `src/astock_lens/qualifications/common.py`
- Modify: all six qualifier modules
- Create: `tests/unit/test_qualification_context.py`
- Modify: `tests/unit/test_strategy_qualification.py`

**Interfaces:**

Create:

```python
class QualificationContext(DomainRecord):
    strategy_result: StrategyResult
    factors: tuple[FactorResult, ...] = ()
```

Change:

```python
class AbsoluteQualificationRule(Protocol):
    version: str

    def evaluate(
        self,
        context: QualificationContext,
    ) -> AbsoluteQualificationVerdict:
        ...
```

Change:

```python
class StrategyQualifier(Protocol):
    strategy_id: str
    qualification_version: str

    def qualify(
        self,
        context: QualificationContext,
    ) -> StrategyQualification:
        ...
```

- [ ] **Step 1: Write RED Growth test using ROE outside Strategy factor snapshot**

Construct:

```text
StrategyResult.factor_snapshot:
    revenue_yoy
    revenue_cagr_3y
    net_profit_parent_yoy
    net_profit_parent_cagr_3y

QualificationContext.factors:
    all above + roe_ttm
```

Test:

```python
def test_growth_qualification_can_read_non_scoring_roe_factor() -> None:
    context = QualificationContext(
        strategy_result=growth_result(rank_percentile=0.95),
        factors=(
            factor("net_profit_parent_yoy", 20.0),
            factor("revenue_yoy", 8.0),
            factor("roe_ttm", 9.0),
        ),
    )
    qualification = qualifier.qualify(context)
    assert qualification.absolute_pass is True
```

- [ ] **Step 2: Write RED missing-evidence test**

```python
def test_missing_approved_qualification_factor_fails_closed() -> None:
    context = QualificationContext(
        strategy_result=growth_result(rank_percentile=0.95),
        factors=(
            factor("net_profit_parent_yoy", 20.0),
            factor("revenue_yoy", 8.0),
        ),
    )
    qualification = qualifier.qualify(context)
    assert qualification.absolute_pass is False
    assert any("roe_ttm" in risk for risk in qualification.risks)
```

- [ ] **Step 3: Implement `QualificationContext`**

```python
class QualificationContext(DomainRecord):
    strategy_result: StrategyResult
    factors: tuple[FactorResult, ...] = ()
```

- [ ] **Step 4: Update contracts and common builder**

`build_qualification` now accepts `context`.

```python
def build_qualification(
    *,
    context: QualificationContext,
    expected_strategy_id: str,
    qualification_version: str,
    absolute_rule: AbsoluteQualificationRule,
) -> StrategyQualification:
    result = context.strategy_result
    ...
    verdict = absolute_rule.evaluate(context)
```

- [ ] **Step 5: Update six strategy qualifiers mechanically**

Each becomes:

```python
def qualify(self, context: QualificationContext) -> StrategyQualification:
    return build_qualification(
        context=context,
        expected_strategy_id=self.strategy_id,
        qualification_version=self.qualification_version,
        absolute_rule=self.absolute_rule,
    )
```

Do not add per-strategy special behavior.

- [ ] **Step 6: Update old tests**

Migrate:

```python
qualifier.qualify(result)
```

to:

```python
qualifier.qualify(
    QualificationContext(
        strategy_result=result,
        factors=result.factor_snapshot,
    )
)
```

Tests needing non-scoring factors must pass them explicitly.

- [ ] **Step 7: Run**

```bash
PYTHONPATH= uv run --no-sync pytest   tests/unit/test_qualification_context.py   tests/unit/test_strategy_qualification.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/astock_lens/qualifications         tests/unit/test_qualification_context.py         tests/unit/test_strategy_qualification.py
git commit -m "资格：分离策略评分证据与绝对资格证据"
git push
```

---

# Task 3: Make Qualification Configuration Strict and Fail-Closed

**Files:**
- Create: `src/astock_lens/qualifications/config.py`
- Modify: `src/astock_lens/qualifications/rules.py`
- Modify: `src/astock_lens/qualifications/contracts.py`
- Modify: `src/astock_lens/qualifications/registry.py`
- Create: `tests/unit/test_qualification_config.py`

**Interfaces:**

Add:

```python
class QualificationConfigInvalid(ValueError):
    ...
```

Add strict config models:

```python
class FactorThreshold(DomainRecord):
    min: float | None = None
    max: float | None = None

class QualificationRuleConfig(DomainRecord):
    strategy_id: str
    version: str
    description: str = ""
    thresholds: dict[str, FactorThreshold]
```

Loader:

```python
def load_qualification_rule(
    path: Path,
    *,
    expected_strategy_id: str | None = None,
    known_factor_names: frozenset[str] | None = None,
) -> FactorThresholdRule:
    ...
```

- [ ] **Step 1: Write RED tests for every fail-open case**

Required tests:

```python
def test_empty_thresholds_are_invalid(): ...
def test_threshold_without_min_or_max_is_invalid(): ...
def test_min_greater_than_max_is_invalid(): ...
def test_nan_or_inf_is_invalid(): ...
def test_non_mapping_threshold_is_invalid(): ...
def test_strategy_id_must_match_expected_strategy(): ...
def test_unknown_factor_is_invalid(): ...
def test_blank_version_is_invalid(): ...
```

- [ ] **Step 2: Implement strict validation**

For `FactorThreshold`:

```python
@model_validator(mode="after")
def validate_bounds(self) -> Self:
    if self.min is None and self.max is None:
        raise ValueError("threshold requires min and/or max")
    for value in (self.min, self.max):
        if value is not None and not math.isfinite(value):
            raise ValueError("threshold bounds must be finite")
    if self.min is not None and self.max is not None and self.min > self.max:
        raise ValueError("threshold min cannot exceed max")
    return self
```

For rule config:
- strip `strategy_id` and `version`;
- reject blank;
- reject empty thresholds.

- [ ] **Step 3: Remove silent skipping**

Delete behavior equivalent to:

```python
if not isinstance(bounds, dict):
    continue
```

Malformed entries must raise `QualificationConfigInvalid`.

- [ ] **Step 4: Validate expected strategy id and factor catalog**

```python
if expected_strategy_id is not None and cfg.strategy_id != expected_strategy_id:
    raise QualificationConfigInvalid(...)

unknown = set(cfg.thresholds) - known_factor_names
if unknown:
    raise QualificationConfigInvalid(...)
```

- [ ] **Step 5: Harden canonical loader**

Change:

```python
load_canonical_qualifiers(
    config_dir=None,
    *,
    enabled_strategy_ids=...,
    known_factor_names: frozenset[str],
)
```

Each file is loaded with:

```python
load_qualification_rule(
    cfg_file,
    expected_strategy_id=strat_id,
    known_factor_names=known_factor_names,
)
```

- [ ] **Step 6: Preserve missing-vs-invalid semantics**

- missing file → `QualificationRuleNotConfigured`;
- malformed/invalid file → `QualificationConfigInvalid`.

Do not catch `QualificationConfigInvalid` and convert it to `qualifiers=None`.

- [ ] **Step 7: Run**

```bash
PYTHONPATH= uv run --no-sync pytest   tests/unit/test_qualification_config.py   tests/unit/test_strategy_qualification.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/astock_lens/qualifications tests/unit/test_qualification_config.py
git commit -m "资格：生产规则配置改为严格失败关闭"
git push
```

---

# Task 4: Restore the Six Production YAML Files to the Approved Rules

**Files:**
- Modify: `configs/qualifications/*.yaml`
- Test: `tests/contract/test_qualification_production_rules.py`

- [ ] **Step 1: Replace Value**

```yaml
strategy_id: value
version: v1
description: 稳健价值门槛：PE<=25、PB<=2.5、ROE TTM>=5%
thresholds:
  pe_ttm:
    max: 25.0
  pb:
    max: 2.5
  roe_ttm:
    min: 5.0
```

- [ ] **Step 2: Replace Growth**

```yaml
strategy_id: growth
version: v1
description: 稳健成长门槛：净利同比>=15%、营收同比>=5%、ROE TTM>=8%
thresholds:
  net_profit_parent_yoy:
    min: 15.0
  revenue_yoy:
    min: 5.0
  roe_ttm:
    min: 8.0
```

- [ ] **Step 3: Replace GARP**

```yaml
strategy_id: garp
version: v1
description: 合理估值成长门槛：PE TTM<=35、净利同比>=15%、ROE TTM>=10%
thresholds:
  pe_ttm:
    max: 35.0
  net_profit_parent_yoy:
    min: 15.0
  roe_ttm:
    min: 10.0
```

- [ ] **Step 4: Keep Quality aligned**

```yaml
strategy_id: quality
version: v1
description: 质量门槛：ROE TTM>=12%、毛利率>=20%、资产负债率<=65%
thresholds:
  roe_ttm:
    min: 12.0
  gross_margin:
    min: 20.0
  debt_to_asset:
    max: 65.0
```

- [ ] **Step 5: Replace Dividend**

```yaml
strategy_id: dividend
version: v1
description: 可持续红利门槛：股息率TTM>=3%，分红支付率TTM处于10%~80%
thresholds:
  dividend_yield_ttm:
    min: 3.0
  dividend_payout_ttm:
    min: 0.10
    max: 0.80
```

- [ ] **Step 6: Keep Momentum aligned**

```yaml
strategy_id: momentum
version: v1
description: 动量门槛：现价处于近一年最高价80%以上；流动性由Research Universe准入门槛负责
thresholds:
  proximity_52w_high:
    min: 0.80
```

- [ ] **Step 7: Run contract test**

```bash
PYTHONPATH= uv run --no-sync pytest   tests/contract/test_qualification_production_rules.py -v
```

Expected: PASS.

- [ ] **Step 8: Strict-load all production rules**

```bash
PYTHONPATH= uv run --no-sync python - <<'PY'
from astock_lens.cli.app import _factor_configs
from astock_lens.qualifications.registry import load_canonical_qualifiers

factor_names = frozenset(c.name for c in _factor_configs())
qualifiers = load_canonical_qualifiers(known_factor_names=factor_names)
print(sorted(qualifiers))
PY
```

Expected six canonical strategy ids.

- [ ] **Step 9: Commit**

```bash
git add configs/qualifications tests/contract/test_qualification_production_rules.py
git commit -m "修复：恢复所有者批准的六策略资格门槛"
git push
```

---

# Task 5: Wire Full Factor Evidence into `qualification_stage`

**Files:**
- Modify: `src/astock_lens/pipelines/stages.py`
- Modify: `src/astock_lens/pipelines/daily.py`
- Modify: `src/astock_lens/cli/app.py`
- Create: `tests/integration/test_qualification_pipeline.py`
- Modify: `tests/unit/test_candidate_routing.py`

**Interfaces:**

Change:

```python
def qualification_stage(
    *,
    strategy_results: Sequence[StrategyResult],
    factor_results: Sequence[FactorResult],
    qualifiers: Mapping[str, StrategyQualifier],
) -> tuple[StrategyQualification, ...]:
    ...
```

- [ ] **Step 1: Write RED Growth integration test**

The Growth `StrategyResult.factor_snapshot` deliberately does not contain `roe_ttm`.

Pass full `factor_results` containing ROE.

Assert Growth qualification uses the full Factor evidence and passes.

- [ ] **Step 2: Write RED Dividend unit regression**

Use:

```text
dividend_yield_ttm = 3.5
dividend_payout_ttm = 0.50
rank_percentile = 0.95
```

and deliberately place:

```text
dividend_paid_ratio = 79.0
```

in the strategy scoring snapshot.

Assert:
- approved Dividend qualification passes;
- `79.0` is never compared against `0.80`.

- [ ] **Step 3: Write RED GARP regression**

Use:

```text
pe_ttm = 30
net_profit_parent_yoy = 20
roe_ttm = 12
```

while the GARP strategy factor snapshot contains only scoring factors.

Assert qualification passes.

- [ ] **Step 4: Reuse `FactorResultIndex`**

```python
index = FactorResultIndex(factor_results)

for result in strategy_results:
    if not result.eligible:
        continue
    qualifier = qualifiers.get(result.strategy_id)
    ...
    context = QualificationContext(
        strategy_result=result,
        factors=index.for_symbol(result.symbol),
    )
    qualifications.append(qualifier.qualify(context))
```

No repeated full-list scan.

- [ ] **Step 5: Update daily**

```python
state.qualifications = stages.qualification_stage(
    strategy_results=state.strategy_results,
    factor_results=state.factor_results,
    qualifiers=context.qualifiers,
)
```

Do not unblock BUILD_CANDIDATES.

- [ ] **Step 6: Load factor configs once in `_run_daily`**

```python
factor_configs = _factor_configs()
factor_names = frozenset(config.name for config in factor_configs)

try:
    qualifiers = load_canonical_qualifiers(
        known_factor_names=factor_names,
    )
except QualificationRuleNotConfigured:
    qualifiers = None

return run_daily(
    ...,
    factor_configs=factor_configs,
    qualifiers=qualifiers,
)
```

Do not catch `QualificationConfigInvalid`.

- [ ] **Step 7: Run focused suite**

```bash
PYTHONPATH= uv run --no-sync pytest   tests/integration/test_qualification_pipeline.py   tests/unit/test_candidate_routing.py   tests/unit/test_strategy_qualification.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/astock_lens/pipelines         src/astock_lens/cli/app.py         tests/integration/test_qualification_pipeline.py         tests/unit/test_candidate_routing.py         tests/unit/test_strategy_qualification.py
git commit -m "管线：资格判定改用完整股票因子证据"
git push
```

---

# Task 6: Add Read-Only Qualification Impact Audit

**Files:**
- Create: `src/astock_lens/calibration/qualification_impact.py`
- Modify: `src/astock_lens/cli/app.py`
- Create: `tests/unit/test_qualification_impact.py`
- Create: `tests/integration/test_qualification_impact_cli.py`

**Interfaces:**

```python
class StrategyQualificationImpact(DomainRecord):
    strategy_id: str
    strategy_eligible_count: int
    ranked_count: int
    top_ten_count: int
    absolute_pass_count: int
    dual_pass_count: int
    failure_reasons: tuple[tuple[str, int], ...]
    qualified_symbols: tuple[str, ...]

class QualificationImpactReport(DomainRecord):
    as_of: datetime
    strategies: tuple[StrategyQualificationImpact, ...]

def build_qualification_impact(
    *,
    factor_results: Sequence[FactorResult],
    strategy_results: Sequence[StrategyResult],
    qualifiers: Mapping[str, StrategyQualifier],
    as_of: datetime,
) -> QualificationImpactReport:
    ...
```

- [ ] **Step 1: RED counting test**

Fixture includes:
- absolute pass + top10 pass;
- absolute pass + below top10;
- absolute fail + top10;
- missing factor.

Assert `top_ten_count`, `absolute_pass_count`, `dual_pass_count` independently.

- [ ] **Step 2: RED failure-reason aggregation**

Two symbols failing the same factor should produce an aggregated factor/reason count.

- [ ] **Step 3: Implement using the same qualification logic**

Do not fork or reimplement threshold evaluation.

- [ ] **Step 4: Add CLI**

```bash
astock calibrate qualification-impact   --as-of YYYY-MM-DD   --output-dir PATH
```

Read:
- stored FACTOR Snapshot;
- stored STRATEGY Snapshot;
- strict canonical qualifiers.

Write only:
- `qualification-impact-YYYY-MM-DD.json`;
- `qualification-impact-YYYY-MM-DD.md`.

Forbidden:
- Provider calls;
- Factor/Strategy recomputation;
- Snapshot/Watchlist/Job/Candidate writes.

- [ ] **Step 5: Add read-only assertion**

Fingerprint Snapshot / Watchlist / Job state before and after.

Expected only the requested output directory changes.

- [ ] **Step 6: Render Markdown**

Minimum summary:

```text
strategy | eligible | ranked | top10 | absolute-pass | dual-pass
```

Then per strategy:
- top failure reasons;
- up to 20 qualified symbols;
- representative boundary samples.

- [ ] **Step 7: Run**

```bash
PYTHONPATH= uv run --no-sync pytest   tests/unit/test_qualification_impact.py   tests/integration/test_qualification_impact_cli.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/astock_lens/calibration/qualification_impact.py         src/astock_lens/cli/app.py         tests/unit/test_qualification_impact.py         tests/integration/test_qualification_impact_cli.py
git commit -m "校准：增加六策略资格规则只读影响审计"
git push
```

---

# Task 7: Run the Real 2,303-Symbol Qualification Repair Acceptance

**Files:**
- Create: `docs/decision-packets/2026-09-20-qualification-repair-audit.md`
- Modify: `docs/REVIEW_NOTES.md`

**No production code change.**

- [ ] **Step 1: Verify the formal baseline**

Start from:

```text
as_of = 2026-09-19
Research Universe ≈ 2,303
FactorResult ≈ 55,272
StrategyResult ≈ 13,818
```

Read actual stored records and record actual counts. Do not force old numbers if current formal state differs.

- [ ] **Step 2: Run impact audit**

```bash
PYTHONPATH= uv run --no-sync astock calibrate qualification-impact   --as-of 2026-09-19   --output-dir var/calibration/qualification-repair
```

- [ ] **Step 3: Record six actual distributions**

For each strategy:

```text
eligible
ranked
top10
absolute pass
dual pass
dual pass / ranked
top 5 failure reasons
```

- [ ] **Step 4: Trigger safety review on extreme output**

These are review triggers, not automatic product thresholds:

```text
dual_pass_count == 0
dual_pass_count == ranked_count
dual_pass_count / ranked_count < 0.005
dual_pass_count / ranked_count > 0.50
```

If triggered:
- inspect at least 20 boundary examples;
- verify units/DataStatus;
- do not change approved thresholds without owner approval.

- [ ] **Step 5: Verify repaired strategies directly**

Growth qualified samples must show:

```text
net_profit_parent_yoy >= 15
revenue_yoy >= 5
roe_ttm >= 8
```

Dividend qualified samples must show:

```text
dividend_yield_ttm >= 3.0
0.10 <= dividend_payout_ttm <= 0.80
```

`dividend_paid_ratio` must not control the verdict.

GARP qualified samples must show:

```text
pe_ttm <= 35
net_profit_parent_yoy >= 15
roe_ttm >= 10
```

`pe_percentile` must not control the absolute verdict.

- [ ] **Step 6: Write repair audit**

Include:
- previous defect;
- corrected rule;
- actual full-pool pass counts;
- representative pass/fail boundary samples;
- proof no Candidate was published.

- [ ] **Step 7: Commit**

```bash
git add docs/decision-packets/2026-09-20-qualification-repair-audit.md         docs/REVIEW_NOTES.md
git commit -m "验收：完成六策略资格规则全研究池修复审计"
git push
```

---

# Task 8: Repair Documentation Drift and Run Final Gates

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/REMAINING_PRODUCT_BLOCKERS.md`
- Modify: `docs/REVIEW_NOTES.md`
- Modify: `.workbuddy/memory/2026-09-20.md`

- [ ] **Step 1: Correct roadmap**

```text
Stock Discovery                         COMPLETE
P1 Valuation                            COMPLETE
P2 Owner Qualification Decision         COMPLETE
P2 Qualification Implementation         REPAIRED + AUDITED
P3 Market Regime/Validation/Signal      BLOCKED
P4 Candidate Publishing                 BLOCKED
P5 Today/Web                            NOT STARTED
```

- [ ] **Step 2: Remove stale current-state claims**

Current sections must no longer say:
- qualification configs do not exist;
- Value only has 2 results / GARP 1;
- industry is below 100% if canonical evidence is still 2303/2303;
- trading-calendar skip is unimplemented if current HEAD already implements it.

Historical records may remain, but label them as historical.

- [ ] **Step 3: Run all quality gates**

```bash
make test-fast PYTHONPATH=
PYTHONPATH= uv run --no-sync pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

- [ ] **Step 4: Prove invalid config fails loudly**

Use temp configs for:
- empty thresholds;
- wrong strategy id;
- unknown factor;
- min > max.

Expected: `QualificationConfigInvalid`.

Never:
- pass;
- silently skip;
- become `qualifiers=None`.

- [ ] **Step 5: Prove Candidate remains blocked**

Run:

```bash
PYTHONPATH= uv run --no-sync astock daily   --as-of 2026-09-19   --allow-incomplete
```

Expected:
- qualification-rule-not-configured blocker is gone;
- genuine later-stage blockers remain;
- no CANDIDATE Snapshot is written.

Do not disable historical snapshot conflict protection. If the existing 2026-09-19 daily snapshots are immutable and rerun would conflict, inspect the existing Job/Snapshot state instead of overwriting.

- [ ] **Step 6: Commit**

```bash
git add docs/ROADMAP.md docs/REMAINING_PRODUCT_BLOCKERS.md         docs/REVIEW_NOTES.md .workbuddy/memory/2026-09-20.md
git commit -m "审计：完成候选资格正确性加固并清理状态漂移"
git push
```

---

# Mandatory STOP Gate

After Task 8, STOP.

This repair plan does **not** authorize:

- Market Regime implementation;
- Market Validation implementation;
- Signal implementation;
- `RepresentativeCandidatePolicy` production wiring;
- CANDIDATE Snapshot publication;
- `astock today`;
- Web UI;
- changes to approved qualification thresholds;
- cross-strategy combined score.

Return the repair audit to the owner first.

---

# Required Agent Completion Report

```text
1. Task 1–8 commit SHAs
2. Remote main HEAD
3. Baseline full pytest result before changes
4. RED contract-test evidence before YAML repair
5. Final six production rule payloads
6. Proof Growth uses roe_ttm >= 8
7. Proof Dividend uses dividend_yield_ttm >= 3
8. Proof Dividend uses 0.10 <= dividend_payout_ttm <= 0.80
9. Proof Dividend no longer uses dividend_paid_ratio for qualification
10. Proof GARP uses pe_ttm <= 35
11. Proof GARP uses net_profit_parent_yoy >= 15
12. Proof GARP no longer uses pe_percentile as absolute gate
13. QualificationContext test result
14. Full-factor-evidence pipeline test result
15. Empty-threshold config rejection
16. Unknown-factor config rejection
17. strategy_id mismatch rejection
18. min > max rejection
19. Full-pool Research Universe count
20. FactorResult count
21. StrategyResult count
22. Value top10 / absolute-pass / dual-pass
23. Growth top10 / absolute-pass / dual-pass
24. GARP top10 / absolute-pass / dual-pass
25. Quality top10 / absolute-pass / dual-pass
26. Dividend top10 / absolute-pass / dual-pass
27. Momentum top10 / absolute-pass / dual-pass
28. Any extreme-output safety review triggered
29. Qualification-impact JSON path
30. Qualification-impact Markdown path
31. Repair audit path
32. Proof qualification-impact is read-only
33. Proof no CANDIDATE snapshot was written
34. Remaining BUILD_CANDIDATES blockers
35. Ruff result
36. Ruff format result
37. mypy result
38. full pytest result
39. git diff --check
40. git status --short
41. Any plan deviation with exact reason and commit
```

Correct completion statement:

```text
Production Qualification now matches the owner-approved rules, uses complete per-symbol Factor evidence, fails closed on invalid configuration, and has been audited on the formal research pool. Formal Candidate publishing remains blocked by the later Market/Signal/Candidate gates.
```

---

# Self-Review

## Spec Coverage

- Approved-rule drift: Tasks 1 and 4.
- Dividend/GARP unit defects: Tasks 1, 4, 5, 7.
- Full qualification evidence: Tasks 2 and 5.
- Fail-closed loader: Task 3.
- Full-pool impact audit: Tasks 6 and 7.
- Documentation drift: Task 8.
- Candidate stays blocked: Tasks 5, 7, 8 and STOP Gate.

## Placeholder Scan

No implementation TODO/TBD placeholders are used. Later product work is explicitly outside this plan.

## Type Consistency

`QualificationContext` is defined once in Task 2 and used unchanged in Tasks 5–7. `load_canonical_qualifiers(..., known_factor_names=...)` is defined in Task 3 and used consistently thereafter.

## Review Focus Coverage

1. Approved-rule drift → Task 1.
2. Unit mismatch → Tasks 1, 5, 7.
3. Evidence narrowing → Tasks 2, 5.
4. Fail-open config → Task 3.
5. Full-pool shock → Tasks 6, 7.
