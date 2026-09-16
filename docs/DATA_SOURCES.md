# 数据来源（V1）

## 1. 两层分工

```text
批量扫描 / 选股                     研究增强
-----------------------            --------------------------
AkShare                            a-share-deep-research
交易所公开数据                       ├─ westock-npm
免费备用源                           ├─ westock-cli
                                    └─ neodata
```

全市场批量扫描只使用免费或公开数据源。深度研究阶段不重复造数据层，而是通过适配器使用现有 `a-share-deep-research`。

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
