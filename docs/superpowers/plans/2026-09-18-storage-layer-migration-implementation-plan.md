# 存储分层迁移实施计划（Parquet + DuckDB）

> **已被取代（2026-09-18）：** 实施步骤以
> `docs/superpowers/plans/2026-09-18-storage-migration-v2-implementation-plan.md` 为准
> （不可变数据包 + 证据表 + `active.json` 显式物化）。本文件只作历史记录保留：
> 它提出的门禁清单与任务分解仍是当时的口径，但目录布局（扁平
> `data/normalized/<dataset>/`）已被 v2 的数据包布局取代。
> 口径规格仍是 `docs/STORAGE.md`，两份计划都引用它。

> **给执行的 agent：** 按任务逐条实施，每个步骤用 `- [ ]` 勾选跟踪。这份计划里的
> 阈值、分区、压缩参数一律不得自行发明——未确认的项标 `Deferred`，并停在对应的
> **STOP GATE**。

**目标：** 把分析数据的读取点从"每次重新解析 Raw CSV"换成"读已落盘的 Normalized
Parquet"，把正式快照 / Watchlist / Job 状态的默认后端从 JSON 换成 DuckDB；Raw 层
CSV 保持原样不动。

**权威口径：** `docs/STORAGE.md`（2026-09-18 所有者裁决）+ `docs/ARCHITECTURE.md` §14。

**技术栈：** Python >=3.12、Pydantic 2.x、Typer、pytest、Ruff、mypy、
`data` extra（duckdb / polars / pyarrow）、既有 `SnapshotStore` / `WatchlistStore` /
`JobStore` 抽象。

---

## 一、所有者裁决（2026-09-18，本轮不再重新讨论）

1. 保留 CSV 作为 Raw 原始落地区，尤其是 Provider 回放和故障审计用途。
2. 新增 Normalized Parquet 层，行情、财报等分析数据从这里读取。
3. 把正式快照、Watchlist、Job 状态统一切到 DuckDB。
4. JSON 只保留给小型 manifest、API/CLI 交换、测试 fixture 和外部 Adapter 协议。
5. 迁移期间做 CSV → Parquet 的校验和双读比对，确认行数、主键、空值状态一致后再切默认读取路径。

**结论口径：** 不是"CSV/JSON 完全错了"，而是 Raw 层可以继续用，分析和业务持久化层
应该尽快切到 Parquet + DuckDB。

## 二、全局约束

- 不新增任何未确认的分区粒度、目录布局、压缩算法、row group 大小与双写策略。
- **禁止静默兜底**：格式转换不得把缺失变成 0 / 空串 / NaN / 丢行；缺失必须仍是 6 个
  显式状态之一。
- 不删除、不重建 Raw CSV：`data/raw/**` 原件在整个迁移过程中保持可回放。
- 依赖方向不变：Factor / Universe / Strategy 只读 Normalized；API / Web 不直连 DuckDB。
- Raw → Parquet 的校验未全绿前，**默认读取路径保持 CSV**。
- 每个任务：先写失败测试（RED 证据）→ 最小实现（GREEN）→ 跑定向命令 + `ruff` +
  `mypy` + `git diff --check` → 中文 commit 并 push；不攒批量。
- 大产物不入库（`.gitignore` 已含 `data/**/*.parquet`、`var/astock.duckdb`、
  `data/raw/**`、`data/snapshots/**`、`var/jobs/`）。
- 结论、裁决与新约定写入 `.workbuddy/memory/<YYYY-MM-DD>.md`（中文）。

## 三、起点状态（2026-09-18 实测，实施前必须核对）

- `main` HEAD `96f0e7d`；**工作区有未提交改动**：`configs/universe.yaml`
  （SSE+SZSE、`min_average_turnover_20d: 150000000`）+ 10 个测试文件 +
  `tests/fixtures/csv/daily_bars_long.csv`，另有 `var/scan-*.csv` 未跟踪产物。
  **实施前先确认这批改动的归属并单独提交或还原**，否则会被混进存储迁移的提交里。
- Raw：`data/raw/daily_bars.csv` 167,751 行、`securities.csv` 5,565 只、
  `financial_{balance,income,cashflow}.csv`、`bootstrap/<as-of>/parts/`、`westock/`、`neodata/`。
- Normalized：`data/normalized/` 只有 `.gitkeep`（**本计划的主要缺口**）。
- 快照：`data/snapshots/{UNIVERSE,FACTOR,STRATEGY}/<date>.json` 各 3 天；
  Watchlist 默认 JSON；Job 只有 `JsonJobStore`，CLI `_job_store()` 硬编码它。
- `configs/app.yaml` 的 `storage.database` / `storage.parquet_root` 被解析被打印，
  但代码里无人消费。
- 依赖：本机 venv 有 `duckdb 1.5.5`，**缺 `pyarrow` / `polars`**。

## 四、锁定数据流

```text
Provider ──(CSV 落地，保留)──► data/raw/**
                                    │
                                    ▼
                         NORMALIZE（归一化 + 质量门）
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
        data/normalized/**/*.parquet        （回放用途：CSV 路径保留）
                    │
                    ▼
        Factor → Universe → Strategy → Candidate
                    │
                    ▼
        正式快照 / Watchlist / Job 状态 ──► DuckDB
```

## 五、STOP GATE（未确认不得越过）

| 门禁 | 内容 | 阻塞 | 状态 |
| --- | --- | --- | --- |
| A | Parquet 分区粒度与目录布局 | Task 2 | 待所有者确认 |
| B | 现存 JSON 快照 / Job 清单是否迁入 DuckDB | Task 7 | 待所有者确认 |
| C | 过渡期是否双写（两边都写） | Task 7 | 待所有者确认 |
| D | Normalized 层是否也装因子结果时序 | Task 2 | 待所有者确认 |

门禁确认前，Task 1、Task 4 的校验器骨架、Task 6 的 DuckDB JobStore 可以先行
（它们不依赖上述选项）。

---

## Task 1：让 `storage` 配置真正被消费

**问题：** `configs/app.yaml` 声明了 `storage.database` 与 `storage.parquet_root`，
`settings.py` 解析、`astock doctor` 打印，但代码里没有任何地方使用。

- [ ] 新增 `src/astock_lens/data/storage/paths.py`：把 `storage.database` /
      `storage.parquet_root` 解析为快照根、Watchlist 根、Job 根、Parquet 根的
      **统一默认来源**。
- [ ] 优先级固定为 `环境变量 > configs/app.yaml > 内置默认`；env 覆盖的是具体路径，
      不是"关掉配置"。
- [ ] CLI 的 `_csv_root()` 之外的路径解析函数改为走这一个来源，不新增第二套路径逻辑。
- [ ] `astock doctor` 打印**实际生效**路径（含来源：env / config / default）。
- [ ] RED：`tests/unit/test_storage_paths.py` — 三档优先级各一条，另加"config 缺
      `storage` 段"与"env 指向不存在的根"两条边界。
- [ ] 提交：`配置：让 storage 路径真正被消费`

## Task 2：Normalized Parquet 写入器（受门禁 A、D 约束）

- [ ] `uv sync --extra data` 装 `pyarrow` / `polars`；缺 extra 时报错必须点名安装命令
      （照抄既有 `_MISSING_EXTRA` 风格，不要在模块顶层 import）。
- [ ] 新增 `src/astock_lens/data/storage/parquet.py`：
      `ParquetNormalizedWriter.write(dataset: NormalizedDataset, *, as_of, root) -> Path`。
- [ ] 四张表：`daily_bars`、`financial_observations`、`valuations`、`securities`；
      每张表带 `status` 列（6 态之一），缺失值写 NULL，**不得**写 0 / 空串。
- [ ] 写入原子性：临时目录 + 原子替换；半途失败不得留下半份可读产物（与 bootstrap
      的 `os.replace + fsync` 约定一致）。
- [ ] 同键重复写幂等（内容相同不重写；内容不同必须显式报错，不能静默覆盖）。
- [ ] 分区与目录布局按门禁 A 的确认结果；未确认前不实现具体布局。
- [ ] 血缘：产物携带 `as_of`，并预留 `universe_snapshot` / `factor_version` /
      `strategy_version` 字段位。
- [ ] RED：`tests/unit/test_parquet_normalized_store.py` — 往返一致、缺失状态不变、
      同键幂等、异内容冲突、原子性（注入写失败）。
- [ ] 提交：`数据：新增归一化数据的 Parquet 落地层`

## Task 3：Parquet 读取器与双源开关

- [ ] 新增 `ParquetNormalizedReader.read(*, as_of, root) -> NormalizedDataset`。
- [ ] `normalize_stage()` 增加 `source: Literal["csv", "parquet"] = "csv"`；**默认仍是
      csv**，切换由 Task 8 执行。
- [ ] 缺 Parquet 产物时必须显式失败或按缺失状态返回，绝不静默回退 CSV 冒充成功。
- [ ] RED：同一 `as_of` 下两路产出的 `NormalizedDataset` 逐条相等（含显式排序规则）。
- [ ] 提交：`数据：归一化数据支持从 Parquet 读取`

## Task 4：迁移校验器与只读 CLI

- [ ] 新增 `src/astock_lens/data/storage/verify.py`：
      `verify_parquet_against_csv(...) -> MigrationReport`，实现 `docs/STORAGE.md` §4
      的四关：结构（列/类型/主键唯一）、计数（逐数据集行数）、状态（空值仍为显式状态）、
      双读比对（两侧 `NormalizedDataset` 逐条相等）。
- [ ] 报告分级 P0/P1/P2/P3；**任何 P0 都判为不可切换**，且报告必须点名数据集与主键。
- [ ] CLI：`astock storage verify --as-of YYYY-MM-DD`，只读，不写快照 / Watchlist / Job。
- [ ] RED：四类反例各一条（少一列、行数差 1、状态被写成 0、双读不等），断言命中级别
      且 P0 阻断切换。
- [ ] 提交：`校验：新增 CSV 与 Parquet 的迁移比对`

## Task 5：真实数据校验（算子运行，产出证据）

- [ ] 对 `2026-09-17` 全市场跑 Task 4：行情 167,751 行、`securities.csv` 5,565 只、
      三大表、neodata 估值全量参与。
- [ ] 四关结果与实测耗时、产物大小写入 `docs/REVIEW_NOTES.md` 新增一节。
- [ ] 门禁：**任一 P0 → 不得进入 Task 8**，回到 Task 2/3 修数据，修完重跑。
- [ ] 提交：`验证：全市场归一化数据的 Parquet 迁移比对`

## Task 6：Job 状态的 DuckDB 实现

- [ ] 新增 `src/astock_lens/jobs/duckdb_store.py`：`DuckDBJobStore`，表
      `job_runs(job_type, as_of, payload JSON, recorded_at)`，主键 `(job_type, as_of)`；
      "重跑同一阶段替换原条目并保持位置"的语义与 `JsonJobStore` 完全一致。
- [ ] 新增 `resolve_job_store(root, *, backend=None)`；门禁 B/C 未确认前默认保持 `json`。
- [ ] 读取不写库（查询某个从未跑过的日期不得创建数据库文件），与既有两个 DuckDB
      store 的约定一致。
- [ ] RED：`tests/unit/test_job_store.py` 加对照测试 — 两种实现逐条比对（替换位置、
      顺序、损坏记录必须报错而不是读成"什么都没跑"）。
- [ ] 提交：`数据：补齐 Job 状态的 DuckDB 实现`

## Task 7：三类业务状态的默认后端切到 DuckDB（受门禁 B、C 约束）

- [ ] 快照 `data/snapshots/resolve.py`、`watchlist/store.py`、`jobs` 的默认后端统一改成
      `duckdb`；三个 `ASTOCK_*_BACKEND=json` 回退路径必须保留且可用。
- [ ] CLI `_job_store()` 改为走 `resolve_job_store`，不再硬编码 JSON 实现。
- [ ] 现存 JSON 数据按门禁 B 的确认结果处理（迁移脚本 / 留档不动）。
- [ ] `astock doctor` 打印三类状态的实际承载（DuckDB 路径或文件根）与后端来源。
- [ ] RED：默认路径写入后 DuckDB 文件存在且读回逐条一致；`=json` 时仍写 JSON 文件。
- [ ] 提交：`存储：正式快照、Watchlist 与 Job 状态默认落到 DuckDB`

## Task 8：默认读取路径切到 Parquet（Task 5 全绿后）

- [ ] `normalize_stage()` 的 `source` 默认值改为 `parquet`；CLI 增加 `--source csv`
      回放开关。
- [ ] 加守门测试：默认路径下把 CSV 移走仍能算出同样结果（证明真的没读 CSV）；
      `--source csv` 与 Parquet 路径结果逐条相等。
- [ ] 提交：`存储：分析数据默认从 Parquet 读取`

## Task 9：文档与账本收口

- [ ] `docs/ROADMAP.md` 勾掉"Parquet 存储"条目并补提交号；把门禁确认结果记进第一节。
- [ ] `docs/DATA_MODEL.md` 补 Normalized 层的持久化形态与主键定义。
- [ ] `.workbuddy/memory/2026-09-18.md` 追加本轮结论与偏差。
- [ ] 提交：`文档：收口存储分层迁移结论`

---

## 验收总口径

1. Raw CSV 原件在迁移前后可回放，且默认分析路径不再依赖它；
2. `data/normalized/**/*.parquet` 成为 Factor / Universe / Strategy 的唯一数据来源；
3. 快照 / Watchlist / Job 状态默认落 DuckDB，JSON 回退仍可用；
4. `astock storage verify` 在真实全市场数据上四关全绿（无 P0）；
5. 迁移期间没有任何一步把缺失写成 0、把失败读成空、或静默回退到另一条路径；
6. Raw 层与业务层各自的载体，与 `docs/STORAGE.md` 的四层表格一一对应。
