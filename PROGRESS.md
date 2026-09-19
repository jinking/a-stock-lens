# PROGRESS

## 二阶段 · 第一刀（任务 2.1 + 2.2）—— 2026-09-19 11:08 开工

### 任务 0 核验（二阶段）

- `HEAD` = `fbeba36`；`git status --short` 干净（无输出）。
- `uv run pytest -q` = **890 passed / 0 skipped**（5 分 44 秒）——与计划的基线一致。
- `uv run python -c "import pyarrow"` → `ModuleNotFoundError`（与计划一致：本切片不装依赖）。
- `ls data/normalized` → 4 个数据集目录 + `quality_findings/`，内含 4 个 `.parquet`
  与 `quality_findings.json`：旧扁平布局遗留，**只读、不动**。
- 结论：与计划描述的现状一致，可以动工。

### 理解的目标 / 顺序 / 最大风险

- 目标：按 `docs/superpowers/plans/2026-09-18-storage-migration-v2-implementation-plan.md`
  的任务 2.1、2.2 逐条照做——把存储路径解析收敛到一个 resolver（2.1），把"每次分析
  重新解析 Raw CSV"提取成可注入的归一化读取边界（2.2）。**不发布 Parquet 布局、
  不切默认后端、不建生产 DuckDB**（`docs/STORAGE.md` §6 四项仍未裁决）。
- 顺序：2.1 RED → 实现 → GREEN → 静态检查 → 提交；再 2.2 同样一轮；最后行为不变
  硬证据（重跑 capture 比对 baseline 三文件 sha256）+ 全量 pytest。
- 最大风险：2.2 要动 `stages.py` / `analysis.py` / `daily.py` 三个计算入口。若把
  "读一次"顺手做成"重写算法"，就会用"结构更干净"掩盖"算出来的东西变了"。因此
  `run_research_analysis` 只做**纯复用**：同一 `outcome` 对象既算研究池也算分析，
  不重写因子/Universe/策略任何一行算法。
- 第二风险：`run_research_analysis` 现在**归一化两次**（`compute_research_universe`
  内一次、自己又一次）。改成一次读取后，输出必须逐字节相同——靠 baseline
  `factors.jsonl` / `strategies.jsonl` / `research-universe.json` 的 sha256 钉住。
- 第三风险：`tests/conftest.py` 的 `local_tmp` 夹具说明本机 `tmp_path` 不可用；
  计划片段里的 `tmp_path` 需换成 `local_tmp`，这是环境适配，不改断言强度。
- 时间盒：≤1.5 小时。

### 状态

- [x] 任务 0 核验
- [x] 任务 2.1 统一路径解析 —— 提交见本节末尾
- [ ] 任务 2.2 归一化读取边界

### 2.1 关键证据

- RED #1：`uv run pytest tests/unit/test_storage_paths.py tests/unit/test_settings.py
  tests/unit/test_api.py -q` → `ModuleNotFoundError: No module named
  'astock_lens.data.storage.paths'`（收集期报错）。日志见
  `var/acceptance/storage-v2-20260919/logs/task21-red-01.log`。
- GREEN：同一命令 → **28 passed**。
- `ruff check` / `ruff format --check` / `mypy`（109 files）/ `git diff --check` 全绿。
- 正向：`astock doctor` 打印五条生效路径与来源，例
  `storage.database: var/astock.duckdb [present] (config)`、
  `storage.snapshot_root: data/snapshots [present] (default)`。
- 反向 A（配置非法）：`ASTOCK_CONFIG=<坏 YAML> astock doctor` → 退出码 **1**，
  打印 `config ... [failed]` + `Configuration file is not valid YAML: ...`，
  没有回溯；日志 `logs/reverse-21-invalid-yaml.log`。
- 反向 B（env 覆盖）：`ASTOCK_DATABASE=<临时文件>` →
  `database` 就是那个文件且 `sources['database'] == 'env'`；
  `normalized_root` 仍 `config`、三个 JSON root 仍 `default`。
- 行为不变：`resolve_snapshot_store(root)` / `resolve_watchlist_store(root)`
  不传 `database` 时仍是 `root/<legacy>.duckdb`（有专门用例钉住）。
- 默认后端未变：仍是 `json`；本切片没有切换任何默认读取路径。

## 一阶段（已完成）

## 任务 0 核验（2026-09-19 08:52 开工）

- 理解的目标：按 `docs/superpowers/plans/2026-09-18-research-baseline-implementation-plan.md`
  的任务 1.1 / 1.2 / 1.3 逐条照做，给"CSV → Parquet + DuckDB"迁移留下**可逐字节比对
  的迁移前基线**，顺带让行业映射缺失在报告里如实标识来源与局限。
- 顺序：1.1 输入清单 → 1.2 行业证据字段 → 1.3 一次只读研究诊断；每项先 RED 再 GREEN，
  立刻提交（本地，不 push）。
- 最大风险：1.2 会动 `candidate_report.py` / `render.py` / `cli/app.py` 三处公共面，
  策略与因子数值一旦被顺手改动，就等于用"报告字段变了"掩盖"算的东西变了"；
  因此每个新增字段都要有"数值不变"的回归钉住。
- 第二风险：`astock calibrate candidates` 的 canonical 路径**按设计仍会拒绝**（9 只无
  行业），所以 1.2 的正面证据只能走 external 路径；canonical 只贴"仍拒绝"的反向证据。
- 第三风险：全仓盘点与全池分析各约 3–7 分钟，整阶段 2 小时时间盒要靠"不重跑 Provider"
  与后台并行来省。
- 核验结论（2026-09-19）：`HEAD=08d597c`、`git status` 仅一个与本任务无关的既有未跟踪
  文件、`wc -l data/raw/daily_bars.csv = 1675724`、`astock universe research --as-of
  2026-09-17` = `listing prefilter: 4991 / research universe: 2303`。全量 pytest 已在
  后台开跑（开工前那份），结果见 `var/acceptance/baseline-20260918/logs/task0-*.log`。

## 状态

- [x] 任务 0 核验
- [x] 任务 1.1 输入与状态清单 —— 提交 `0111eea`
- [x] 任务 1.2 校准报告显式携带行业证据 —— 提交 `50c3a96`
- [x] 任务 1.3 生成一次离线研究基线 —— 提交见本节末尾

## 1.3 关键数字（全池 2026-09-17）

- 六个产物落在 `var/acceptance/baseline-20260918/analysis/`：`manifest.json`、
  `factors.jsonl`（55,272 条）、`strategies.jsonl`（13,818 条）、
  `research-universe.json`（2,303 只）、`calibration.json`、`calibration.md`。
- 研究池 **2,303**；`unknown_industry_symbols` **9** 只；覆盖 **0.9961**。
- 四榜可打分：growth **2,302**、momentum **2,281**、quality **1,697**、dividend **1,612**
  ——与开工现状逐个一致，无一项需要"改数据凑数"。
- 重跑 1.1 脚本比对：`data/raw` + `data/snapshots` + `data/watchlist` + `var/jobs`
  共 5,021 个文件的 sha256 **全部一致，0 个变化**；全量 5,058 个白名单文件也无
  新增 / 消失 / 内容变化。
