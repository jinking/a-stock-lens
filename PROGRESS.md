# PROGRESS

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
