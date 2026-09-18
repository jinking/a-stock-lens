# 待办清单（Roadmap）

本文件是**后续工作的唯一清单**：从哪里继续、哪些被什么卡住、哪些已经定好了口径。
每完成一项就勾掉并补上提交号；每次出现新的未决事项，先记到这里或
`docs/REVIEW_NOTES.md`，不要留在对话里。

**状态快照（2026-09-18 研究池前置筛选落地，`main` 起点 `4d9d87e`，734 tests 全绿）**

本行数字由 `uv run pytest -q` 于提交前实测得出（`734 passed`），不再是引用旧值：
`d964422 / 674 tests / 3 只真实数据` 这组说法已作废，替换为本轮实测。
研究池（Research Universe）进入实现阶段：先做只读上市元数据前置筛选，再在昂贵数据补全前
生成研究股票池，见 `docs/superpowers/plans/2026-09-18-calibration-readiness-implementation-plan.md`。

| 层 | 现状 |
| --- | --- |
| 数据源 | AkShare（名单/日线）、WeStock（三大表，带公告日）、neodata（估值/行业/语义）三个 Provider 全部接入 |
| 落地 | 财报（按 `code+EndDate` 合并）、名单/日线（按 `symbol[+trade_date]`）、neodata（按取数日一天一文件） |
| 因子 | 24 个配置（技术/流动性 + 基本面 + 估值） |
| 策略 | 7 个配置，**6 个在打分**（等权，均已评审，各自独立 Scanner 类），1 个待行业数据 |
| 执行链 | 唯一分析执行链 `pipelines/analysis.py`；正式快照只有 `astock daily` 能写 |
| 候选 | `BUILD_CANDIDATES` 保持 `BLOCKED`：入选规则未批准 + Market/Signal 未实现 |
| 接口 | CLI 10 条命令；API 5 个路由；Web 只有 `web/README.md` |

---

## 一、需要所有者决策才能动（阻塞中）

这些不是"没时间做"，是**不能自行发明**。按设计的原则，阈值与词表未确认前保持 `BLOCKED`。

- [ ] **Market Regime 阈值**：五个状态（BULL/RANGE_UP/RANGE/RANGE_DOWN/BEAR）的判定输入与阈值。定了才能实现 `DETECT_REGIME`。
- [ ] **Candidate Qualification 绝对门槛与候选发布**：
  - **批准架构（Approved Architecture）**：双门槛机制（相对分位数底线 `rank_percentile >= 0.90` + 独立绝对质量门槛）；横截面代表性选择政策（每策略软保底 3 只、上限 50 只、不硬凑 20 只下限、Market Validation 一票否决、严禁跨策略综合加权打分；详见 `docs/superpowers/specs/2026-09-17-candidate-qualification-design.md`）；
  - **已实现基础设施（Implemented Infrastructure）**：策略资格模型与契约（`src/astock_lens/qualifications/`）、6 个策略判定器框架、横截面代表性选择策略（`RepresentativeCandidatePolicy`）、候选证据装配与持久化（`strategy_qualifications`, `candidate_policy_version`）、管线阶段解耦（`qualification_stage` 与 `candidate_stage`）、全市场只读校准报告引擎与 CLI（`astock calibrate candidates`）、独立产物审计器（`tests/artifacts/validator.py`）；
  - **依然阻塞（Still Blocked）**：六个策略的绝对质量门槛（Value/Growth/GARP/Quality/Dividend/Momentum）保持未配置状态，等待全市场校准报告产出真实分布证据后由项目所有者审定；上游 Market Regime、Market Validation、Signal 模块未实现；日常管线中 `BUILD_CANDIDATES` 依法保持 `BLOCKED`。
- [ ] **Market Validation 阈值**：个股趋势、行业趋势、相对强弱、量价、流动性五项输入如何判 `CONFIRMED/NEUTRAL/CONTRADICTED`。
- [ ] **Signal 检测阈值**：`BREAKOUT / PULLBACK / TREND_CONTINUE / TREND_WEAKEN / BREAKDOWN` 的判定规则。
- [ ] **分红支付率的形状**：实测榜首出现 1950%/274% 的支付率（动用留存收益或特别分红），当前线性加权把 1950% 与 90% 同等对待。选项：设上限 / 区间偏好 / 接受现状。
- [ ] **Growth 极值稳健化**：榜首 `net_profit_parent_yoy` 达 71528%，百分位把 3000% 与 70000% 压成相邻名次。选项：缩尾 / 要求两端同时成立 / 接受现状。
- [ ] **PEG 值域复核**：源站 PEG 值域是 83–1503（正常 0–5）且出现负值。选项：接受其相对排序 / 自算 `pe_ttm / net_profit_parent_cagr_3y`。
- [ ] **Industry Trend 的行业打分口径**：行业侧指标（收入/利润增速、估值、广度）与"行业→个股"映射的权重。
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
- [ ] **Golden Dataset 名单**：设计要求 30–50 只固定股票覆盖多行业与边界情况，清单仍是 `Deferred`。当前本机已落地的真实数据是 5 只（`000001.SZ`、`300750.SZ`、`600519.SH`、`601318.SH`、`688981.SH`），覆盖深主板/创业板/沪主板/科创板。

---

## 二、设计已确认、尚未实现的功能

按设计 §22 的 V1 验收链 `doctor → sync → universe → factors → 7 scanners → regime →
market validation → signals → candidate snapshot → Today → Stock Profile → WATCH →
ResearchRequest → DeepResearchAdapter` 逐项对照：

- [ ] **第 7 个 Scanner：Industry Trend**。数据侧已有（neodata 板块成分明细含每只股票 PE TTM/总市值/资金流），缺：行业数据归一化 + 板块清单来源（neodata 不枚举板块；待探 WeStock `sector ranking`）。
- [ ] **Market Regime / Market Validation / Signal 三个模块**：契约已就位，实现被上面第一节的阈值阻塞。
- [ ] **Web 六个页面**：Today / Screener / Strategy / Stock Profile / Watchlist / Data Health（`web/README.md` 只有规划）。
- [ ] **API 补齐**：当前 5 个路由（health/universe/factors/candidates/watchlist），还缺 Stock Profile、Data Health、Market Regime、Signal 等查询面。
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
- [ ] **研究池的策略长度历史**（252 根 bar，`astock sync-research`）：流动性窗口（20 根）已补齐，
  但 `proximity_52w_high` 等策略因子需要 252 根，因此目前全市场只有 5 只能被策略打分。
  要得到全市场排序列表，需要对本轮 4,935 只研究池再跑一次策略长度历史（预计 13 分钟左右）。
- [ ] **全市场估值批量路径**：实测估值批量覆盖极低（10 只一批只回 1–2 只），单标的可靠但全市场要 5,500 次调用。可行路径是**按板块迭代**（板块成分明细一次给出整板块每只股票的总市值与 PE TTM），需要先解决板块清单来源。
- [ ] **全市场财报的定期刷新节奏**：37 分钟/次的季度任务，尚未定"多久跑一次、失败如何补"的节奏（`Deferred`）。
- [ ] **neodata 财务单季与 WeStock 累计口径的对齐规则**：两者数值一致（实测茅台 H1 完全相同），但单季 vs 累计需要一层对齐才能交叉验证。
- [ ] **Data Health 扩展**：`doctor` 现在报 provider 状态与数据集行数/日期区间，还缺 neodata 各数据集的"最后成功取数日"与失败原因汇总。

---

## 四、已知性能与质量问题

- [ ] **全市场归一化峰值内存约 2.9 GB**（一次性物化 213 万个观测对象），是当前最大开销；可改为按标的惰性读取。
- [ ] **板块清单来源未定**（同上）。
- [ ] **测试里的网络打桩规范**：一次 36 秒的测试暴露出"没打桩就会真的抓全市场名单"；约定：任何触碰 Provider 的测试都必须注入桩。
- [ ] **`astock daily` 的 `--sync` 目前只支持 AkShare 批量路径**，估值需要单独按标的落地。

---

## 五、文档与约定维护

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

## 八、下一阶段入口（建议按顺序拆成三个独立计划）

不要一次把剩余 Roadmap 塞给一个 Agent，按下面的切分走：

### Plan B — Candidate & Strategy Semantics

- 前提：所有者批准 Candidate Qualification（第一节第一条）、Growth 极值稳健化、
  Dividend payout shape、PEG 处理规则。
- 目标：让"5,500 只 StrategyResult → 少量 Research Candidate"的产品语义真正成立，
  并建立策略特征化 / Golden Dataset。

### Plan C — Full-Market Data Scale

- 目标：Parquet 落地、按标的/批次惰性读取（当前全市场归一化峰值约 2.9 GB）、
  全市场日线与估值的批量路径、10 分钟日扫目标。

### Plan D — Market Lifecycle & Product Surface

- 目标：Industry Trend → Market Regime → Market Validation → Signal → Candidate →
  Watchlist → Deep Research → API → React 六页面。
- 前提：第一节里 Market Regime / Market Validation / Signal 的阈值全部获批。

- [x] **研究池范围与门槛（2026-09-18，所有者决定）**：`exchanges` 只保留 SSE/SZSE（北交所日线
  在现用接口上取不到），`min_average_turnover_20d` 由 2,000 万上调至 **1.5 亿**，研究池落在
  **2,303 只**（目标 2,000–3,000）。财务三大表已用 westock 批量落地覆盖全池；见
  `docs/REVIEW_NOTES.md` 第十九节。
- [ ] **估值数据（neodata）**：`value` / `garp` 仍只有个位数标的可打分，因为估值批量路径依赖行业映射；
  需要先跑 `sync-industry`（westock 行业目录与成员）再按板块迭代估值。
