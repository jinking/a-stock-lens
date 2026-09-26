# 数据来源（V1）

## 1. 两层分工

```text
批量扫描 / 选股                     研究增强
-----------------------            --------------------------
腾讯 WeStock CLI（日线批量 + 三大表）  a-share-deep-research
AkShare（证券名单、显式回退）           ├─ westock-npm
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

## 6. 日线批量行情

`astock daily --sync` 默认通过已安装的 WeStock CLI 批量获取日线；按每批 100 只打印处理数、成功数、缺失数和待处理数。日线取不复权数据，成交量从”手”换算为股，换手率从百分数换算为小数比例，维持既有 Raw 字段单位。`ASTOCK_BULK_PROVIDER=akshare` 可显式选择 AkShare 日线。

已有 `securities.csv` 时日常同步只读本地名单缓存；冷启动或显式 `astock sync` 更新名单时使用 AkShare。两种 CLI 底层都访问腾讯行情接口，因此这次切换的是批量接入方式，不是底层供应商或独立数据源。WeStock 错误会保留为 `SOURCE_ERROR`，不会静默回退或伪造数据。

## 7. 数据湖本地日线（2026-09-25 新增）

`ASTOCK_BULK_PROVIDER=lake` 选择第三种日线来源：`a-share-data-lake_v1` 的本地全市场 Parquet。这不是”换一家数据商”，而是给日线一条正交于腾讯的本地通道——WeStock CLI、neodata 与 AkShare 日线的底层都落在腾讯行情接口上，集中风险需要一条断得开、跑得动、可离线的替代路径。

数据契约与既有日线 Provider 完全对齐（同列、同序、同单位）：`volume` 原样为”股”、`amount` 原样为”元”、不复权。归一层不做任何换算；数据湖的 iFinD `cmd_history_quotation` 直接返回股与元，恰好与 §6 写明的规范单位一致。数据湖没有换手率列，Provider 留空字符串（= 缺失）而非 0——`avg_amount_20d` 流动性因子读的是 `amount`，全市场没有因子消费 `turnover_rate`。

三种失败状态被如实分开：Parquet 不存在或读盘失败 = `SOURCE_ERROR`；请求交易日/窗口内确实没有行 = `NULL`；请求标的里湖只回了部分 = 缺口进 `missing_symbols`。绝不静默回退、绝不伪造行。名单（`securities`）不走数据湖：湖主档只有当前快照的 `name` 字段可推 ST，不是 PIT 的历史状态，而名单归一层要求 `is_st / is_delisting_board / suspended_trading_days` 必填非空——硬接就是把 ST 规则建立在猜值上。名单仍由 AkShare 提供。

`LakeProvider` 同时实现了 `BatchMarketBarSource`（批量补缺口契约，`fetch_recent_bars`）与 `SymbolBarFallbackSource`（逐标的补缺，`fetch_symbol_bars`），因此 `astock sync-bootstrap` 和 `astock sync-research` 在选中 lake 时可以把 `batch_source` 真正接上（此前 `NO_BATCH_PRIMARY_AVAILABLE` 的探测结论对 westock/akshare 仍然成立），整段窗口的历史一次性返回，冷启动从逐只 ~1 秒压到本地秒级。
