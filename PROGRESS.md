# PROGRESS

## 测试用例精简切片（2026-09-25）

- **目标**：测试用例数量精简（规格 §7.1 验收线 ≤1040 例）；只动 `tests/`，`src/**` 与 `configs/**` 零改动，冻结 5 个未提交测试文件一行不改。
- **手法**：三条合并规则（遍历全部成员 / 先收集再断言 / 失败消息点名参数）+ 按域合并长尾文件；已固化进 `docs/ARCHITECTURE.md` §20.5（「表驱动优先」与「数量上限」）。
- **实测（collected）**：**1298 → 1063**（−235）；含用例文件 **136 → 66**，`tests/**/*.py` **141 → 71**（`a9ec8f7` 合并落点 70；修复轮 R1 还原 `test_qualification_config.py` 后 71）。
- **覆盖率**：基线 92%（`TOTAL 8703 734`，`--cov=astock_lens --cov-report=term`）；收口重测 **TOTAL 8703 734 92%（1063 passed）**（命令与原始输出见 `var/test-consolidation/coverage-after-1.txt`）。
- **批次与 commit**：
  | 批次 | 任务 | commit | collected |
  | --- | --- | --- | --- |
  | 0 基线 | Task 0 | `872e99b` + `59119d2` | 1298 |
  | 1 参数化收敛 | Task 1–4 | `b466794` `95032f7` `50a8ca9` `c3957b3` | 1298 → 1184 |
  | 2 近邻家族 | Task 5–9 | `ae5bb62` `bd285ba` `889c652` `0c6426b` `8b5cb8c` | 1184 → 1077 |
  | 3–4 去重与清理 | Task 10–11 | `55398f3` `20baf65` | 1077 → 1063 |
  | 5 文件合并 | Task 12 | `a9ec8f7`（修复轮 `48d5e1e` `9c1a39c`） | 1063 → 1063 |
  | 6 文档治理 | Task 13 | 本提交 | 1063 |
  | 待执行 | Task 14 / Task 15 | — | ≤1040（缺口 23） |
- **遗留**：Task 14 全量验收与远端 CI；Task 15 备用池收口（缺口 23，未达标不得凑数）。目录级 `ruff format --check tests/` 唯一红项 `tests/unit/test_akshare_provider.py:356` 为冻结文件的既有漂移（`20baf65` 上同样红），转 Task 14 处置披露。

## 复杂度收敛切片（2026-09-23）

- **Trade Gate 状态**：模型、Trade Profile、审计 Adapter、规则/裁决、独立 Ledger、服务层、只读 API 与 CLI 基础已落地；它消费研究事实，不重算因子/策略，不进入 `astock daily`。完整 Evaluation / Execution / Review 用户流程尚未以代码证据交付，不能标记为完成。
- **保持不变**：Trade Gate 源码、配置、测试与既有命令本切片冻结；`TradeDecision` 不改变 Candidate admission。
- **复杂度拆分**：统一策略资格实现、合并候选/市场验证重复测试、拆分发现/研究生命周期 CLI，并完成 CLI 数据、管线、校准命令分层；CLI 帮助输出与原基线一致。
- **测试实测**：Task 4 CLI 回归 **160 passed / 3 warnings**，未新增测试；Task 5/6 测试净增量为 **-4**。后续全量验收以最终命令输出为准，不用历史估算替代实测。

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
- [x] 任务 2.1 统一路径解析 —— 提交 `6a824fe`
- [x] 任务 2.2 归一化读取边界 —— 提交见本节末尾
- [x] 全量回归（917 passed / 0 skipped）—— 见"完成条件"一节

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

### 2.2 关键证据

- RED #1：`uv run pytest tests/unit/test_normalized_repository.py
  tests/integration/test_analysis_pipeline.py tests/integration/test_research_universe_flow.py
  tests/integration/test_daily_pipeline.py -q` → `ModuleNotFoundError: No module
  named 'astock_lens.data.repository.contracts'`。日志
  `logs/task22-red-01.log`。
- GREEN：同一命令 → **46 passed**（日志 `logs/task22-green-02.log`）。
- 静态检查：`ruff check` / `ruff format --check`（224 files）/ `mypy`（112 files）
  全绿。
- **一次读取**：计数 fake 证明一次 research 分析只调 `read` **1** 次
  （`counting.reads == [(LONG_DATASET, "securities")]`），且此时 `csv_root`
  指向一个不存在的目录——CSV 那条路根本没被碰。
- **异常不回退 CSV**：`logs/reverse-22-no-csv-fallback.log`。注入必抛异常的
  repository、同时给**真实可用**的 CSV 根（`tests/fixtures/csv`，`is_dir()=True`）：
  分析抛 `RuntimeError`，`read` 只被调用 1 次，没有回退。
- **行为不变硬证据（三文件 sha256 与基线逐个相同）**：

  | 产物 | 基线 sha256 | 2.2 之后 sha256 | 结论 |
  | --- | --- | --- | --- |
  | `factors.jsonl` | `2a507477…a597c` | `2a507477…a597c` | **SAME** |
  | `strategies.jsonl` | `15ce4f25…89cbd3` | `15ce4f25…89cbd3` | **SAME** |
  | `research-universe.json` | `fe817691…00e941` | `fe817691…00e941` | **SAME** |

  完整哈希见 `logs/baseline-three-files.sha256` 与
  `logs/after-2.2-three-files.sha256`；重跑产物在 `analysis-after-2.2/`
  （命令：`uv run python -m scripts.capture_research_baseline --csv-root data/raw
  --as-of 2026-09-17 --output-dir … --config-root configs
  --industry-path data/raw/westock/industry/2026-09-17.csv`，退出码 0）。
- **数据指纹零漂移**：重跑 1.1 盘点（`logs/task22-reaudit.log`），与基线清单逐条
  比对——白名单 **5,058** 个文件，新增 0 / 消失 0 / sha256 变化 0，
  `total_bytes` 都是 **300,127,558**；四类数据（`data/raw` 5,009、
  `data/snapshots` 9、`data/watchlist` 0、`var/jobs` 3）逐个零变化。
- 依赖方向：`src/astock_lens/data/**/*.py` 无任何 `astock_lens.pipelines` 引用
  （有专门用例守护）。
- 一处与计划片段的差别（不是放宽断言）：`RawDataset.fetched_at` 是
  `datetime.now(UTC)` 墙钟，两次 `normalize_stage()` 永不相等，因此计划给的
  `assert actual == expected` 按字面过不去。比对时递归摘掉这一个字段，其余逐项
  比对。详见 `docs/REVIEW_NOTES.md` §26.2。

### 完成条件逐条对账

| 完成条件 | 结果 | 证据 |
| --- | --- | --- |
| 2.1 验收 pytest 全绿且 skipped=0 | **28 passed** | `logs/task21-green-*.log` |
| 2.2 验收 pytest 全绿 | **46 passed** | `logs/task22-green-02.log` |
| 新测试证明"一次分析只读一次" | `read` 调用计数 = **1** | `tests/unit/test_normalized_repository.py` 计数 fake |
| 新测试证明"异常不回退 CSV" | 抛 `RuntimeError`，`read` 仍只 **1** 次 | `logs/reverse-22-no-csv-fallback.log` |
| 2.1 反向 A：非法 YAML | 退出码 **1**、无回溯、打印 `[failed]` | `logs/reverse-21-invalid-yaml.log` |
| 2.1 反向 B：`ASTOCK_DATABASE` | 生效路径 == 该文件，`sources['database'] == 'env'` | 同节 2.1 证据 |
| 行为不变硬证据 | 三文件 sha256 与基线**逐个 SAME** | `logs/after-2.2-three-files.sha256` |
| `configs/**` `data/**` `var/**` 零改动 | 提交范围 + 5,058 文件指纹零漂移 | `logs/task22-reaudit.log` |
| 全量 `uv run pytest -q` ≥890 且 skipped=0 | **917 passed, 10 warnings in 582.30s**，`EXIT=0`，**0 failed / 0 error / 0 skipped** | `logs/full-pytest-after-2.2.log` |
| 两条提交按计划主题 | `6a824fe` 统一分析与业务存储的有效路径解析；`提取归一化数据读取边界并复用单次分析输入` | `git log` |
| `BLOCKED.md` 随交付 | 无阻塞项（写"无"）+ 顺手发现项 | `BLOCKED.md` |

全量数字对得上：**917 = 第一步基线 890 + 本切片新增 27**（2.1 新增
`tests/unit/test_storage_paths.py` 16 条，2.2 新增 `tests/unit/test_normalized_repository.py`
11 条）。没有用例被跳过、删除或放宽。

**跑全量必须在无沙箱模式下跑**（`EXIT=0` 那一条；沙箱内跑会出与代码无关的假 ERROR，
原因与对照实测见 `BLOCKED.md` 第四节第 3 条）：

```bash
uv run pytest -q        # 无沙箱；本次 917 passed in 582.30s
```

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
