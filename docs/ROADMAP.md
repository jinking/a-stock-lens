# 待办清单（Roadmap）

本文件是**后续工作的唯一清单**：从哪里继续、哪些被什么卡住、哪些已经定好了口径。
每完成一项就勾掉并补上提交号；每次出现新的未决事项，先记到这里或
`docs/REVIEW_NOTES.md`，不要留在对话里。

**状态快照（2026-09-22 Candidate v2 生产闭环与全链路验收完成：DELIVERED + AUDITED）**

**Trade Gate V1 增量状态（2026-09-22）：部分实现，未完成交付验收。** 已提交领域模型/画像（`d0abf1b`, `c0c0034`）、快照上下文（`f5b9ea0`）、两阶段 AI 审计（`fe09b00`）、规则与裁决（`5cfb840`, `a934f38`）、Ledger（`c210a70`, `e1abdb1`）、服务层（`2c5bcbf`）、回放/统计/Artifact（`3e412fb`）、CLI（`e6cbdcc`）、只读 API（`f484b99`）、否决规则修正（`1126523`）与阶段文档（`1aff7c8`）。全量 pytest 1274 项通过，ruff/格式/mypy 通过，旧查询链只读且快照哈希不变。仍缺五个 Golden Scenario、完整 CLI 生命周期/评估行为测试、完整 Ledger/API parity 与原始规格/计划全文归档；不得标记 COMPLETE。

本行基线由全量 pytest 及 `tests/artifacts/validator.py` 独立审查实测得出（见 `docs/decision-packets/2026-09-17-candidate-v2-production-audit.md`）。
标准生产日常调度 `astock daily --as-of 2026-09-17` 11 阶段全量跑通，已正式持久化五大权威生产快照：
`UNIVERSE`（2,303 只）、`FACTOR`（120,192 条）、`STRATEGY`（13,818 条）、`MARKET_REGIME`（BEAR）、`CANDIDATE`（50 只 Candidate v2 标的）。
六策略选股榜、双门槛合格发现、5维市场验证、交易形态信号与 Candidate v2 正式候选发布已全链路闭环：
- CLI 提供 `astock today`、`astock candidates`、`astock screen`、`astock qualified` 与 `astock stock`；
- API 提供 `/today`、`/candidates`、`/strategies/{id}/results`、`/qualifications/{strategy_id}/results` 与 `/stocks/{symbol}`；
- 明确澄清三层发现语义：`screen`（纯横截面打分排名）、`qualified`（Top 10% + 绝对质量门槛双通过过滤）、`candidate`（经 Market Validation 5维检验、D1 破位否决、E1 降级预警与代表性择优的研究候选对象，非买入推荐）；
- 架构与数据契约严格遵守只读隔离，绝不重算因子或策略，零状态突变；单股画像中的 `candidate_status` 严格如实呈现（候选已发布时如实返回候选详情，绝不捏造假候选）。
Candidate v2 全链路生产验收经独立产物校验器 100% 通过（0 findings）。P1–P4 阶段已全部完成，后续重点进入 P5 Web MVP 界面开发。

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| Stock Discovery | COMPLETE | 基于含最新估值的正式快照（2026-09-19），六策略与单股画像均可用 |
| Qualified Stock Discovery (Plan A) | COMPLETE | CLI `astock qualified` 与 API `/qualifications/{strategy_id}/results` 上线；2026-09-19 实测（Value 132 / Growth 151 / GARP 61 / Quality 111 / Momentum 166 / Dividend 0 显式 warning） |
| P1 Valuation | COMPLETE | 2,241 / 2,303 覆盖（97.3%），残余 62 只缺口与语义不可算已明确记录 |
| P2 Owner Qualification Decision | COMPLETE | 所有者已批准稳健平衡型六策略规则（2026-09-20） |
| P2 Qualification Implementation | REPAIRED + AUDITED | 六份生产 YAML 已恢复批准原文；资格改用完整股票因子证据；非法配置 fail-closed；已全研究池只读审计 |
| P3 Market Regime/Validation/Signal | COMPLETE | 所有者批准口径已落地（2026-09-20）：R2 复合多维市场环境、5维市场验证矩阵（支持一票否决）与多策略特征信号引擎已实现；已通过端到端集成流水线装配验证（1051 tests passed） |
| P4 Candidate Publishing | COMPLETE | Candidate v2 市场证据与信号加固完成，标准 `astock daily` 正式发布 2026-09-17 候选快照（50 只），独立产物审查 0 findings |
| P5 Today Query & Experience | COMPLETE (CLI/API) / IN PROGRESS (Web) | CLI 与查询 API 已就绪；四页 Web MVP 的 Today、Candidates 已完成，Stock Profile、Strategy 与交付验收进行中 |



| 层 | 现状 |
| --- | --- |
| 数据源 | WeStock CLI（日线批量/三大表）、AkShare（名单/显式日线回退）、neodata（估值/行业/语义）均已接入 |
| 落地 | 财报（按 `code+EndDate` 合并）、名单/日线（按 `symbol[+trade_date]`）、neodata（按取数日一天一文件） |
| 因子 | 24 个配置（技术/流动性 + 基本面 + 估值，含真实 TTM 股息率） |
| 策略 | 7 个配置，**6 个在打分**（等权，均已评审，各自独立 Scanner 类），1 个待行业数据 |
| 执行链 | 唯一分析执行链 `pipelines/analysis.py`；正式快照只有 `astock daily` 能写 |
| 发现 | **股票发现已完成**（排名 `screen` + 双门槛合格 `qualified` 纯查询服务、CLI 与 API 已打通，只读无副作用） |
| 候选 | **候选快照已就绪**（Candidate v2 市场验证/信号闭环，破位 100% 否决，主策略唯一归属） |
| 接口 | CLI 与只读查询 API 已就绪；Web MVP 已有应用外壳、Today 与 Candidates 页面，后续补齐 Stock Profile、Strategy 和验收 |

---

## 一、需要所有者决策才能动（阻塞中）

这些不是"没时间做"，是**不能自行发明**。按设计的原则，阈值与词表未确认前保持 `BLOCKED`。

- [x] **Market Regime、Market Validation 与 Signal 规则审定与工程实现（已完成，commit `4b76d18`）**：
  - **决策材料包**：`docs/decision-packets/2026-09-20-market-signal-owner-decisions.md`，所有者已批准 R2 复合多维、5维市场验证矩阵（支持一票否决）、信号词表与分位数阈值、Mode B 全局阻塞语义；
  - **工程落地**：`src/astock_lens/market/`（`regime.py`, `validation.py`）与 `src/astock_lens/signals/`（`detector.py`）已实现并装配至 `pipelines/stages.py`；全量单元与集成测试 100% 通过（1051 passed）。

- [x] **Candidate Qualification 绝对门槛与候选发布（已完成，commit `95f34a5`, `8d56c85`）**：
  - **批准架构（Approved Architecture）**：双门槛机制（相对分位数底线 `rank_percentile >= 0.90` + 独立绝对质量门槛）；横截面代表性选择政策（每策略软保底 3 只、上限 50 只、不硬凑 20 只下限、Market Validation 一票否决、严禁跨策略综合加权打分；详见 `docs/superpowers/specs/2026-09-17-candidate-qualification-design.md`）；
  - **已实现基础设施（Implemented Infrastructure）**：策略资格模型与契约（`src/astock_lens/qualifications/`）、6 个策略判定器框架、横截面代表性选择政策（`RepresentativeCandidatePolicy`）、候选证据装配与持久化（`strategy_qualifications`, `candidate_policy_version`）、管线阶段解耦（`qualification_stage` 与 `candidate_stage`）、全市场只读校准报告引擎与 CLI（`astock calibrate candidates`）、独立产物审计器（`tests/artifacts/validator.py`）；
  - **已修复并审计（Repaired + Audited，2026-09-20）**：六个策略的绝对质量门槛（Value/Growth/GARP/Quality/Dividend/Momentum）生产配置已恢复为所有者批准口径（`configs/qualifications/*.yaml`）；资格判定改用该股票完整 Factor 证据；非法配置 fail-closed；已完成全研究池只读审计（见 `docs/decision-packets/2026-09-20-qualification-repair-audit.md`）。
  - **生产闭环与首期发布（2026-09-21）**：日常调度全链路打通，成功生成 2026-09-19 正式 `CANDIDATE` 快照（50 只标的）；经独立校验器全量单快照与跨快照审查 0 findings（见 `docs/decision-packets/2026-09-20-candidate-snapshot-audit.md`）；API 与 CLI 全面连通。
  - **Candidate v2 市场证据与信号发布全面加固（2026-09-21）**：项目所有者正式批准 A1/B3/C1/D1/E1/F1 决策组合；完成 Plan A（安全门禁、确定性主策略、策略显式市场验证/信号）与 Plan B（R2 中证全指均线比率趋势、5D 申万二级超额与真实基准超额）；在隔离沙箱中全量跑通 Candidate v2 全链路，经独立校验器全量 0 findings（见 `docs/decision-packets/2026-09-21-candidate-v2-audit.md`）。顺利进入 Plan C。
- [ ] **分红支付率的形状**：实测榜首出现 1950%/274% 的支付率（动用留存收益或特别分红），当前线性加权把 1950% 与 90% 同等对待。选项：设上限 / 区间偏好 / 接受现状。
- [ ] **Growth 极值稳健化**：榜首 `net_profit_parent_yoy` 达 71528%，百分位把 3000% 与 70000% 压成相邻名次。选项：缩尾 / 要求两端同时成立 / 接受现状。
- [ ] **PEG 值域复核**：源站 PEG 值域是 83–1503（正常 0–5）且出现负值。选项：接受其相对排序 / 自算 `pe_ttm / net_profit_parent_cagr_3y`。
- [ ] **Industry Trend 阻塞**：行业 membership 已可用；缺口是行业聚合指标、Industry Trend 打分口径及对应实现仍未批准/完成。
- [ ] **停牌天数数据源**：`configs/universe.yaml` 的 `long_suspension_days` 现在是 `null`（未评审），需要能提供停牌天数的数据源。
- [ ] **`data` extra 在本机装不上（环境阻塞）**：`uv sync --extra data` 实测跑 29 分钟后因
  `files.pythonhosted.org` 拉取 `polars-runtime-32` 超时失败，**`pyarrow` / `polars` 至今未安装**。
  这直接影响 `2026-09-18-storage-migration-v2-implementation-plan.md` 的技术栈（它写的是
  PyArrow Parquet）。实测可行的替代：Parquet 的读写全部交给 **DuckDB 原生完成**
  （`read_csv → COPY TO (FORMAT PARQUET)`、`read_parquet`），迁移链路已按这条路跑通。
  需要所有者裁决：改用 DuckDB 原生，还是提供可用镜像源再补装 PyArrow。
- [ ] **存储分层迁移的门禁**（2026-09-18 所有者给出四层裁决，口径见 `docs/STORAGE.md`；
  实施步骤以 `docs/superpowers/plans/2026-09-18-storage-migration-v2-implementation-plan.md`
  为准，早先那份 `...-storage-layer-migration-implementation-plan.md` 已标注被取代）：
  - **已被 v2 计划回答**：目录布局（不可变数据包 `data/normalized/v1/<as_of>/<bundle_id>/`）、
    Normalized 层装什么（值表 + 证据 + 诊断 + 表头）、现存 JSON 的处置（任务 2.6 历史迁入
    与无损回滚出口）。
  - **仍需所有者裁决**：见上面那条 `data` extra 装不上带来的技术栈选择（PyArrow vs DuckDB 原生）。
- [ ] **Golden Dataset 名单**：设计要求 30–50 只固定股票覆盖多行业与边界情况，清单仍是 `Deferred`。早期固定的 5 只 golden 样本标的为 `000001.SZ`、`300750.SZ`、`600519.SH`、`601318.SH`、`688981.SH`（覆盖深主板/创业板/沪主板/科创板），全市场/研究池正式 Golden Dataset 仍待项目所有者确认。

---

## 二、设计已确认、尚未实现的功能

按设计 §22 的 V1 验收链 `doctor → sync → universe → factors → 7 scanners → regime →
market validation → signals → candidate snapshot → Today → Stock Profile → WATCH →
ResearchRequest → DeepResearchAdapter` 逐项对照：

- [ ] **第 7 个 Scanner：Industry Trend**。行业 membership 已可用；缺口是行业聚合指标、Industry Trend 打分口径及对应实现仍未批准/完成。
- [x] **Market Regime / Market Validation / Signal 三个模块**（2026-09-20/21 完成）：R2 复合宏观环境、5D 验证矩阵与多策略形态信号引擎已实现并在标准日常流水线 `astock daily` 中跑通，正式产出 `MARKET_REGIME` 快照并用于 Candidate v2 筛选。
- [ ] **Web MVP 四页面**：Today / Candidates / Stock Profile / Strategy，按 `docs/superpowers/plans/2026-09-21-web-mvp.md` 执行；Watchlist 编辑、Data Health 页面不属于本轮范围。
- [ ] **API 补齐**：当前 8 个路由（health/universe/factors/candidates/watchlist/strategies/strategies_results/stocks），Stock Profile 与策略榜单已补齐，还缺 Data Health、Market Regime、Signal 等查询面。
- [ ] **深研 Adapter 实际接线**：`CliDeepResearchAdapter` 已实现且未配置时报错，但还没接上深研仓库的真实入口（`ASTOCK_DEEP_RESEARCH_CMD`）。
- [ ] **Normalized Parquet 层 + 业务状态切 DuckDB**：2026-09-18 所有者给出四层裁决
  （Raw 继续 CSV / 分析数据走 Parquet / 快照·Watchlist·Job 走 DuckDB / JSON 只留给
  manifest、API-CLI 交换、fixture、外部 Adapter）。实施步骤以
  `docs/superpowers/plans/2026-09-18-storage-migration-v2-implementation-plan.md` 为准。
  **本轮已用一次性脚本 `scripts/migrate_storage.py` 把数据实搬完并四关校验全绿**
  （实测与产物见 `docs/REVIEW_NOTES.md` 第二十一节）：Raw 走零拷贝视图、四类归一化数据
  落 Parquet、快照/Job 状态入 DuckDB。该脚本的**扁平目录布局是临时口径**，会被 v2 的
  不可变数据包布局取代；默认读取路径仍是 CSV，尚未切换。
- [ ] **因子数量**：设计目标约 40–60 个；现有 24 个。缺口主要在财务衍生（增长质量、盈利稳定性）与行业维度。

---

## 三、数据工程遗留

- [x] **全市场启动行情批量源能力探测**（2026-09-18）：当前 worktree 未安装可调用 AkShare（锁定候选版本 `1.18.94`），`tools/bin/westock` 也不存在；已有 AkShare 日线为逐标的 `stock_zh_a_hist_tx`，WeStock 的 100 标的批处理只适用于财务三大表，neodata 不提供日线 OHLCV/amount。结论为 `NO_BATCH_PRIMARY_AVAILABLE`，见 `docs/BOOTSTRAP-SOURCE-PROBE-2026-09-18.md`；后续只能走已有单标的 fallback，不能新增或臆造批量行情 Provider。
- [x] **全市场日线落地**（AkShare，名单实测 5,565 只）：2026-09-18 完成。走加固后的
  `sync-bootstrap --workers 6`：预筛 5,301 只中 455 只已达标直接跳过，4,846 只实抓，
  satisfied **5,008 只**（= 每只有 20+ 根带成交额 bar），整命令 **16m20s**、5.5 sym/s
  （纯抓取速率 6.5–6.9 sym/s），整份文件 103,940 → **167,751 行**；研究池随之从 453 只
  涨到 **4,935 只**。证据见 `docs/REVIEW_NOTES.md` 第十五~十七节。
  遗留：293 只北交所（`920xxx.BJ`）腾讯日线接口不支持，当前显式记为 `source_error` 并被排除
  出研究池，是否换端点待所有者决策。
- [x] **全市场估值批量路径与研究池覆盖**（2026-09-19/20）：已通过加固后的 `sync-valuation` 多轮补抓（落地 2,241 / 2,303 只，覆盖率 97.3%），并在 2026-09-20 正式写入 `2026-09-19` 日常快照（`astock daily`）。正式快照中六策略全部具备大规模排名能力：Value 达 1,578 只、GARP 达 849 只、Growth 达 2,302 只、Momentum 达 2,281 只、Quality 达 1,697 只、Dividend 达 1,612 只。剩余未打分标的系非正指标等业务语义判定（`NOT_APPLICABLE`），非数据接入缺陷。
- [x] **休市日日历与数据抓取跳过**（用户明确需求，2026-09-20）：已实现。`src/astock_lens/calendar/` 提供 A 股交易日历，`astock calendar is-open` / `latest` 可查询；`astock sync-research` 在休市日自动检测并优雅跳过全池价格抓取，休市日零外部网络 I/O。证据见 `docs/REVIEW_NOTES.md` §33.8。（原文保留为历史需求。）
- [ ] **全市场财报的定期刷新节奏**：37 分钟/次的季度任务，尚未定"多久跑一次、失败如何补"的节奏（`Deferred`）。
- [ ] **neodata 财务单季与 WeStock 累计口径的对齐规则**：两者数值一致（实测茅台 H1 完全相同），但单季 vs 累计需要一层对齐才能交叉验证。
- [ ] **Data Health 扩展**：`doctor` 现在报 provider 状态与数据集行数/日期区间，还缺 neodata 各数据集的"最后成功取数日"与失败原因汇总。

---

## 四、已知性能与质量问题

- [ ] **全市场归一化峰值内存约 2.9 GB**（一次性物化 213 万个观测对象），是当前最大开销；可改为按标的惰性读取。
- [ ] **板块清单来源未定**（同上）。
- [ ] **测试里的网络打桩规范**：一次 36 秒的测试暴露出"没打桩就会真的抓全市场名单"；约定：任何触碰 Provider 的测试都必须注入桩。
- [x] **日线批量 Provider 切换**（2026-09-23）：`astock daily --sync` 默认走 WeStock CLI，本地缓存优先读取证券名单；AkShare 保留为名单更新、冷启动及显式行情回退。底层两者仍同属腾讯行情接口，非供应商级分散。
- [ ] **资格影响审计的 risk 聚合键命名空间混用（M2 Minor，2026-09-20 QA 复评遗留）**：
  `src/astock_lens/calibration/qualification_impact.py` 的 `failure_reasons` 目前「能抠出因子名用因子名、
  抠不出用 risk 原文」作聚合键，因子标识符与整句文案同表。当前生产 risk 均含因子名、只读审计零丢失，
  非阻断；建议后续把 risk 结构化（携带 `factor` 字段）替代正则 + 原文兜底。

---

## 五、文档与约定维护

- [x] **GitHub Actions CI 接入（2026-09-20）**：`.github/workflows/ci.yml` 在 `push main` 与 PR 时
  复跑与本地交付门禁相同的命令（ruff check / format --check / mypy / 全量 pytest，含 `tests/stress`）。
  Python 3.12（声明的支持下限，与本地 3.14 形成双解释器交叉验证）；必装 `--extra data`
  （duckdb 用例是 `importorskip`，缺依赖会导致“跳过式假绿”）。
- [ ] `docs/DATA_MODEL.md` 补上 `ValuationObservation`（与 `FinancialObservation` 分开建模的理由）。
- [ ] `configs/factors/README.md` 更新到 24 个因子（含估值与基本面两类）。
- [ ] 每次裁决后同步 `docs/REVIEW_NOTES.md` 与 `.workbuddy/memory/<日期>.md`。
- [ ] 提交与文档一律中文（`AGENTS.md` 已写入约定）。

---

## 六、维护方式

1. 新事项出现 → 立刻写进本文件（或 `REVIEW_NOTES.md`），**不要只留在对话里**；
2. 完成一项 → 勾掉并补上提交号；
3. 需要所有者决策的 → 放到第一节，写清选项与影响，等确认再动；
4. 每完成一小步就 `commit` + `push`，不攒批量（见 2026-09-17 的节奏约定）。

## 七、已关闭：核心执行链硬化（2026-09-17）

这一轮不做新功能，只把"能跑"变成"只有一个真相"。逐项与提交号：

| 已关闭的事 | 提交 |
| --- | --- |
| 回归测试钉住快照写入权与候选路由的旧风险 | `1c30c8f` |
| 收敛为唯一分析执行链：`first_slice.py` / `daily_scan.py` 删除，改为 `pipelines/analysis.py` | `0bdfad3` |
| `astock daily` 成为唯一正式 Snapshot writer；`factors compute` / `strategy run` / `universe build` 纯计算，`scan` 只预览 | `11e1132` |
| 同日同 `(kind, as_of)` 内容不同即拒绝覆盖（`SnapshotConflictError`），内容相同幂等 | `dc37709` |
| Candidate 移到 Market / Signal 之后；上游缺位时 `BLOCKED` 而不是假成功 | `34d5d4e` |
| 六个策略各自独立 Scanner 类，percentile 加权降级为共享评分组件 | `b663a11` |
| 删除"有分数即 WATCH"，建立显式 Candidate Policy 边界（未批准即 `BLOCKED`） | `7d58d4c` |
| `FactorInputRef.available_at` 携带真实证据时间；校验器补时点与跨快照一致性检查 | `ba3ce0e` |

被这一轮**取代**的旧 TODO：不再需要"给通用加权 Scanner 补资格判定"这类条目——
策略边界已经回到各自的类里；也不再需要讨论"局部命令是否该写快照"——写入权只有
`daily` 一条路径。

## 八、下一阶段入口（严格分阶段推进）

> 详细的技术阻断机理、涉及源码位置、解除流程与第一性原理，参见 [docs/REMAINING_PRODUCT_BLOCKERS.md](file:///Users/huangjinjin/Documents/ChatGPT/a-stock-lens/docs/REMAINING_PRODUCT_BLOCKERS.md)。

P1–P4 阶段已全部完成并经验收闭环：
- **P1 估值全覆盖**：完成（97.3% 覆盖率，2,241 只标的）。
- **P2 六策略绝对质量门槛**：完成（所有者批准方案 1 稳健平衡型规则，生产 YAML 恢复并完成全池只读审计）。
- **P3 市场研判、5维验证与信号模块**：完成（R2 复合环境、5D 验证矩阵支持 D1 破位否决、多策略特征信号引擎支持 E1 降级预警）。
- **P4 正式候选发布与 Candidate v2 生产验收**：完成（标准 `astock daily` 生成五大权威生产快照，独立产物校验器审查 0 findings）。

**当前主线：推进 P5 Web MVP 与对应接口闭环**
后续工作严格按以下分期推进：

### P5.1：Today 概览与 CLI / API 候选查询（已完成）
- **产出**：CLI `astock today` / `astock candidates`；API `GET /today`、`GET /candidates`、`GET /stocks/{symbol}`；已完整展示 Candidate v2 属性、主策略与验证/信号状态。

### P5.2：Web MVP 四页面构建（进行中主线）
- **前提**：P4 正式 Candidate v2 快照与 API 端点已可用。
- **目标**：构建只读轻量 Web 前端（Today / Candidates / Stock Profile / Strategy），详见 `docs/superpowers/specs/2026-09-21-production-candidate-v2-web-mvp-design.md` 与 `docs/superpowers/plans/2026-09-21-web-mvp.md`。Watchlist 编辑、Data Health 页面与实时行情不在本轮范围。

### P6：后续架构演进与深研集成（预留）
- **目标**：第 7 个 Scanner（Industry Trend）行业指标与打分口径审定；Parquet 分析数据层不可变数据包布局落地；对接外部 Agent 的 `ASTOCK_DEEP_RESEARCH_CMD` 真实调用。
