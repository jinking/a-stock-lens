# 待办清单（Roadmap）

本文件是**后续工作的唯一清单**：从哪里继续、哪些被什么卡住、哪些已经定好了口径。
每完成一项就勾掉并补上提交号；每次出现新的未决事项，先记到这里或
`docs/REVIEW_NOTES.md`，不要留在对话里。

**状态快照（2026-09-17，`main` = `8c79288`，604 tests 全绿）**

| 层 | 现状 |
| --- | --- |
| 数据源 | AkShare（名单/日线）、WeStock（三大表，带公告日）、neodata（估值/行业/语义）三个 Provider 全部接入 |
| 落地 | 财报（按 `code+EndDate` 合并）、名单/日线（按 `symbol[+trade_date]`）、neodata（按取数日一天一文件） |
| 因子 | 24 个配置（技术/流动性 + 基本面 + 估值） |
| 策略 | 7 个配置，**6 个在打分**（等权，均已评审），1 个待行业数据 |
| 接口 | CLI 10 条命令；API 5 个路由；Web 只有 `web/README.md` |

---

## 一、需要所有者决策才能动（阻塞中）

这些不是"没时间做"，是**不能自行发明**。按设计的原则，阈值与词表未确认前保持 `BLOCKED`。

- [ ] **Market Regime 阈值**：五个状态（BULL/RANGE_UP/RANGE/RANGE_DOWN/BEAR）的判定输入与阈值。定了才能实现 `DETECT_REGIME`。
- [ ] **Candidate Qualification 规则**：`BUILD_CANDIDATES` 现在因"没有已批准的入选规则"而 `BLOCKED`（见 `.workbuddy/memory/` 与管线 note）。可选方案与影响，**只记录不选择**：
  - **方案 A：每策略独立绝对规则**——每条策略各自定资格条件。好处是可解释、与策略语义绑定；代价是规则数量随策略增长，跨策略之间没有共同尺度。
  - **方案 B：每策略 Top percentile**——按排名分位取头部。好处是不同策略可比、天然控制数量；代价是百分位本身就是阈值（取多少、按哪个横截面算），且极端值会污染边界。
  - **方案 C：绝对规则 + percentile 混合**——先过滤再排名。好处是兼顾质量与数量；代价是两套参数都要评审，调参空间最大。
  - **方案 D：策略只产出 ResearchResult，另设独立 Candidate Policy 汇总**——策略完全不做入选判断。好处是职责最干净、未来可换汇总口径；代价是要新增一层模型与存储。
  - 批准前需要看的证据：全市场 Candidate 数量、策略分布、行业集中度、头部样本与边界样本、方案间重合度（计划里的 Gate A 已写明口径）。
- [ ] **Market Validation 阈值**：个股趋势、行业趋势、相对强弱、量价、流动性五项输入如何判 `CONFIRMED/NEUTRAL/CONTRADICTED`。
- [ ] **Signal 检测阈值**：`BREAKOUT / PULLBACK / TREND_CONTINUE / TREND_WEAKEN / BREAKDOWN` 的判定规则。
- [ ] **分红支付率的形状**：实测榜首出现 1950%/274% 的支付率（动用留存收益或特别分红），当前线性加权把 1950% 与 90% 同等对待。选项：设上限 / 区间偏好 / 接受现状。
- [ ] **Growth 极值稳健化**：榜首 `net_profit_parent_yoy` 达 71528%，百分位把 3000% 与 70000% 压成相邻名次。选项：缩尾 / 要求两端同时成立 / 接受现状。
- [ ] **PEG 值域复核**：源站 PEG 值域是 83–1503（正常 0–5）且出现负值。选项：接受其相对排序 / 自算 `pe_ttm / net_profit_parent_cagr_3y`。
- [ ] **Industry Trend 的行业打分口径**：行业侧指标（收入/利润增速、估值、广度）与"行业→个股"映射的权重。
- [ ] **停牌天数数据源**：`configs/universe.yaml` 的 `long_suspension_days` 现在是 `null`（未评审），需要能提供停牌天数的数据源。
- [ ] **Golden Dataset 名单**：设计要求 30–50 只固定股票覆盖多行业与边界情况，清单仍是 `Deferred`。当前只有 3 只真实数据的演示集。

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
- [ ] **Parquet 存储**：设计规定时序走 Parquet、元数据走 DuckDB；现在快照是 JSON/DuckDB，Parquet 未落地。
- [ ] **因子数量**：设计目标约 40–60 个；现有 24 个。缺口主要在财务衍生（增长质量、盈利稳定性）与行业维度。

---

## 三、数据工程遗留

- [ ] **全市场日线落地**（AkShare，5,564 只，估计约 1.5 小时）：跑完才能做真正的全市场日扫——目前只有 3 只真实日线 + fixture。带限流与断点续跑。
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
