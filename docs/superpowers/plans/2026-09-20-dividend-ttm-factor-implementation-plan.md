# 股息率 TTM 因子实现与红利策略资格激活实现计划 (Dividend Yield TTM Factor & Qualification Activation Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于项目所有者已批准的除权日、实施状态与基准日现价口径（A1+B1+C1），实现 `dividend_yield_ttm` 因子计算，集成至 Normalized 数据集与因子引擎，激活 Dividend 策略双门槛合格标的发现。

**Architecture:** 
1. 将已归一化的 `DividendEvent` 挂载入 `NormalizedDataset`；
2. 在 `src/astock_lens/factors/valuation.py`（或专用因子模块）实现 `DividendYieldTTMFactor`，依据除权日在过去 365 天内的已实施分红事件累加每股派息，除以 `as_of` 当日收盘价；
3. 全量运行 2026-09-19 因子重算与资格发现，验证 Dividend 策略从 0 合格转为正常合格标的。

**Tech Stack:** Python 3.12+, Pydantic, pytest, ruff, mypy

**Spec:** 
- `docs/decision-packets/2026-09-20-dividend-yield-definition-decision.md`
- `docs/superpowers/specs/2026-09-20-qualified-to-candidate-upgrade-design.md`
- `AGENTS.md`

## Global Constraints

- 严禁静默兜底：无分红事件记为 `NOT_APPLICABLE`（非分红股）或 0.0（依据设计规范，分红股无派息或无事件）；数据状态必须真实明确；
- 窗口严格限制：除权日必须满足 `as_of - 365天 <= ex_date <= as_of`；
- 预案严格排除：必须排除 `implementation_status` 为预案的记录，仅聚合已实施分红；
- 分母现价：必须使用 `as_of` 当日或最新可用的 `DailyBar.close`，若缺少价格则记为 `NULL` / `SOURCE_ERROR`；
- 所有代码测试先行（TDD，RED -> GREEN -> REFACTOR -> COMMIT -> PUSH）。

---

### Task 1: 扩展 NormalizedDataset 支持分红事件模型

**Files:**
- Modify: `src/astock_lens/data/contracts.py`
- Test: `tests/unit/test_normalized_dataset_dividends.py`

**Interfaces:**
- Consumes: `DividendEvent` from `src.astock_lens.data.dividends.models`
- Produces: `NormalizedDataset.dividend_events: tuple[DividendEvent, ...] = ()`

- [ ] **Step 1: Write failing unit test**
  编写测试验证 `NormalizedDataset` 可以持有 `dividend_events`，并在默认情况下为空元组。
- [ ] **Step 2: Run test to verify RED**
- [ ] **Step 3: Update NormalizedDataset definition**
- [ ] **Step 4: Run test to verify GREEN**
- [ ] **Step 5: Commit and push** (`归一化：数据契约增加分红事件集合`)

---

### Task 2: 实现 DividendYieldTTMFactor 计算器

**Files:**
- Create: `src/astock_lens/factors/dividend.py` (或在 `valuation.py` 扩展)
- Modify: `src/astock_lens/factors/registry.py`
- Test: `tests/unit/test_dividend_yield_factor.py`

**Interfaces:**
- Consumes: `FactorContext` (含 `dataset.dividend_events` 与 `dataset.daily_bars`)
- Produces: `FactorResult` 包含 `raw_value` (以 % 为单位，例如 3.52 表示 3.52%)，`inputs` 包含参与计算的除权日与分红金额引用

- [ ] **Step 1: Write failing tests for DividendYieldTTMFactor**
  - 测试 1: 正常单次/多次已实施分红，正确累计除权日在一年内的派息，除以现价，得出正确股息率；
  - 测试 2: 排除预案事件（预案不计入分红分子）；
  - 测试 3: 排除超过 365 天或晚于 as_of 的除权日事件；
  - 测试 4: 缺少收盘价或停牌时，返回 NULL；
  - 测试 5: 无任何分红事件的标的，返回 NOT_APPLICABLE。
- [ ] **Step 2: Run tests to verify RED**
- [ ] **Step 3: Implement DividendYieldTTMFactor logic**
- [ ] **Step 4: Run tests to verify GREEN**
- [ ] **Step 5: Register factor in factor registry**
- [ ] **Step 6: Commit and push** (`因子：实现除权日口径TTM股息率计算器`)

---

### Task 3: 管道装配与 2026-09-19 快照实测验证

**Files:**
- Modify: `src/astock_lens/pipelines/analysis.py` 或数据归一化加载器
- Test: `tests/integration/test_dividend_factor_pipeline.py`

**Interfaces:**
- Consumes: 真实分红事件落地文件 `data/raw/neodata/dividend_history/`
- Produces: 包含有效 `dividend_yield_ttm` 的 FACTOR 快照

- [ ] **Step 1: 编写集成测试验证分析管线在计算因子时正确载入分红事件**
- [ ] **Step 2: 实现分红数据与日线数据在分析上下文中的注入**
- [ ] **Step 3: 运行测试确保集成通过**
- [ ] **Step 4: Commit and push** (`管线：装配分红事件至因子分析上下文`)

---

### Task 4: 红利策略双门槛合格标的发现与审计

**Files:**
- Run CLI: `astock qualified dividend --as-of 2026-09-19`
- Test: `tests/integration/test_dividend_qualified_discovery.py`
- Docs: 更新 `docs/decision-packets/2026-09-20-dividend-repair-audit.md`

- [ ] **Step 1: 编写测试验证 Dividend 策略在具备真实股息率后产出合格标的**
- [ ] **Step 2: 执行真实 2026-09-19 数据计算**
- [ ] **Step 3: 审计 Dividend 策略双门槛合格名单与分布**
- [ ] **Step 4: 更新文档与 ROADMAP**
- [ ] **Step 5: Commit and push** (`校准：完成红利策略真实资格激活与审计`)
