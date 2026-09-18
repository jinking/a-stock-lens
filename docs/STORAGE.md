# 存储分层与迁移口径（V1）

本文件是存储分层的**权威口径**。`docs/ARCHITECTURE.md` §14 只给方向，具体到
"哪一层用什么载体、谁写谁读、切换前要过哪些校验"，以本文件为准。

裁决日期：2026-09-18，裁决人：项目所有者。本文件只记录已确认的内容；
未确认的照旧标 `Deferred`，不得在代码里先行发明。

## 1. 四层裁决

| 层 | 载体 | 谁写 | 谁读 | 落地状态（2026-09-18） |
| --- | --- | --- | --- | --- |
| Raw 原始落地 | **CSV** | `data/sync.py`、bootstrap checkpoint | 归一化入口（`LocalCsvProvider`） | 已落地 |
| Normalized 分析数据 | **Parquet** | `NORMALIZE` 阶段 | Factor / Universe / Strategy | **未实现**（`data/normalized/` 为空） |
| 正式快照、Watchlist、Job 状态 | **DuckDB** | `astock daily`、`astock watch`、pipeline | API / CLI | 部分实现，默认仍是 JSON |
| 小对象交换 | **JSON** | manifest、API/CLI、fixture、Adapter | 同左 | 已落地 |

### 1.1 CSV 保留为 Raw 原始落地区

Raw 层继续用 CSV，**不迁 Parquet**，也不做"统一格式"改造。理由：Raw 的职责是
保真与可回放，用途是 **Provider 回放**（同一份原始输入能重跑归一化）与
**故障审计**（出问题时能直接看源站给了什么）。这两件事要的是"与源站同形"，
不是查询性能。

### 1.2 新增 Normalized Parquet 层

行情、财报等**分析数据从 Parquet 读取**。归一化产物落盘后，Factor / Universe /
Strategy 不再直接读 Raw CSV。

依赖方向不变，只是读取点从"每次重新解析 CSV"换成"读已落盘的归一化产物"。

### 1.3 正式快照、Watchlist、Job 状态统一切到 DuckDB

三类业务状态都要求主键约束、冲突检测与事务性写入，DuckDB 是本地最优解。
`ARCHITECTURE.md` §14 原本就是这个方向，本次把它从"方向"变成"默认后端"。

### 1.4 JSON 只保留四类用途

1. 小型 manifest（例如 bootstrap 的 `manifest.json`）；
2. API / CLI 交换格式；
3. 测试 fixture；
4. 外部 Adapter 协议（例如深研 `ResearchSummary`）。

超出这四类的新持久化需求，一律不新增 JSON 载体。

## 2. 为什么不是"CSV/JSON 完全错了"

- Raw 层的 CSV 是**证据**：职责是保真与可回放，不是查询性能。它没有错。
- 分析层的真实瓶颈是**重复归一化**：现在每次 run 都要把 CSV 重新解析成两百多万个
  观测对象（全市场归一化峰值内存实测约 2.9 GB）。Parquet 带来列式存储、显式类型
  与分区，把这份重复开销消掉。
- 业务状态（快照 / Watchlist / Job）要的是事务性与主键约束，JSON 文件给不了；
  这类需求下 JSON 是错的选择。
- JSON 本身没有错，错的是拿它承载**需要约束与查询**的状态。

结论：Raw 层可以继续用，分析和业务持久化层应尽快切到 Parquet + DuckDB。

## 3. 边界与禁令

- Factor / Universe / Strategy **不得**读 Raw CSV：归一化产物落盘后，读取点只有
  Parquet（回放用途例外，见 §4.4 的双读比对）。
- API / Web 不得直连 DuckDB（保持 `ARCHITECTURE.md` §19.1）。
- **禁止静默兜底**：落盘时缺失仍必须写成 6 个显式状态之一（`VALUE`、`NULL`、
  `STALE`、`INVALID`、`SOURCE_ERROR`、`NOT_APPLICABLE`），不得因为格式转换而
  变成 0、空串、NaN 或直接丢行。
- Raw CSV 不做"删除重建"式迁移：任何迁移都必须保留原件。
- `data/**/*.parquet`、`var/astock.duckdb` 是运行时产物，不入版本库
  （`.gitignore` 已就位）。

## 4. 迁移校验口径（裁决第 5 条的落地）

CSV → Parquet 必须过完下面四关，**全绿之后**才允许把默认读取路径切到 Parquet。

1. **结构校验**：列集合与类型一致；主键唯一
   （行情 `symbol + trade_date`，财务 `symbol + report_period + metric` 等）。
2. **计数校验**：逐数据集行数一致（不是总量一致——总量一致可以掩盖此消彼长）。
3. **空值状态校验**：每个"缺失"在 Parquet 里仍是显式状态，不得退化成 NaN/0/丢行；
   同一格的状态在两侧必须相同。
4. **双读比对**：同一 `as_of` 下，CSV 路径与 Parquet 路径产出的 `NormalizedDataset`
   必须逐条相等（比较前按显式排序规则归一）。

校验产出分级报告（P0 阻断 / P1 降级 / P2 警告 / P3 记录）：**任何 P0 都不允许切换**。

Deferred（未确认，不得先写进代码）：Parquet 分区粒度、目录布局、压缩算法与
row group 大小、过渡期是否双写。

## 5. 现状与缺口（2026-09-18 实测）

**Raw（CSV，已落地）** — `data/raw/`：

- `daily_bars.csv` 167,751 行、`securities.csv` 5,565 只名单；
- `financial_balance.csv` / `financial_income.csv` / `financial_cashflow.csv`；
- `bootstrap/<as-of>/parts/<symbol>.csv` 每标的分片 + `manifest.json`；
- `westock/industry/`、`neodata/`。

**Normalized（Parquet，未落地）** — `data/normalized/` 只有 `.gitkeep`。
`normalize_stage()` 在内存里产出 `NormalizedDataset`，`financial_inputs()` /
`valuation_inputs()` 每次直接从 CSV 重新归一化。这是裁决第 2 条的缺口。

**业务状态（默认 JSON）**：

- 快照 `data/snapshots/<KIND>/<date>.json`（`UNIVERSE` / `FACTOR` / `STRATEGY`
  各 3 天）；`JsonSnapshotStore` 是默认，`DuckDBSnapshotStore` 已实现且在同一协议
  后面，由 `ASTOCK_SNAPSHOT_BACKEND` 切换（默认 `json`）；
- Watchlist：`JsonWatchlistStore` 默认，`DuckDBWatchlistStore` 已实现，
  `ASTOCK_WATCHLIST_BACKEND` 切换；
- Job 状态：`var/jobs/<date>.json`，**只有** `JsonJobStore`，尚无 DuckDB 实现，
  且 CLI `_job_store()` 硬编码该实现。

**已声明但无人消费的配置**：`configs/app.yaml` 的 `storage.database`
（`var/astock.duckdb`）与 `storage.parquet_root`（`data`）被 `settings.py` 解析、
被 `astock doctor` 打印，但代码里没有任何地方真正使用它们。

**依赖**：`pyproject.toml` 的 `data` extra 已声明 `duckdb` / `polars` / `pyarrow`。
本机 venv 现有 `duckdb 1.5.5`，**缺 `pyarrow` 与 `polars`**。

## 6. Deferred / 待所有者确认

- Parquet 分区粒度与目录布局；
- Normalized 层是否只装"行情 + 财务 + 估值 + 名单"，还是也装因子结果时序；
- 现存 JSON 快照与 Job 清单是否迁入 DuckDB（迁移 / 留档后从新数据开始）；
- 过渡期是否双写（两边都写，切换时再停一侧）。

以上四项未确认前，实施计划按"不预设"处理，对应的任务保持 `BLOCKED`。
