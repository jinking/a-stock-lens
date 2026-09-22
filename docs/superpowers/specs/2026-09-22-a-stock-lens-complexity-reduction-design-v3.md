# A-Stock Lens Complexity Reduction 设计规格（v3）

**日期：** 2026-09-22
**仓库：** `jinking/a-stock-lens`
**审计基线 HEAD：** `fe09b004904fcc6c7883f1abb5aab039b5dc6665`
**上一版基线：** `2149e9ed58565dfa282c92fdecc9b7b4be70328a`
**性质：** 无行为变化的复杂度收敛 / Test Suite Consolidation
**状态：** Revised after Trade Gate landing

## 1. 为什么升级到 v3

v2 Spec 完成后，`main` 又前进了 4 个 commit：

```text
65e1a117  设计：westock 替换 AkShare 当 bulk daily bars 的规格文档
d0abf1b8  交易准入：建立领域模型与受控词表
c0c0034e  交易准入：增加三套策略画像配置
fe09b004  交易准入：增加两阶段论点审计适配器
```

相较旧基线新增：

```text
configs/trade_gate/
src/astock_lens/trade_gate/
tests/unit/test_trade_gate_*.py
docs/superpowers/specs/2026-09-22-westock-bulk-bars-design.md
```

因此 v2 的两条表述需要修订：

1. “V1 不新增一级领域 package”不能再机械套用，因为 `trade_gate/` 已经成为当前 `main` 的既有事实；
2. Complexity Reduction 的基线必须切到 `fe09b004...`，否则后续“测试减少”“文件减少”和行为 hash 比较都会失真。

---

# 2. 当前规模（新基线）

GitHub tree 在 `fe09b004...` 上：

```text
Python production files      = 148
Python production source     ≈ 813,867 bytes

Python test files            = 123
Python test source           ≈ 995,044 bytes

Trade Gate Python files      = 6
Trade Gate source            ≈ 14,447 bytes

Trade Gate test files        = 3
Trade Gate test source       ≈ 4,242 bytes
```

与旧基线相比：

```text
production files   +6
test files         +3
production bytes   +~14 KB
test bytes         +~4 KB
```

具体 pytest collected case 数必须由执行 Agent 在 Task 0 本地真实采集，不能从文件数推断。

---

# 3. 当前真实架构：两个 bounded context

v3 不再把所有能力画成一条越来越长的链。

## 3.1 Stock Discovery / Research Context

保持现有核心链：

```text
Provider
→ Raw / Normalized
→ Universe
→ Factor
→ Strategy
→ Qualification
→ Market Regime
→ Market Validation
→ Signal
→ Candidate
→ Watchlist / Research
```

它回答：

> 哪些股票值得进入研究与持续跟踪范围？

## 3.2 Trade Gate Context

新提交的 `trade_gate/` 是另一个 bounded context：

```text
Candidate / Research facts
        +
User Trade Intent
        +
Current Market Overlay
        ↓
Independent Assessment
        ↓
Thesis Audit
        ↓
Profile / Veto / Risk Evaluation
        ↓
TradeDecision
        ↓
TradePlan / Override / Execution / Review
```

它回答：

> 已经有研究结论之后，这一个具体 ENTRY / ADD 意图能否通过交易准入？

这两个上下文不能揉成一个总分。

### 明确边界

Trade Gate：

- 可以读取 Candidate / Factor / Strategy / MarketValidation / Signal 等已生成事实；
- 可以接收用户 thesis、风险计划和实时 overlay；
- 不重新计算 Factor；
- 不重新实现 Strategy；
- 不改变 Candidate 选股结果；
- 不进入 `astock daily` 的正式扫描 stage；
- 不成为 Candidate 是否入选的上游条件。

这条边界是 v3 新增的最重要架构约束。

---

# 4. Trade Gate 当前状态判定

当前 `trade_gate/` 已存在：

```text
models.py
profiles.py
audit/contracts.py
audit/cli.py
```

以及三套配置：

```text
EVENT
SWING
POSITION
```

现有领域模型已经覆盖：

```text
TradeIntent
TradeRiskProposal
ExistingPositionSnapshot
TradeMarketOverlay
TradeContext
IndependentAssessment
ThesisAuditResult
VetoResult
DimensionScore
TradeGateEvaluation
TradePlan
OverrideRecord
ExecutionRecord
TradeReview
```

当前测试覆盖的是：

```text
领域受控词表 / 时间与风险模型
Profile 配置与权重约束
两阶段审计 Adapter 契约
```

但从当前提交本身看，尚不能据此声称：

```text
完整 Evaluation Engine 已接线
Trade Gate CLI 已成为用户命令
TradePlan / Execution / Review 已持久化
Trade Gate 已进入 daily pipeline
```

本轮 Complexity Reduction 不替它补齐这些功能，也不删掉它。

---

# 5. 本轮双目标保持不变

## A. Production Complexity Reduction

```text
删除 Qualification 重复实现
拆解 CLI God File
冻结 Pipeline
同步文档真实状态
```

## B. Test Suite Complexity Reduction

```text
建立 Test Ownership
删除跨层重复证明
合并无信息增量的参数 Case
禁止纯重构继续新增测试
建立永久 Test Delta Budget
```

完成后仍要求：

```text
相同 Stock Discovery 输入
→ 相同 Factor
→ 相同 StrategyResult
→ 相同 Qualification
→ 相同 MarketValidation
→ 相同 Signal
→ 相同 Candidate

相同 Trade Gate 输入
→ 现有已实现模型 / Profile / Adapter 行为不变
```

---

# 6. 新的硬约束

## 6.1 基线以最新 main 为准

所有 before/after：

```text
test count
test bytes
source bytes
CLI output
snapshot hash
```

都从 `fe09b004...` 或执行时更新后的最新 main 重采集。

禁止继续使用 `2149e9e` 作为优化基线。

## 6.2 当前已有顶层领域包冻结

v3 的规则从：

> V1 不新增一级领域包

修改为：

> **本轮不再新增任何“当前基线之外”的一级领域包。**

`trade_gate/` 作为已经落地的当前域被 grandfathered，不在本轮删除。

新的一级域仍需满足：

```text
现有域无法表达
至少两个真实独立用例
独立生命周期
独立失败语义
独立持久化或测试必要性
```

## 6.3 Trade Gate 暂时冻结

本轮禁止：

```text
增加 TradeGateEvaluator
增加 TradeGate Pipeline Stage
增加 execution 持久化
增加 broker integration
增加新的 TradeProfile
修改 PASS/WAIT/NO_TRADE 语义
修改 80/70 阈值
修改现有 veto 业务含义
```

除非只是为了修复本轮重构导致的 import 问题。

## 6.4 Test Case 不得净增长

本轮：

```text
final pytest collected <= baseline pytest collected
```

纯重构：

```text
new behavior tests = 0
```

Trade Gate 新加入的 3 个测试文件视为基线的一部分，不在本轮为了“凑减少数字”删除。

---

# 7. Trade Gate Test Ownership

新增到 Test Ownership Matrix：

| Rule family | Authoritative test |
| --- | --- |
| Trade Gate vocab / TradeIntent / TradeRiskProposal invariants | `tests/unit/test_trade_gate_models.py` |
| Trade Profile YAML / fixed thresholds / weight total | `tests/unit/test_trade_gate_profiles.py` |
| Thesis Audit phase isolation / adapter output / confidence adjustment | `tests/unit/test_trade_gate_audit_adapter.py` |

这三组当前属于高信息量测试。

本轮默认：

```text
KEEP
```

理由：

- 模型不变量、配置合同、外部 Adapter 契约是三种不同失败类型；
- 当前每个文件 case 数很少；
- 尚未出现跨 Unit / Integration / API / Web 多层重复；
- 新域刚落地，不适合立即以“测试瘦身”为理由削弱安全网。

---

# 8. Qualification 去重复

方案与 v2 保持：

```text
6 YAML
→ FactorThresholdRule
→ ConfiguredQualifier
→ build_qualification()
```

六个原 concrete Qualifier 只保留 thin compatibility wrapper。

本轮不改变：

```text
TOP 10% percentile gate
absolute thresholds
fail-closed
qualification_version
StrategyQualification schema
```

**Test Delta Budget：**

```text
新增 0
净 collected case <= 0
```

---

# 9. CLI 拆分：新增并发开发约束

当前 `cli/app.py` 仍是主要 complexity hotspot。

目标仍是：

```text
cli/
├── app.py
├── runtime.py
├── data_commands.py
├── pipeline_commands.py
├── discovery_commands.py
├── lifecycle_commands.py
└── calibration_commands.py
```

其中：

```text
_bulk_provider()
```

在重构后应进入：

```text
cli/runtime.py
```

而不是继续留在 `cli/app.py`。

这会影响新加入的 Westock 设计稿，因此必须协调执行顺序。

---

# 10. Westock Bulk Bars：与本轮的关系

当前仓库新增：

```text
docs/superpowers/specs/2026-09-22-westock-bulk-bars-design.md
```

它是 **Feature Design**，不是本轮 Complexity Reduction 的组成部分。

## 10.1 不并行实施

Westock 实现与 Complexity Reduction 都会碰：

```text
cli/app.py / _bulk_provider
Provider composition
CLI tests
```

因此禁止两个 Agent 同时执行。

推荐顺序：

```text
Complexity Reduction
→ CLI boundary 稳定
→ 更新 Westock Spec / Implementation Plan
→ 再实现 WestockBarsProvider
```

如果业务上必须 Westock 先做，则反过来：

```text
Westock feature 完成并合并
→ 重新采 Complexity Reduction baseline
→ 再执行本计划
```

不能拿旧 baseline 硬跑。

## 10.2 Westock 测试策略必须重新过 Test Delta Budget

当前 Westock 设计稿预列：

```text
9 unit tests
6 contract tests
```

这只是设计候选，不应自动等于最终新增 15 个 collected cases。

后续 Implementation Plan 必须先审计：

```text
现有 DataProvider contract tests
现有 WestockCliProvider tests
现有 provider health/error tests
现有 bulk provider factory tests
```

再决定最小新增量。

原则：

```text
新 Provider 的独有字段转换 / 单位陷阱
→ 需要新增测试

已有 DataProvider 通用 contract
→ 优先复用/参数化现有 contract suite

CLI factory 行为
→ 若现有 factory contract 可扩展，不新建重复测试文件
```

Westock 是新业务行为，因此可以净新增测试，但必须说明信息增量，而不是机械按“一个断言一个 case”增长。

---

# 11. Test Suite Reduction 主任务

与 v2 相同，但基线新增 Trade Gate 后，审计范围调整为：

```text
candidate*
qualification*
market*
signal*
cli*
bootstrap*
calibration*
provider*
trade_gate*
artifact*
```

## 第一批确定可收敛对象

仍保留 v2 已确认的重复项：

```text
Candidate Policy score rejection 重复
Candidate Routing tautological purity case
Candidate Routing 5 个同一 hasattr 参数 case
MarketValidation standalone missing-liquidity 重复 case
Qualification six concrete implementation 测试
```

Trade Gate 当前不加入第一批删除对象。

---

# 12. Pipeline Freeze

`daily.py` 与 `stages.py` 继续冻结。

特别明确：

```text
Trade Gate 不进入 Daily Stage
```

禁止增加：

```text
EVALUATE_TRADE_GATE
RUN_THESIS_AUDIT
BUILD_TRADE_PLAN
```

Daily pipeline 是股票发现/研究生产链，不是具体交易意图生命周期。

---

# 13. 文档收敛新增内容

本轮更新 `docs/ARCHITECTURE.md` 时，需要明确画出：

```text
Stock Discovery Context
Trade Gate Context
```

而不是把 Trade Gate 继续接在 daily pipeline 第 12、13、14 阶段后面。

同时新增 Testing Architecture：

```text
Test Ownership
Pure Refactor Rule
Test Delta Budget
新测试四类合法理由
```

README 只说明“当前已经稳定可用”的功能。

Trade Gate 若当前没有用户入口，不得在 README 写成“已完成交易准入产品”。

---

# 14. 更新后的实施顺序

```text
Task 0
以 fe09b004... 或最新 main 重新冻结 Production + Test Baseline

Task 1
Test Ownership Audit
+ 新增 Trade Gate ownership
+ Westock concurrency note

Task 2
Qualification 通用化

Task 3
CLI Discovery / Lifecycle 拆分

Task 4
CLI Data / Pipeline / Calibration 拆分
+ _bulk_provider 移到 runtime.py

Task 5
已证明重复的 Candidate / Routing / MarketValidation tests 收敛

Task 6
第二轮测试 cluster 审计
Trade Gate 默认 KEEP

Task 7
ARCHITECTURE / README / PROGRESS 收敛
+ 两 bounded contexts
+ Testing Architecture
+ Westock spec 后续迁移说明

Task 8
全量行为 / Snapshot / CLI / Test Count 验收

Task 9
Review Gate
```

---

# 15. 验收标准

## Stock Discovery 行为

```text
Factor unchanged
Strategy unchanged
Qualification unchanged
MarketValidation unchanged
Signal unchanged
Candidate unchanged
Snapshot schema unchanged
CLI/API/Web contract unchanged
```

## Trade Gate 当前行为

```text
Trade enums unchanged
TradeIntent / TradeRiskProposal validation unchanged
Trade Profile loading unchanged
EVENT/SWING/POSITION config unchanged
CliThesisAuditAdapter phase isolation unchanged
adjusted_ratio unchanged
```

## 工程复杂度

```text
Qualification 重复实现收敛
CLI God File 消失
Pipeline 未重写
没有再新增新的顶层领域域
Trade Gate 没被偷偷塞进 daily
```

## 测试复杂度

```text
final collected <= latest baseline
pure refactor new behavior tests = 0
Trade Gate 三个现有测试文件保留
第一批已证明重复 coverage 被删除/合并
每条规则拥有权威测试层
```

## 并发 Feature 安全

```text
Westock 实现不与 CLI complexity refactor 并行
Westock 后续 plan 重新做 Test Delta Budget
Westock spec 中 _bulk_provider 位置在 CLI 拆分后更新
```

---

# 16. 最终原则

这次新提交没有推翻 Complexity Reduction 的方向，反而证明它更有必要。

系统现在已经不是单一“选股工具”，而开始出现两个业务上下文：

```text
研究什么股票
vs
具体这笔交易该不该放行
```

正确做法不是把新能力砍掉，也不是继续把所有东西塞进一条 Pipeline。

正确做法是：

> **承认已经形成的新边界，把边界钉死；同时停止无上限新增顶层概念和重复测试。**

本轮 Complexity Reduction 的目标仍然是：

> **同样的能力，更少重复实现；同样的安全性，更少重复证明。**
