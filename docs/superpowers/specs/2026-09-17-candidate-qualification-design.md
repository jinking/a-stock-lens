# Candidate Qualification 设计规格

**日期：** 2026-09-17  
**状态：** 已获项目所有者批准，等待实施计划  
**范围：** Candidate Qualification、跨策略候选池选择、校准证据  
**不包含：** Market Regime 阈值、Market Validation 具体判定阈值、Signal 具体检测阈值、各策略绝对质量门槛的最终数值

---

## 1. 目标

把全市场 StrategyResult 收敛成一组**少量、可解释、可复现的 Research Candidate**，同时保持以下边界：

1. Candidate 是研究对象，不是投资推荐；
2. Strategy 负责测量一只股票在某种策略视角下表现如何，不负责跨策略最终入选；
3. 不创建跨策略总分；
4. 不把“有分数”“数据完整”误当成“值得研究”；
5. 缺失的上游判定必须保持缺失，不能伪装成 NEUTRAL / NO_SIGNAL；
6. 最终候选池希望通常落在 20–50 只，但质量优先于数量。

当前代码已经建立 `CandidatePolicy` 边界，并删除了“eligible 且有 score 就 WATCH”的旧隐式规则。本规格确认该边界的正式产品语义，并把它扩展为可处理全市场配额、去重和总量控制的横截面选择规则。

---

## 2. 已批准的产品裁决

### 2.1 候选池数量

- 日常目标区间：**20–50 只**；
- **50 只是硬上限**；
- **20 不是硬下限**；
- 如果当天只有 12 只真正满足质量要求，就只发布 12 只；
- 禁止为了凑够 20 只而降低 percentile、放宽绝对门槛或绕过 Market Validation。

### 2.2 多策略代表性

- 每个已启用、可运行的策略具有 **3 只软保底**；
- “软保底”不是强制塞满：该策略只有 1 只合格，就只保留 1 只；
- 先分别取得每个策略内排名最高的至多 3 只合格股票，再做全局去重；
- 同一股票可以同时代表多个策略，但最终只能产生一个 Candidate；
- 去重后的剩余名额，再从所有尚未入选的合格股票中按全局优先级补入，直到没有更多合格股票或达到 50 只。

当前 6 个可运行策略理论上最多产生 18 个“策略软保底槽位”，但去重后实际唯一股票数可能少于 18；未来 Industry Trend 上线后同样使用该机制。

### 2.3 策略内资格线

每个策略的 Strategy Qualification 采用**双门槛**：

1. **绝对质量门槛通过**；
2. **该策略横截面 Top 10% 通过**。

二者必须同时成立。

Top 10% 是“进入策略候选资格池”的门槛，不代表直接成为最终 Candidate。

对于当前 `rank_percentile` 采用“越高越好”的策略，Top 10% 的目标语义为：

```text
rank_percentile >= 0.90
```

如果某个未来策略的排序方向或 percentile 语义不同，必须由该策略适配为统一的“越高越好”资格语义后才能进入 Candidate 层，CandidatePolicy 不负责猜测方向。

### 2.4 绝对质量门槛的批准方式

本规格**不批准任何具体绝对阈值**。

禁止现在直接写入类似：

- ROE > 15%；
- PE < 20；
- 净利润增长 > 20%；
- 股息率 > 3%。

原因是当前全市场真实数据尚未完成完整校准，不应在不了解真实分布、异常值和边界样本时凭经验定常数。

必须先运行 Calibration Report，再由项目所有者逐策略批准 Value / Growth / GARP / Quality / Dividend / Momentum 的绝对质量线。

在绝对质量线批准前，正式 Candidate 发布继续保持 `BLOCKED`。

---

## 3. 责任边界

正式链路调整为：

```text
StrategyResult
    ↓
StrategyQualification
    ↓
CandidateEvidence
    ↓
CandidatePolicy（横截面选择）
    ↓
Candidate
```

### 3.1 StrategyResult

职责：**测量**。

继续回答：

- 当前股票是否具备该策略所需的数据与基本 eligibility；
- score 是多少；
- rank_percentile 是多少；
- 哪些 factor 产生了贡献；
- 有哪些 reasons / risks。

StrategyResult 不回答“是否进入最终 Candidate”。

现有 `eligible` 保持“该策略是否可评估/满足该策略基础计算条件”的语义，不重新塞入最终 Candidate 资格含义。

### 3.2 StrategyQualification

职责：**判断一只股票是否达到某个策略的最低研究标准**。

它与 StrategyResult 分离，避免重新把“测量”和“产品选择”混成一个概念。

建议领域模型至少包含：

```text
symbol
strategy_id
strategy_version
qualification_version
qualified
percentile_pass
absolute_pass
rank_percentile
reasons
risks
```

其中：

- `percentile_pass`：是否满足 Top 10%；
- `absolute_pass`：是否满足该策略已批准的绝对质量门槛；
- `qualified`：两者均通过；
- `qualification_version`：保证以后调整门槛时可复现历史结果。

### 3.3 StrategyQualifier

每个策略拥有自己的 Qualification 语义。

例如：

```text
ValueQualifier
GrowthQualifier
GarpQualifier
QualityQualifier
DividendQualifier
MomentumQualifier
IndustryTrendQualifier（未来）
```

Qualifier 可以复用公共的 percentile 检查工具，但**禁止**重新做成一个“万能 YAML 规则 DSL”。策略的绝对规则仍然应由策略自己的代码边界表达，配置只保存已批准的数字参数和版本。

推荐方向：

```text
configs/qualifications/value.yaml
configs/qualifications/growth.yaml
...
```

配置负责参数，Qualifier 类负责语义。

### 3.4 CandidatePolicy

职责：**跨策略汇总与候选池控制**。

CandidatePolicy 不重新计算 factor，不重新解释某个策略为什么好，也不创建跨策略总分。

它只负责：

- 接收各策略已经给出的 StrategyQualification；
- 应用 Market Validation 否决规则；
- 保证策略软代表性；
- 全局去重；
- 按批准的优先级排序；
- 执行 50 只硬上限。

因为软保底和 50 只上限都需要看到整个横截面，当前逐股票的：

```text
CandidatePolicy.qualify(one symbol)
```

接口不足以承担正式规则。

实施时应把 CandidatePolicy 升级成**横截面 selection policy**，即一次看到全市场已经完成 Qualification 的 CandidateEvidence，再返回 Selection 结果。

不要把配额逻辑偷偷放进 pipeline 循环或 CandidateBuilder。

### 3.5 CandidateBuilder

CandidateBuilder 继续只负责组装已批准的证据，不承担选择规则。

当前“Policy qualified → WATCH；未入选 → IGNORE”的路由语义可以保留。

`DEEP_RESEARCH` 与 `TRACK_SIGNAL` 的触发条件不属于本规格，继续等待 Signal / Research 生命周期规则批准。

---

## 4. Market Validation 与 Signal

### 4.1 Market Validation

已批准规则：

```text
CONTRADICTED → 否决 Candidate
CONFIRMED    → 允许进入 Candidate 选择
NEUTRAL      → 允许进入 Candidate 选择
```

重要区别：

```text
market_validation is None
```

不能解释为 `NEUTRAL`。

`None` 表示上游 Market Validation 尚未运行或没有产生结论；正式 daily pipeline 在这种情况下不得发布 Candidate，应保持该阶段 `BLOCKED` / incomplete。

### 4.2 Signal

Signal **不是 Candidate 资格硬门槛**。

因此：

```text
NO_SIGNAL
```

仍然可以成为 Research Candidate，只是优先级较低或保持观察。

但：

```text
signal is None
```

不等于 `NO_SIGNAL`。

`None` 表示 Signal Engine 没有运行或没有形成结果，仍属于上游不完整。

Signal 可以作为最终排序的最后一级提示，但本规格**不批准 BREAKOUT / PULLBACK / TREND_CONTINUE / ... 之间的具体高低顺序**。该顺序必须在 Signal 规则自身获得批准后再加入；在此之前不得擅自猜测。

---

## 5. CandidatePolicy 选择算法

### 5.1 输入

对每个 symbol，CandidatePolicy 需要看到一份 CandidateEvidence，至少包含：

```text
symbol
strategy_qualifications[]
market_validation
signal
```

只考虑：

- 至少一个 `StrategyQualification.qualified == True`；
- `market_validation` 为 CONFIRMED 或 NEUTRAL；
- 正式 pipeline 已经确认上游阶段完整。

### 5.2 第一步：Market Validation 否决

任何 `CONTRADICTED` 股票直接从 Candidate 池排除。

该否决不能被：

- 很高的策略排名；
- 多策略命中；
- soft quota；

覆盖。

### 5.3 第二步：策略软保底

对每个 enabled strategy：

1. 取该策略中 `qualified == True` 的股票；
2. 按该策略自己的 `rank_percentile` 从高到低排序；
3. 取最多 3 只；
4. 所有策略结果做 union；
5. 按 symbol 去重。

如果某策略只有 2 只合格，就只贡献 2 只；禁止向下放宽门槛补足 3 只。

### 5.4 第三步：全局补位

将尚未入选、但至少通过一个 StrategyQualification 的股票放入剩余池。

按全局优先级排序，依次补入，直到：

- 没有更多合格股票；或
- 唯一 Candidate 数达到 50。

### 5.5 不设置 20 只补足逻辑

如果最终只有 12 只：

```text
Candidate count = 12
```

这是合法结果，不是失败。

系统应该说明“今天只有 12 只通过全部已批准规则”，而不是放宽质量条件。

---

## 6. 多策略命中与全局优先级

同一股票命中多个策略：

- 最终只产生一个 Candidate；
- Candidate 保留全部通过的 StrategyQualification / StrategyResult；
- 多策略命中有轻度优先权；
- **绝不把不同策略 score 相加、平均或加权成一个 global_score**。

最终优先级使用**字典序排序**，而不是综合分：

1. **最佳单策略 `rank_percentile`**：高者优先；
2. **通过 Qualification 的策略数量**：多者优先；
3. **Market Validation**：`CONFIRMED` 优先于 `NEUTRAL`；
4. **Signal priority**：只在 Signal 层正式批准其顺序后启用；
5. **symbol**：仅作为确定性最终 tie-breaker，保证同一输入得到同一顺序，不表达投资偏好。

形式化表达：

```text
priority_key = (
    best_strategy_rank_percentile DESC,
    qualified_strategy_count DESC,
    market_validation_priority DESC,
    approved_signal_priority DESC,   # 未批准前禁用
    symbol ASC,
)
```

这样可以保证：

- 一个在单一策略里极强的股票不会因为只命中一个策略就被大幅降级；
- 多策略共振只作为第二排序键；
- 不重新制造跨策略总分。

---

## 7. Calibration Gate

正式批准绝对质量门槛前，必须先生成全市场 Calibration Report。

### 7.1 每个策略必须输出

对 Value / Growth / GARP / Quality / Dividend / Momentum 分别输出：

1. 可评估股票数；
2. 有 score / rank 的股票数；
3. score 与 rank_percentile 的分布；
4. Top 10% 的实际边界；
5. 主要 factor 的全市场分布；
6. Top 样本；
7. Top 10% 边界附近样本；
8. 异常值样本；
9. 行业分布与集中度；
10. 与其他策略的命中重合情况。

### 7.2 必须重点暴露当前已知异常

至少包括：

- Growth 极端增长率（例如数千到数万百分比）；
- Dividend 超高 payout ratio；
- PEG 异常值域与负值；
- 缺失值 / stale / source_error 对策略人口的影响。

报告不能只给统计表，还必须给可人工阅读的 symbol 样本，尤其是：

```text
头部样本
Top 10% 边界上方样本
Top 10% 边界下方样本
异常值样本
```

### 7.3 门槛敏感性

Calibration Report 应提供“候选门槛变化 → 合格数量变化”的敏感性曲线或表格。

这些情景只用于帮助所有者决策，不代表 Agent 获准选择其中任何一个阈值。

Agent 可以枚举数据驱动的候选切点并报告影响，但必须标注：

```text
CALIBRATION ONLY — NOT APPROVED PRODUCT RULE
```

### 7.4 Gate 关闭条件

只有当项目所有者逐策略批准绝对质量规则与版本后，才能：

1. 写入正式 qualification config；
2. 启用对应 StrategyQualifier；
3. 解除 CandidatePolicy 的“绝对门槛未批准”阻塞；
4. 允许 daily pipeline 发布正式 Candidate snapshot。

---

## 8. 版本与可复现性

Strategy Qualification 是产品判断，必须版本化。

历史 Candidate 至少必须能够追溯：

```text
strategy_id
strategy_version
qualification_version
candidate_policy_version
market/signal evidence version（当对应模块实现后）
```

改变以下任何一项都必须升级相应版本：

- 绝对质量阈值；
- percentile 门槛（当前为 Top 10%）；
- soft reserve（当前 3）；
- max candidates（当前 50）；
- Candidate 优先级规则；
- Market Validation 的 Candidate 否决语义。

禁止在不改版本的情况下改变历史选择语义。

---

## 9. 失败与阻塞语义

以下情况不允许发布 Candidate snapshot：

1. 某启用策略需要 Qualification，但其绝对规则尚未批准；
2. Market Validation 阶段未实现 / 未运行；
3. Signal 阶段未实现 / 未运行，而 canonical daily 仍声明该阶段是 Candidate 上游必经层；
4. CandidatePolicy 未配置；
5. 输入 lineage / version 不一致。

这些都属于：

```text
BLOCKED / incomplete
```

而不是：

```text
0 candidates
```

真正的“0 candidates”只能表示：所有必需模块都成功运行，但当天没有任何股票通过已批准规则。

---

## 10. 测试设计

实施时必须覆盖以下独立测试层。

### 10.1 StrategyQualification 单元测试

每个策略至少验证：

- percentile < 0.90 → 不通过；
- percentile >= 0.90，但 absolute gate 不通过 → 不通过；
- percentile >= 0.90 且 absolute gate 通过 → 通过；
- 缺失必要 evidence → 显式失败/不通过，不用 0 补；
- qualification_version 写入结果。

### 10.2 CandidatePolicy 单元测试

必须验证：

- 每策略最多软保底 3；
- 不足 3 不凑数；
- 多策略同 symbol 去重；
- 同一 symbol 可以保留多个 qualification；
- CONTRADICTED 一票否决；
- CONFIRMED > NEUTRAL；
- 最佳单策略排名优先于命中策略数量；
- 多策略数量仅作为第二排序键；
- 超过 50 时严格截断；
- 少于 20 时不放宽规则；
- 相同输入重复执行顺序完全一致。

### 10.3 Pipeline 集成测试

必须验证：

- qualification thresholds 未批准 → BUILD_CANDIDATES = BLOCKED；
- Market Validation 缺失 → BLOCKED，而不是 NEUTRAL；
- Signal 缺失 → BLOCKED，而不是 NO_SIGNAL；
- NO_SIGNAL 仍可产生 Candidate；
- 完整运行后 Candidate snapshot 只包含 policy 选中的唯一 symbol；
- snapshot 中能追溯 strategy / qualification / policy 版本。

### 10.4 Artifact Validator

独立校验器应增加：

- Candidate 必须至少引用一个 `qualified == True` 的 StrategyQualification；
- Candidate 不得携带 `MarketValidation.CONTRADICTED`；
- qualification_version / policy_version 不得缺失；
- 同一 Candidate snapshot 中 symbol 唯一；
- Candidate 数不得超过 50；
- Candidate 引用的 StrategyResult / qualification 必须在对应快照或证据集中存在。

---

## 11. 非目标

本轮明确不做：

- 不决定 Value / Growth / GARP / Quality / Dividend / Momentum 的具体绝对阈值；
- 不决定 Market Regime 阈值；
- 不决定 Market Validation 五项输入的判定算法；
- 不决定 Signal 检测阈值；
- 不决定各 Signal 类型之间的最终优先级；
- 不实现 Web 页面；
- 不增加新的策略或因子；
- 不引入机器学习模型自动学习 Candidate 资格；
- 不创建跨策略 global_score。

---

## 12. 验收标准

Candidate Qualification 设计只有在以下条件满足后才算真正落地：

1. `StrategyResult → StrategyQualification → CandidatePolicy → Candidate` 边界在代码中清晰存在；
2. 每个策略有独立 Qualifier，而不是万能规则引擎；
3. Top 10% 规则有显式测试；
4. 每策略 3 只软保底有显式测试；
5. 全局 Candidate 上限 50 有显式测试；
6. 少于 20 时不会自动放宽标准；
7. 多策略同股票只产生一个 Candidate；
8. 最佳单策略排名优先，多策略命中仅为第二排序键；
9. `CONTRADICTED` 无法进入 Candidate；
10. `None` 与 `NEUTRAL` / `NO_SIGNAL` 不混淆；
11. Calibration Report 能支撑所有者逐策略批准绝对门槛；
12. 在绝对门槛正式批准以前，生产 Candidate 仍保持 BLOCKED；
13. 全部选择规则具备明确版本，可复现历史结果。

---

## 13. 本规格形成的最终原则

一句话概括：

> **策略负责测量，Qualifier 负责证明“值得研究”，CandidatePolicy 负责从多个已证明合格的策略视角中构造一个有限、去重、有代表性的研究池；任何数量目标都不能反过来迫使系统降低质量门槛。**
