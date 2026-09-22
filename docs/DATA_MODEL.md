# 数据模型（V1）

本文件只记录设计文档中已确认的模型边界。未确认的部分标为 `Deferred` 或 `Not defined in V1`。

## 1. 时间模型

财务观测必须携带以下时间字段：

| 字段 | 含义 |
| --- | --- |
| `report_period` | 数据所属的报告期 |
| `announce_date` | 公告日期 |
| `available_at` | 该数据实际可被使用的时刻 |
| `as_of` | 本次计算所处的时点 |

强制规则：`available_at <= as_of`。违反时 `FinancialObservation` 直接抛出校验错误，不做修正、不做截断。

`available_at` 与 `as_of` 必须是带时区的 `datetime`：naive 时间戳会因为隐式时区而产生前视偏差，因此被拒绝。

缺少 `announce_date` 的财务记录无法进入时点敏感 Factor；该字段可显式为 `None`，但不提供默认值，调用方必须显式决定。

## 2. 快照血缘与版本

每个派生产物都必须能回答"它是在什么上下文下产生的"。血缘字段预留为：

- `universe_snapshot`
- `factor_version`
- `strategy_version`

产物自身另外携带 `as_of`。

每日扫描完成后保存五类快照：`UNIVERSE`、`FACTOR`、`STRATEGY`、`MARKET_REGIME`、`CANDIDATE`。

已知重复：`FactorResult` 按设计规格同时携带 `factor_version` 字段与 `SnapshotLineage.factor_version`。在快照存储落地前，两者可能不一致；届时以血缘为准。

## 3. 缺失状态

统一使用 6 个显式状态，禁止用 0 表示"没有数据"：

- `VALUE`：有值；
- `NULL`：源数据即为空；
- `STALE`：值过旧，不满足当前 `as_of` 的新鲜度；
- `INVALID`：值存在但不合法（例如 `close <= 0`、`volume < 0`、重复主键）；
- `SOURCE_ERROR`：取数失败；
- `NOT_APPLICABLE`：该指标对当前标的或行业不适用。

## 4. 错误分级

| 级别 | 语义 |
| --- | --- |
| `P0` | 可能污染选股结果，阻断当前扫描 |
| `P1` | 关键数据集不可用，相关模块停止或降级 |
| `P2` | 非关键数据缺失，继续并警告 |
| `P3` | 展示或辅助问题，仅记录 |

## 5. Watchlist 生命周期

V1 活跃路径：

`DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL`

预留状态（V1 不得触达）：`READY`、`HOLDING`、`EXITED`、`ARCHIVED`。

状态变更必须写入 Timeline。每条记录保存 `thesis`、`key_questions`、`risk_conditions`、`waiting_for` 以及 `created_at` / `updated_at`。

## 6. 研究模型

- `ResearchRequest`：`symbol`、`as_of`、`thesis`、`key_questions`、`risk_conditions`、`waiting_for`。
- `ResearchJob`：`job_id`、`symbol`、`submitted_at`。
- `ResearchJobStatus`：`job_id`、`state`、`observed_at`、`is_terminal`、`message`。
- `ResearchSummary`：`job_id`、`symbol`、`completed_at`、`summary`、`artifact_reference`。

`ResearchJobStatus.state` 是自由字符串：任务状态词表属于 `a-share-deep-research`，A-Stock Lens 只做透传，不自行定义。

## 7. Canonical Schema

`DailyBar`：`symbol`、`trade_date`、`open/high/low/close/pre_close`、`volume`、`amount`、`turnover_rate`、`pct_change`、`adj_factor`。

`FinancialObservation`：`symbol`、`metric`、`value`、`unit`、`report_period`、`announce_date`、`available_at`、`as_of`、`source`。

## 8. Trade Gate（增量实现）

- `TradeIntent` 固定一次 ENTRY/ADD 的交易目的、画像、风险提案与创建时刻；所有时间戳带时区。
- `TradeMarketOverlay` 只携带显式输入的交易时点事实；历史日线不得冒充盘中行情。
- `TradeGateEvaluation` 保存画像/规则版本、维度分数、Veto、缺失数据、复入触发条件及上下文。
- JSON Ledger 以记录 ID 追加；相同 ID 同内容幂等、不同内容拒绝覆盖。同一意图可有多次评估。
- `TradePlan`、`OverrideRecord`、`ExecutionRecord`、`TradeReview` 为独立追加记录。Override 必须记录更小仓位上限、证据、止损规则与风险确认。
- PASS 只表示 eligible，不是买入推荐；当前服务不连接券商。

数值字段保持可选，缺失即 `None`；是否可用由 Data Quality Gate 判定，而不是由记录本身猜测。

## 8. Deferred

- `FactorMetadata.frequency` / `direction` / `null_policy` 的取值词表：`Deferred`，设计文档未枚举。
- Golden Dataset 的具体 30–50 只股票清单：`Deferred`。
- `ResearchRequest` 中"触发策略及分数 / Market Validation"的字段形态：`Deferred`，产品文档要求包含，但完整字段集尚未确定。
