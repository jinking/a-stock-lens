# 市场环境、市场验证与信号规则实现计划 (Market & Signal Implementation Plan - Plan E)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于项目所有者已批准的 R2 复合多维市场环境、5 维市场验证矩阵（支持一票否决）以及策略交易特征信号词表，工程实现 Market Regime、Market Validation 与 Signal 判定引擎，并集成至分析流水线，为候选股票（Candidate）发布铺平道路。

**Architecture:**
1. **Market Regime (市场环境)**: 依据日线行情与全市场数据计算市场宽度 (`breadth_ratio`)、指数趋势与波动率，判定 5 态环境 (`BULL`, `RANGE_UP`, `RANGE`, `RANGE_DOWN`, `BEAR`)；
2. **Market Validation (市场验证)**: 依据 5 维特征矩阵（个股趋势、板块/行业、相对强弱、量价配合、流动性底线）输出三态枚举 (`CONFIRMED`, `NEUTRAL`, `CONTRADICTED`)，流动性不足或负向项 >= 2 时判定为 `CONTRADICTED`（支持一票否决）；
3. **Signal (技术特征信号)**: 结合标的所归属策略及技术因子分位数，输出交易特征信号标签 (`BREAKOUT`, `TREND_CONTINUE`, `PULLBACK`, `VALUE_CONTRARIAN`, `DIVIDEND_SUPPORT`, `TREND_WEAKEN`, `BREAKDOWN`, `NO_SIGNAL`)；
4. **Pipeline Integration (管线装配)**: 在 `astock_lens.pipelines` 中打通因子计算后的环境判定、市场验证与信号生成阶段；
5. **Mode B 防线维护**: 严格坚守项目所有者签署的 Mode B 全局阻塞约定，在正式全面放行前不擅自发布虚假买入建议。

**Tech Stack:** Python 3.12+, Pydantic, pytest, ruff, mypy

**Spec:**
- `docs/decision-packets/2026-09-20-market-signal-owner-decisions.md` (已获批)
- `docs/superpowers/specs/2026-09-20-qualified-to-candidate-upgrade-design.md`
- `AGENTS.md`

---

## 全局约束与红线

- **禁止静默兜底**: 因子缺失或数据异常绝不转化为 0.0，必须保留 `DataStatus`；
- **纯粹特征描述**: Signal 只是客观市场状态与特征描述，绝非买卖建议或投资指令；
- **单 Task 单 Commit**: 遵循 TDD 闭环（RED -> GREEN -> REFACTOR -> COMMIT -> PUSH）；
- **全流程中文**: 提交信息、注释与测试用例说明一律中文。

---

### Task 1: 实现复合多维市场环境判定器 (Market Regime Detector)

**Files:**
- Create: `src/astock_lens/market/regime.py`
- Modify: `src/astock_lens/market/__init__.py`
- Test: `tests/unit/test_market_regime_detector.py`

**Interfaces:**
- Consumes: `MarketRegimeContext`（包含全市场日线条目、指数均线趋势或市场宽度比例 `breadth_ratio`）
- Produces: `MarketRegimeResult`（包含 `regime: MarketRegime`, `breadth_ratio: float`, `reasons: tuple[str, ...]`）

- [ ] **Step 1: 编写 RED 单元测试**
  - 测试 1: 市场宽度 `breadth_ratio > 0.55` 且指数趋势向上时判定为 `BULL` 或 `RANGE_UP`；
  - 测试 2: 市场宽度在 `0.40 <= breadth_ratio <= 0.55` 时判定为 `RANGE`；
  - 测试 3: 市场宽度 `< 0.40` 且指数下行时判定为 `BEAR` 或 `RANGE_DOWN`；
  - 测试 4: 缺少必要日线数据时 fail-closed，记录清晰风险原因而不随意兜底。
- [ ] **Step 2: 运行测试确认 RED**
- [ ] **Step 3: 实现 MarketRegimeDetector**
- [ ] **Step 4: 运行测试确认 GREEN**
- [ ] **Step 5: Commit and push** (`市场环境：实现复合多维市场状态判定器`)

---

### Task 2: 实现 5 维市场验证矩阵判定器 (Market Validator)

**Files:**
- Create: `src/astock_lens/market/validation.py`
- Modify: `src/astock_lens/market/__init__.py`
- Test: `tests/unit/test_market_validator.py`

**Interfaces:**
- Consumes: `ValidationContext`（标的 symbol、策略 ID、技术与估值因子映射、行业超额等）
- Produces: `MarketValidationResult`（包含 `status: MarketValidation`, `positive_count: int`, `negative_count: int`, `reasons: tuple[str, ...]`, `risks: tuple[str, ...]`）

- [ ] **Step 1: 编写 RED 单元测试**
  - 测试 1: 流动性警戒线拦截：20日日均成交额 `< 1.0 亿元` 直接判定为 `CONTRADICTED`（一票否决）；
  - 测试 2: 动量策略破位拦截：`ret_20d < 0` 或跌破 15% 计为负向冲突；负向项 >= 2 时输出 `CONTRADICTED`；
  - 测试 3: 价值/红利策略筑底容忍：`ret_20d` 在 -10% ~ 0% 且估值合理不误判冲突；
  - 测试 4: 各项指标健康且具备趋势支撑时判定为 `CONFIRMED`；
  - 测试 5: 平衡过渡状态判定为 `NEUTRAL`。
- [ ] **Step 2: 运行测试确认 RED**
- [ ] **Step 3: 实现 MarketValidator**
- [ ] **Step 4: 运行测试确认 GREEN**
- [ ] **Step 5: Commit and push** (`市场验证：实现5维客观验证与一票否决矩阵`)

---

### Task 3: 实现多策略特征交易信号检测器 (Signal Detector)

**Files:**
- Create: `src/astock_lens/signals/detector.py`
- Modify: `src/astock_lens/signals/__init__.py`, `src/astock_lens/signals/contracts.py`
- Test: `tests/unit/test_signal_detector.py`

**Interfaces:**
- Consumes: `SignalContext`（标的 symbol、策略上下文、技术因子分布）
- Produces: `SignalResult`（包含 `signal: Signal`, `reasons: tuple[str, ...]`, `lineage: SnapshotLineage`）

- [ ] **Step 1: 编写 RED 单元测试**
  - 测试 1: 动量突破：`proximity_52w_high >= 0.95` 且量比放量触发 `BREAKOUT`；
  - 测试 2: 动量回踩：`ret_60d >= 20%` 且 `ret_20d` 处于 0% ~ 5% 触发 `PULLBACK`；
  - 测试 3: 价值筑底：深度估值标的且 `ret_20d` 企稳 (-5% ~ +2%) 触发 `VALUE_CONTRARIAN`；
  - 测试 4: 严重破位：20日跌幅超过 -15% 触发 `BREAKDOWN`；
  - 测试 5: 无显著特征返回 `NO_SIGNAL`。
- [ ] **Step 2: 运行测试确认 RED**
- [ ] **Step 3: 实现 DefaultSignalDetector**
- [ ] **Step 4: 运行测试确认 GREEN**
- [ ] **Step 5: Commit and push** (`信号：实现各策略特征交易状态检测器`)

---

### Task 4: 管线装配与端到端集成验证 (Pipeline Assembly & Integration)

**Files:**
- Modify: `src/astock_lens/pipelines/stages.py`, `src/astock_lens/pipelines/analysis.py`
- Test: `tests/integration/test_market_signal_pipeline.py`

**Interfaces:**
- 将 Market Regime、Market Validation 与 Signal 判定完整装配进分析链路中，产出完整的验证与信号快照；
- 保持 `daily.py` 中的安全门禁，确保 Mode B 语义。

- [ ] **Step 1: 编写集成测试验证管线各阶段顺畅衔接与快照生成**
- [ ] **Step 2: 装配 market 与 signal 阶段**
- [ ] **Step 3: 运行全量测试验证 100% 通过**
- [ ] **Step 4: 更新 ROADMAP.md 与 memory**
- [ ] **Step 5: Commit and push** (`管线：装配市场环境验证与信号检测全链路`)
