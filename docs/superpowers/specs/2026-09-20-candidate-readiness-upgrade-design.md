# Candidate Readiness Upgrade 设计规格

**日期：** 2026-09-20  
**状态：** 当前阶段执行基线

## 目标

把 2026-09-19 已补齐的估值 Raw 数据正式送入 Factor / Strategy Snapshot，并生成可供项目所有者审批六策略绝对质量门槛的决策级 Calibration 证据；在审批前不发布 Candidate。

## 当前事实

- Stock Discovery MVP 已完成，可通过 CLI/API 查询策略榜单与单股画像。
- Research Universe 基线：2,303 只。
- 2026-09-19 neodata valuation Raw：2,241 / 2,303，覆盖 97.3%。
- 估值覆盖报告：Value 估值侧交集 1,578，GARP 850。
- 新估值 Raw 尚未重算进正式 Factor / Strategy Snapshot。
- 默认分析路径仍是 `CsvNormalizedRepository`，因此无需先完成 Parquet/DuckDB 迁移即可消费新 Raw。
- Candidate Qualification 基础设施已存在，但六策略绝对质量规则未批准。
- Market Regime / Market Validation / Signal 未实现。
- 正式 Candidate Publishing 必须继续 BLOCKED。

## 本阶段最终产物

1. 一个新的、与 2026-09-19 估值数据一致的只读 Research Analysis 基线。
2. 同一 `as_of` 的正式 FACTOR / UNIVERSE / STRATEGY Snapshot。
3. `astock screen value` / `garp` 真正读取新的正式策略结果。
4. 六策略最新 Calibration Report。
5. 一份 Owner Decision Packet，展示六策略边界、分布、异常和门槛备选，但不替所有者选择。
6. Candidate 继续未发布。

## Point-in-Time 原则

```text
as_of=2026-09-17
→ valuation loader 不可读取 2026-09-19.csv

as_of>=2026-09-19
→ 可读取不晚于 as_of 的最新 valuation raw
```

禁止修改冻结的：

```text
data/raw/neodata/valuation/2026-09-17.csv
```

禁止为了更新榜单覆盖已有的历史正式 Snapshot。

## 正式 Snapshot 发布语义

```text
Raw
→ CsvNormalizedRepository
→ run_research_analysis          # 只读预演
→ 验证
→ astock daily --allow-incomplete
→ FACTOR / UNIVERSE / STRATEGY Snapshot
```

如果目标 `as_of` 已存在内容不同的正式 Snapshot：

```text
STOP
```

不得关闭 `SnapshotConflictError`。

## Storage Migration 不阻塞本阶段

本阶段不运行：

```text
scripts/migrate_storage.py
```

因为当前业务默认读取仍是 CSV Repository；存储迁移是独立工程任务。

## Strategy Discovery 验收

新的正式 Snapshot 发布后，六个现有策略都必须可查询：

```bash
astock screen growth
astock screen momentum
astock screen quality
astock screen dividend
astock screen value
astock screen garp
```

每个榜单显示真实 total / eligible / scored / ranked。

禁止规定 Value/GARP 必须达到某个人工覆盖百分比；如果仍接近补抓前的个位数水平，视为数据没有进入正式分析链，进入调试而不是调整策略规则。

## Calibration 决策级证据

最终 Calibration 必须与正式 Strategy Snapshot 使用同一：

- `as_of`
- Research Universe
- Factor config
- Strategy config
- valuation raw
- industry evidence

每策略至少展示：

- evaluable / ranked count
- Top-10% 边界
- boundary strategy score
- Top 样本
- 0.90 边界上下样本
- factor 值与 DataStatus
- factor p10/p25/p50/p75/p90/p95
- 行业集中度
- 跨策略 overlap

重点异常单独呈现：

```text
Growth 极端增长值
Dividend payout 异常高值
PEG 正负值与尺度问题
Value / GARP 实际可评分分母
```

## Industry Coverage Gate

最终“可审批”的 Calibration 必须使用 canonical industry evidence。

如果仍有权威来源无法补齐的行业缺口：

- 可以生成 `diagnostic_only` 报告；
- 不得称为最终审批报告；
- 不得手工猜行业；
- 必须列出缺失 symbols。

## Absolute Qualification Gate

本阶段禁止创建：

```text
configs/qualifications/value.yaml
configs/qualifications/growth.yaml
configs/qualifications/garp.yaml
configs/qualifications/quality.yaml
configs/qualifications/dividend.yaml
configs/qualifications/momentum.yaml
```

Agent 可以在 Decision Packet 中提出 2–3 组门槛方案及预计影响，但必须标注：

```text
PROPOSAL ONLY — NOT APPROVED PRODUCT RULE
```

不得选择“推荐方案”，不得写入生产配置。

## Candidate Gate

本阶段不得：

- 伪造 `MarketValidation.NEUTRAL`
- 伪造 `Signal.NO_SIGNAL`
- 绕过 `_blocked_reasons()`
- 将 Strategy Top-N 包装为 Candidate
- 发布 CANDIDATE Snapshot

允许并期望：

```text
FACTOR / UNIVERSE / STRATEGY 成功
DETECT_REGIME / MARKET_VALIDATE / RUN_SIGNALS / BUILD_CANDIDATES 继续 BLOCKED
```

## 完成定义

正确完成定义：

> 六策略正式 Stock Discovery 已更新到最新估值数据；决策级 Candidate Qualification 校准材料已经准备好；等待所有者审批绝对质量规则以及后续 Market/Signal 规则。
