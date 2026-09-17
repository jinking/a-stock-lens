# 数据来源（V1）

## 1. 两层分工

```text
批量扫描 / 选股                     研究增强
-----------------------            --------------------------
AkShare                            a-share-deep-research
腾讯 WeStock CLI（三大表）           ├─ westock-npm
交易所公开数据                       ├─ westock-npm
免费备用源                           ├─ westock-cli
                                    └─ neodata
```

全市场批量扫描只使用免费或公开数据源。深度研究阶段不重复造数据层，而是通过适配器使用现有 `a-share-deep-research`。

2026-09-16 补遗（设计规格 §24）：财务三大表的 bulk 源是腾讯 WeStock CLI——它同时给出
`EndDate`（报告期）与 `InfoPublDate`（公告日期），并支持批量拉取（100 只 11 秒，实测）；
进入系统的路径仍是 Provider → Raw → Normalized → Quality Gate。

2026-09-17 修订（设计规格 §24.1）：`neodata` **已升为一等 Provider**，不再是研究侧专属。
它是估值、行业/板块与语义三类主数据的来源，并作为财报的交叉验证源；不做标的枚举（名单
由 AkShare 提供），查询措辞固化成 Provider 内模板，凭证 12 小时有效且由平台侧刷新。
全市场估值走"按板块迭代"的批量路径。上面 Provider 分层图里它同样属于批量/筛选一侧。

## 2. Provider 分层

- `Raw`：尽量保留数据源原貌，并保存抓取元信息（`provider`、`dataset`、`fetched_at`、`trade_date` / `report_period`、`provider_version`、`status`、`row_count`）。
- `Normalized`：转换为系统 Canonical Schema。Factor Engine 只允许读取 Normalized Data。
- `Data Quality Gate`：Raw → Normalized 之后的质量校验，`close <= 0`、`volume < 0`、缺少 `announce_date`、极端估值、重复主键等都会被标记为 `INVALID`，而不是静默修正。

## 3. 存储

- Parquet：历史与高频时序数据；
- DuckDB：元数据、查询、Factor / Strategy 快照、Watchlist、Job State。

PostgreSQL 与 Redis 是 V1 非目标。

## 4. Provider 健康

Provider 与 Dataset 的新鲜度需要在 Data Health 页面与 `astock doctor` 中可见。`ProviderHealth` 记录 `provider`、`healthy`、`status`、`checked_at`、`message`。

## 5. Deferred

- 具体 Provider 的选型顺序与限速策略：`Deferred`。
- 免费备用源的切换条件：`Deferred`。
- AkShare 数据集清单与字段映射表：`Deferred`。
