# 评审记录（Review Notes）

本文件记录实现过程中做出的判断、偏离与未决事项。设计三件套是权威来源；这里写的是
权威来源没有规定、而实现不得不选择的部分，以及选择的依据。

> 语言约定：按项目所有者要求（2026-09-17），本文件与后续文档、提交信息统一使用中文。
> 原始设计规格 `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md` 正文保持英文，
> 其补遗章节已改为中文。

## 一、设计状态与基线

归档规格的元信息写着"最终评审待定"，而项目所有者已确认该设计包为正式基线。
当前指令消除了这处状态不一致，未改动任何产品规则。

## 二、设计一致性实现（2026-09-16）

设计包重新落回仓库时，`docs/PRODUCT.md`、`docs/ARCHITECTURE.md` 与规格正文与包内
**逐字节相同**，因此没有覆盖任何文档；实际工作是补齐设计与代码之间的缺口。

### 2.1 Watchlist 状态转移

`spec §13` 确认唯一活跃路径：`DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL`，
`READY`、`HOLDING`、`EXITED`、`ARCHIVED` 是预留状态。实现只接受确认过的前进一步，
后退、跳步、重复与预留状态一律拒绝并写明涉及的状态。这些拒绝是解释而非发明：
设计没有定义后退或跳步规则，接受它们等于替产品做决定。

### 2.2 每日管线的阶段顺序

`spec §15` 把 `BUILD_UNIVERSE`（3）列在 `COMPUTE_FACTORS`（4）之前。实现先把因子算出来，
因为 Universe 的流动性规则消费 `avg_amount_20d`，重复测量同一数量会给出两套定义。
该偏离写在 `pipelines/daily.py` 的 `EXECUTION_ORDER` 旁，Job Manifest 记录实际执行顺序。

### 2.3 被阻塞的阶段

`DETECT_REGIME`、`MARKET_VALIDATE`、`RUN_SIGNALS`、`UPDATE_WATCHLIST` 记为 `BLOCKED`
并写明等待的决策：设计确认了它们的词表，却没有确认任何阈值；watchlist 也没有
"自动变更状态"的规则。因此 `astock daily` 在这些阶段补齐前退出码为 1，
`--allow-incomplete` 必须显式给出；`MARKET_REGIME` 快照没有生产者，缺失被显式列出。

### 2.4 不属于 `domain/enums.py` 的词表

`JobStatus` 放在 jobs 模块旁，理由与 `UniverseRule` 相同：`domain` 只放设计枚举过的词表，
而设计只提到 `JobRun.status` 字段，没有枚举取值。

### 2.5 多 Scanner 下的血缘版本

`docs/DATA_MODEL.md` §2 预留 `strategy_version` 字段，而 `spec §8` 有七个 Scanner，
因此同一标的一次运行可能命中多个版本。血缘字段改为记录全部参与者（逗号分隔），
"这条结果是否被该血缘覆盖"是成员判断而非等值判断；`SnapshotLineage` 提供拆分，
CandidateBuilder 与独立产物校验器都用它。

### 2.6 深研适配器

`spec §14` 固定了适配器接口与"V1 用 CLI 实现"，但没有规定外部调用的形状。
命令来自 `ASTOCK_DEEP_RESEARCH_CMD`，协议是"一段 JSON 进、一段 JSON 出"。
这是集成细节而非产品规则；任务状态词表属于对方系统，原样透传。未配置命令时
`astock research` 直接按名拒绝，不会伪造一次提交。

## 三、数据源边界补遗（2026-09-16）

项目所有者批准把财务三大表的 bulk 源换到深研项目同款的腾讯 WeStock CLI，
`neodata` 留在研究侧。补遗写进规格 §24，并在 `docs/PRODUCT.md` §4.2、
`docs/ARCHITECTURE.md` §4.1、`docs/DATA_SOURCES.md` §1–2 指向它。依据（当日实测）：

| 证据 | 结果 |
| --- | --- |
| `westock finance sh600519 --type income --fields all` | 同时给出 `EndDate`（报告期）与 `InfoPublDate`（公告日期） |
| 同一接口默认 `--fields core` | 完全没有公告日期 |
| AkShare/Sina 三大表 | `公告日期` 不是原始公告日（同一报告期，资产负债表标 `20260815`、利润表标 `20260417`） |
| 100 只一批 | 11.4 秒、100 行全回；全市场三表约需半小时，属季度任务 |
| CLI 自带的批次汇总行（`成功: 1`） | 即使有无效代码也报成功，因此覆盖率改由"请求代码 vs 返回代码"计算 |
| `neodata` 取最新财报 | 能返回带 `发布日期`/`统计截止日期`/`报告期`的结构化 Markdown（点名报告期即可取到 2026-H1），但逐标的、散文形态、凭证 12 小时且只能由 WorkBuddy 刷新，不适合批量因子源 |

落到代码里的后果：新增 `RawDataset.missing_symbols`（源站可能部分回答却不说）、
永远请求 `--fields all`（有测试钉住）、WeStock 以外部命令调用（不导入对方 Python 模块、
不读其内部状态）。

## 四、财务数据链路（2026-09-16）

设计未规定、实现必须选择的几处：

- **`available_at` 取公告日当天的 A 股收盘（15:00 +08:00）。** `InfoPublDate` 只有日期，
  公告可能在开盘前或收盘后发布；取收盘是保守选择，宁可推迟可用性，绝不提前。
- **指标映射写在代码里**（`data/normalize/financials.py`），与产出这些列的 Provider 相邻，
  和 `akshare_provider.BAR_COLUMN_MAP` 同一做法。源站列名映射是集成细节，不是阈值。
- **49 个规范指标**覆盖设计里的 Quality / Growth / Valuation / Dividend / 现金流维度，
  单位随指标携带（`%`、`x`、`CNY`、`CNY/share`），读者不必猜 `17.7179` 是比率还是百分比。
- **三种"缺失"保持可区分**：源站空值 → `NULL` 观测；文本读不出 → 失败记录 + `INVALID`；
  整张表没落地 → `absent_datasets` 点名。三者都不会变成 0，也不会消失。
- **`NULL` 观测可以通过质量门**（`INVALID` 不行）：因子必须能报告"源站这里没有值"，
  把它删掉会让"缺失"和"没人算这个指标"变得无法区分。
- **财报不做按龄跳过**：按新鲜度跳过需要一条节奏决策（`Deferred`）；重复落地是安全的，
  因为行按 `(code, EndDate)` 合并。

### 4.1 全市场运行查出的三个缺陷

第一次全市场运行（5,576 只 × 三大表）暴露了 fixture 无法暴露的问题，均已修复：

1. **源站列集随批次内容变化。** 含银行的那批多 6 列（实测 88 vs 82），含保险的又多一组
   （`EmbeddedValuePS`、`NewBusinessValuePSLife` 等）。原实现把形状差异判为损坏并返回
   `SOURCE_ERROR`，于是**一批银行毁掉了整张资产负债表和利润表**。改为按列的**并集**合并，
   某个形状没有的单元格留空（缺失，不是 0）；同一处理随后补到文件合并层。
2. **批次成功也可能静默漏代码。** 5,576 只里 58 只在其批次里没返回，单独重问全都有数据。
   现在批次跑完会对 `missing_symbols` 做一次补抓，资产负债表缺口从 58 降到 4。
3. **失败原因被丢弃。** 原先只留状态，第一次失败时无法定位原因。`RawDataset.message`
   现在承载原因，并出现在落地报告里。

运行数字：37 分钟、168 次调用、缺口 4–6 只（`000003.SZ`、`000005.SZ`、`830799.BJ`、
`900948.SH` 等退市/B 股，项目所有者确认不再处理）；归一化 92 秒、峰值内存约 2.9 GB、
0 个阻断问题。内存来自一次性物化 213 万个观测对象，是当前最大开销。

## 五、基本面因子（2026-09-16）

- **TTM 对 TTM。** 中国报表是年初至今累计口径，用半年流量除以期末存量会把半年和整张
  资产负债表混在一起。源站同时发布 TTM 与单期字段，因此需要"滚动一年"的比值两侧都用 TTM，
  而不是由代码拼季度。
- **缺失优先级显式化**：`NOT_APPLICABLE`（该标的报表没有这一行）> `NULL`（有行无值）>
  `STALE`（超过已评审的新鲜度上限）。不写清顺序，两个实现会对同一条记录给出不同结论。
- **`STALE` 是等数字的机制。** 每个基本面因子配置必须声明 `params.stale_after_days`；
  写 `null` 表示"尚无已评审的新鲜度要求"，因子永不报 `STALE`。与 `configs/universe.yaml`
  的 `long_suspension_days: null` 同一约定。
- **新增 `FactorResult.inputs`**，让一个值能说明它依据的指标、报告期、公告日期与原始值。
  设计要求解释链可达；没有这个字段，读者只看到一个比率，不知道是哪一期产生的。
- **`factors compute` 与每日管线共用同一套 normalize**，否则同一个基本面因子会在一条命令下
  报 `NOT_APPLICABLE`、另一条报 `VALUE`。
- **"最近一次带值的观测"语义**（2026-09-17 补）：财报并非每期都发布每个字段，例如源站的
  `DividendPaidRatio` 只在年报出现。若把"最新一期为空"判成 `NULL`，会丢掉市场已知的测量
  ——实测分红策略可评分标的会从 3,689 掉到 734。现在取最近的非空观测，并在 `inputs` 里
  写明它属于哪一期；是否太旧由 `STALE` 与新鲜度上限决定。

已知解读边界（只记录、不改写）：银行的经营现金流包含存款变动，`ocf_to_net_profit`
对金融企业不表示"利润含金量"（实测 `000001.SZ` 为 8.20）。是否按行业豁免属策略层决定，
设计未确认，因此没有加行业判断。

## 六、Scanner 资格判定（2026-09-16）

- **只判资格、不给分数。** `docs/STRATEGY_SYSTEM.md` §5 把所有 Scanner 的权重、阈值、
  `rank_percentile`、`confidence` 列为 `Deferred`。动量带着 `PENDING REVIEW` 的等权草案，
  另外三个当时没有任何权重，打分会是发明的数字。资格判定——"证据是否完整到足以让这个
  Scanner 考虑它"——是真实、可证伪的结论，也是设计漏斗的前半段。
- **当时一个类服务三个 Scanner**：评分被推迟时，区分它们的只有"要求哪些因子"，而那写在
  `configs/strategies/*.yaml` 里。写三个同样的类等于把重复代码伪装成三套算法。
- **新增七个指标透传因子**（`revenue_yoy`、`net_profit_parent_yoy`、`revenue_cagr_3y`、
  `net_profit_parent_cagr_3y`、`roe_ttm`、`gross_margin`、`debt_to_asset`）：
  引擎的契约是 `FactorResult`，策略需要的指标必须先成为因子才能被读到。不重算、不套阈值。
- **新增 `FactorResult.unit`**：一个不带单位的值不可解释。
- **三个未实现的 Scanner 写明等待的输入**（而非"观点未定"）：`value` 与 `garp` 缺已评审的
  股本/市值口径，`industry_trend` 缺尚未落地的行业数据。

资格判定确实在干活而非盖章：同一次运行里，银行 `000001.SZ` 在 `growth`、`dividend` 上合格，
在 `quality` 上不合格——因为它的利润表没有毛利率这一行（该格为空 → `NULL`）。

## 七、权重评审（2026-09-17）

本次先建机器与工具，**权重数字由项目所有者确认后才写入配置**。

### 7.1 本次定下的机制

- **权重的符号表达极性**：正数表示越大越好，负数先定向再排名，因此
  `debt_to_asset: -1.0` 表示杠杆越低越好。一个因子一个数字，含糊之处藏不住。
- **`weights` 必须恰好覆盖 `required_factors`；0 权重被拒绝。** 一个 0 权重意味着这个因子
  本不该出现在要求里，静默忽略会留下没人负责的"要求"。
- **注册表是切换点**（本条为 2026-09-17 权重评审当时的记录；同日"核心执行链硬化"
  已把这条推断规则删除，见 `docs/ROADMAP.md` 第七节）：声明了要求且有权重 → `WeightedPercentileScanner`
  打分；有要求但没权重 → `EligibilityScanner` 只判资格；两者都没有 → 报错并说明等待的输入。
- **配置守卫**：`tests/unit/test_strategy_registry.py` 断言出货配置的权重表与要求表完全一致。
  这条守卫有具体来由——写入等权当天，注册表里还硬绑着资格判定实现，导致 19 个测试同时失败。

### 7.2 实测（5,565 只，2026-09-16 数据）

| 策略 | 候选方案对比 | top-12 重合 |
| --- | --- | --- |
| Quality | 等权 vs 收益+现金流优先 | 3/12（25%） |
| Quality | 等权 vs 资产负债表优先 | 6/12（50%） |
| Growth | 等权 vs 3 年持续性优先 | 7/8（88%） |
| Growth | 等权 vs 最新一期优先 | 7/8（88%） |
| Dividend | 等权 vs 现金流覆盖优先 | 7/8（88%） |

Quality 的权重真的决定看到谁；Growth/Dividend 换权重几乎无效，指向下面两个因子问题。

### 7.3 查出的两个因子缺陷（权重救不了）

1. **分母会塌缩的比值不能用作排名输入。** `dividend_payout_ttm` 与 `ocf_to_net_profit`
   的分母都是 TTM 归母净利润，接近 0 时比值爆炸，而百分位排名恰好专挑这类公司：
   实测榜首 `603439.SH` 支付率 6407%、现金流覆盖 691 倍——与"可持续分红"完全相反。
   源站自己发布的年报支付率是正常的（茅台 79.00%、平安银行 27.13%、`603439.SH` 51.84%）。
2. **Growth 被极端值主导。** 榜首 `revenue_yoy` 达 1819%、`net_profit_parent_yoy` 达 71528%，
   百分位把 3000% 与 70000% 压成相邻名次，因此换权重只移动了一个名字。

### 7.4 项目所有者的裁决与执行（2026-09-17）

1. **三个 Scanner 采用等权开启打分**：Quality 为
   `roe_ttm 1.0 / gross_margin 1.0 / debt_to_asset -1.0 / ocf_to_net_profit 1.0`，
   Growth 四个维度各 1.0，Dividend 两个维度各 1.0。等权是刻意的中性选择：评审已证明
   不同权重会显著改变名单，在没有依据说哪个维度更重要之前不对它们排序。
2. **Dividend 改用源站 `DividendPaidRatio`**，不再用 TTM 比值参与排名；
   原 `dividend_payout_ttm` 因子保留为证据，但移出 `required_factors`。
3. **Growth 暂不做稳健化处理**，该决定保持开放。

### 7.5 执行后复跑发现的第三点

- **极性用实测确认**：把支付率取负（"留存优先"）后，dividend 榜首变成支付率 **0.000%**
  的公司，即不分红的公司。这直接证明分红策略必须取正号。
- **源站的支付率也会出现极端值**：修复"最近一次带值"语义后，可评分标的从 734 恢复到
  4,171，但榜首仍有 1950%、274%、271% 的支付率。超过 100% 的支付率本身是真实信号
  （动用留存收益或特别分红），也正是设计里点名的"一次性特别分红""周期顶部假高股息"风险。
  当前线性加权把 1950% 与 90% 同等对待。**待所有者决定**：设上限、改成区间偏好
  （例如偏好某个支付率带），还是接受现状。这是形状问题而非符号问题，现有加权百分位模型
  无法表达。

## 八、性能修正（2026-09-17）

`factor_stage` 原先把全市场数据交给每个因子的每次调用，基本面因子因此要扫 213 万个观测。
现在每个 context 只带自己标的的行（`stages.DatasetIndex`）：既更快，也更准确地表达
"一个因子能读到什么"。这条与策略无关，是纯实现问题。

## 九、neodata 评估与接入（2026-09-17）

### 9.1 起因：我上一轮的判断被实测推翻

我早先的结论是"neodata 只适合候选级、不适合做主数据"，理由有三：逐标的、Markdown 形态、
凭证 12 小时过期。项目所有者指出应按**重要性**评估、凭证由他刷新。实测结果如下：

| 探针 | 实测 |
| --- | --- |
| 多标的批量 | 10 只标的一次查询返回 10 行（3.1 秒）——批量能力远超预期 |
| 估值 | 滚动 PE/PB、**历史分位**、**相对行业估值标签**，以及逐日 PE/PB/PS/市现率/股息率/EV/PEG |
| 行业 | 板块估值（白酒Ⅱ PE 19.62/PB 3.74）+ **完整成分股明细**（总市值、流通市值、PE TTM、主力净流入） |
| 历史深度 | 一次 8 个季度，**单季口径**（2025-Q4 营收 411.5 亿与 westock 年度累计 1688.4 亿自洽） |
| 重述可见性 | 历史行标 `2026-08-15（最新调整）`，原始公告日与调整日都可见，时点卫生优于 westock 的单一更新日期 |
| 延迟 | 2–5 秒/次；全市场按 10 只/次约 558 次调用，与 westock 的 37 分钟同量级 |

结论：**凭重要性它应当做主数据**，但要按维度分工。推翻"Markdown 不适合入库"的理由也很具体：
本仓库已为 WeStock 实现了 Markdown 表格解析，形态不是障碍。

### 9.2 仍然成立的三条限制（写进 Provider 与设计补遗）

1. **意图匹配**：未命中返回 `1001 未命中意图`，因此查询措辞固化成 `QUERY_TEMPLATES`
   并由测试钉住，调用方不能自由拼自然语言；
2. **批量回答是部分的、`entity` 不可作覆盖依据**：实测请求 3 只时，利润表只回 2 只、
   估值只回 1 只，而 `entity` 三只都列了。覆盖按内容判定 + 缺口补抓一次；
3. **不做标的枚举**：名单仍由 AkShare 提供。

### 9.3 落地的分工

| 维度 | 主数据源 | 理由 |
| --- | --- | --- |
| 估值（含历史分位、行业相对） | **neodata** | 唯一同时给出这两项的来源 |
| 行业/板块 | **neodata** | Industry Trend 的行业侧输入；板块成分明细同时提供全市场估值的批量路径 |
| 主营构成、供应链、业绩会 | **neodata（唯一）** | WeStock `profile` 只有一句业务描述 |
| 财务三大表 | WeStock 为主、**neodata 交叉验证** | 数值一致（实测相同），不一致即信号 |
| 名单、日线 | AkShare + WeStock | 已落地并验证 |

### 9.4 本次实现的代码

- `data/providers/neodata.py`：一等 Provider（查询模板、批量、缺口补抓、`missing_symbols`、
  失败原因写在 `message`）；
- 凭证解析顺序：环境变量 → 插件目录（取最新版本，兼容 v1.6.0 迁移与后续升级）→ 旧路径；
  绝不回显凭证内容；
- `astock doctor` 报告 `provider neodata [ok]/[unavailable]` 与刷新方式；
- `tests/fixtures/neodata/*.json`：三条真实响应逐字录制，测试离线回放（16 个测试）。

### 9.5 尚未验证

板块级全市场覆盖（需要先拿到板块清单，注意它同样没有枚举接口）、限流表现、
以及单季财报与 WeStock 累计口径的对齐规则。这些在接归一化层时一并验证。

## 十、估值接入与 Value 评审（2026-09-17 晚）

### 10.1 规范模型：估值与财务刻意分开

新增 `ValuationObservation`（交易日时点）而不复用 `FinancialObservation`（报告期 + 公告日）：
两者可用性规则不同，混在一个模型里会让 `available_at <= as_of` 的含义含糊。
分类标签（"相对行业平均估值标签：低于"）进 `text_value`，**只作证据、不进排名**——
把"低于/持平/高于"编码成数字是一种解释，设计没确认。

日期来源如实记录：逐日时序表里的指标带自己的估值日期；键值头的"最新 PE/PB/分位"取
时序表最新一天；没有时序表时（板块查询）以查询日为日期并计数 `dated_from_query`。

### 10.2 实测查出的四条限制（都已写进代码或文档）

1. **估值查询必须逐标的。** 10 只一批只回 1–2 只（120 只抽样仅回 23 只），
   而单标的查询稳定返回；财报查询的批量覆盖是 2/3。两者批量能力不同，
   因此评审工具按 1 只一批调用。
2. **源站的"滚动股息率"整列为空。** 40 只抽样全部 `NULL`。把股息率列为 Value 的必需项
   会让它永久不合格（读起来像"市场没有便宜货"，实际是"这一列没数据"），
   因此已从 `required_factors` 移除并写明原因。
3. **亏损公司没有 PE/PB**（但有 PS）。要求 PE/PB 会把亏损股挡在 Value 之外——
   这与"便宜"的通常语义一致，但确实是一条判断，已记录。
4. **比值可以为负，单调极性会奖励"负现金流"。** 实测榜首出现
   `pcf_operating_ttm = -71` 与 `-759`：市现率为负意味着经营现金流为负，
   而"越低越便宜"的极性会把它当成最便宜。**待所有者决定**：
   非正值是否排除（视为 `NOT_APPLICABLE`）、改成区间偏好，还是接受现状。
   与第七节的分红支付率形状问题同类。

另外注意到源站对极小盈利公司给出的 `pe_ttm` 反复出现整齐的 `5.000`
（多只标的相同），像是该源的取值下限；使用前值得复核。

### 10.3 Value 评审结果（等距抽样 40 只，2026-09-17 数据）

| 候选方案 | 与等权 top-8 重合 |
| --- | --- |
| 等权 vs 便宜优先（PE 与分位加重） | 6/8（75%） |
| 等权 vs 便宜但要能赚钱（ROE 加重） | 6/8（75%） |

特征化检验通过：top quintile 的 `pe_ttm` 5.8–10.2 对余下 93–94，
`pb` 1.7–1.8 对 5.3，`roe_ttm` 1.8–13.9 对 -11.7~-14.3。
与 Quality 不同（那里两套权重只重合 3/12），**Value 的权重对榜单影响较小**：
便宜是相对客观的排序，权重改的是"多看重质量一点还是多看重便宜一点"。

GARP 的候选方案与要求已就位（`peg` + `pe_percentile` + 两个 3 年复合增速 + `roe_ttm`），
下一轮跑评审后一并定权重。

### 10.4 项目所有者的裁决与执行（2026-09-17）

1. **Value 取等权**（`pe_ttm -1 / pb -1 / ps_ttm -1 / pe_percentile -1 /
   pcf_operating_ttm -1 / roe_ttm +1`），已写入 `configs/strategies/value.yaml`。
2. **负比值政策：比值不存在时判 `NOT_APPLICABLE`。** 两条实现：
   - 源站给的倍数非正（负现金流、负净资产、负增长）→ 因子报 `NOT_APPLICABLE`；
   - 基本面比值的**分母非正**（亏损、负权益）→ 同样报 `NOT_APPLICABLE`
     （原先报 `INVALID`，但那个值本身是合法的，"不适用"的是这个比值）；
   - 百分位不受此约束：`0.000` 表示"处在自身历史最便宜处"，是合法的值。
   这不是阈值发明，而是比值的语义：负市现率不是"更便宜"，是这个量不存在。

### 10.5 GARP 评审结果（等距抽样 40 只，10 只合格）

| 候选方案 | 与等权 top-6 重合 |
| --- | --- |
| 等权 vs 成长优先（3 年 CAGR 加重） | 6/6（100%） |
| 等权 vs 匹配优先（PEG 与分位加重） | 5/6（83%） |

与 Quality（3/12）形成对照：GARP 的资格约束本身很强（同时要好估值与成长），
所以权重改不动榜单。**GARP 取等权**，已写入配置。

新发现的疑点（未解决）：源站的 **PEG 值域是 83–1503**（正常 PEG 在 0–5），
且会出现负值，说明它的定义/尺度与常见口径不同。方向（越低越匹配）仍可用，
但绝对值不能与外部 PEG 直接比较；使用前建议复核，必要时改用自算
`pe_ttm / net_profit_parent_cagr_3y`（两者我们都有）。

## 十一、neodata 落地与管线接线（2026-09-17 深夜）

这一步把估值从"能在归一化层解析"推到"日常链路可用"。

### 11.1 落地格式：一天一个文件

`<raw_root>/neodata/<dataset>/<取数日>.csv`，内容是内容块的逐字副本
（列固定为 `type, desc, content`）。选择理由：

- 内容块是多行文本，合并进一张表会破坏溯源，也说不清"这一行是哪天问来的"；
- 同一取数日重跑即覆盖，天然幂等；不同天各自留档；
- 时点选择退化成"取不晚于 `as_of` 的最新一天"，与快照复现原则一致——
  **未来日期的文件读不到**，这条由文件选择保证，并由测试钉住。

没有落过任何估值数据时 `ValuationInputs.source_file` 为 `None`：那是"还没同步"，
与"市场没有估值"是两回事，因子层因此报 `NOT_APPLICABLE` 而不是把缺失当 0。

### 11.2 命令行

```bash
uv run astock sync --as-of 2026-09-17 --valuation --symbol 600519.SH --symbol 000001.SZ
```

必须显式给 `--symbol`：neodata 不做标的枚举，且**估值批量覆盖极低**
（实测 10 只一批只回 1–2 只，120 只抽样仅回 23 只）。缺这个参数时**立刻报错**，
不会先抓几十秒行情再告诉使用者参数不对——这条 fail-fast 是被一次 36 秒的测试暴露出来的。

`--valuation` 与 `--financials`/`--statements-only` 可组合：估值逐标的、财报批量，
两者的取数节奏本来就不同。

### 11.3 真实数据验证

落地 → 归一化 → 因子 → 加权评分，全部真实数据（2026-09-17）：

| 环节 | 结果 |
| --- | --- |
| 落地 | 2 个内容块（`600519.SH`、`000001.SZ`），`300750.SZ` 源站未返回 → 记入 `missing_symbols` |
| 归一化 | 230 条估值观测，来源文件 `2026-09-17.csv` |
| 因子 | `stock` 画像显示 pe_ttm 19.31、pb 6.26、pe_percentile 3.39%、pcf_operating_ttm 13.20、roe_ttm 32.41 |
| 评分 | Value：`000001.SZ 83.33`（rank 1.0）、`600519.SH 66.67`（rank 0.5） |

同时确认了时点规则在真实环境下会正确"拒绝"数据：以日线只到 09-04 的目录在 09-17
运行时，Universe 为 0（那天没有行情），而估值文件在 09-04 之前也不可见。

## 十二、核心执行链硬化（2026-09-17，本轮）

目标不是加功能，而是把"能跑"变成"只有一个真相"。以下是本轮的裁决与实测结果。

### 12.1 删除了哪些重复的生产执行链

| 被删除 | 原因 |
| --- | --- |
| `pipelines/first_slice.py` | 与 daily scan 各有一套组装逻辑，同一个项目里有两个真相 |
| `pipelines/daily_scan.py` | 同上；`scan` 现在只走唯一分析执行链 |
| `strategies/weighted.py` | 通用加权扫描器；策略边界改为各自的类 + 共享 scorer |
| `tests/integration/test_first_slice.py`、`test_daily_scan.py` | 随入口一起退休，断言迁移进 `test_analysis_pipeline.py` |

`strategies/eligibility.py` 保留但**没有任何生产引用**：它的用途是"某策略只有资格
规则、还没有已评审权重"时的可登记实现。若所有者认为这条退路不需要，删掉它与其测试
即可。

### 12.2 谁拥有正式 Snapshot 写权限

**只有 `astock daily`。** `factors compute`、`strategy run`、`universe build` 是纯计算，
`scan` 是 non-persistent preview；四者都不创建、也不覆盖任何正式快照。这条规则由
`tests/integration/test_command_snapshot_ownership.py` 钉住，其中用"哨兵快照"排除
"内容恰好相同"的假通过。

### 12.3 Snapshot 冲突行为

同一 `(kind, as_of)`：不存在 → 写入；内容完全一致 → 幂等成功（不重写文件）；内容不同
→ `SnapshotConflictError`，本阶段不提供隐式覆盖。JSON 与 DuckDB 两个 Store 对"内容是否
相同"给同一个答案（比较规范化 payload，而不是文件缩进）。冲突在管线里表现为当前阶段
`FAILED` + Job Manifest 记录具体 kind/date，并且**停止**后续阶段。

### 12.4 哪些策略已有独立 Scanner 边界

`momentum` / `growth` / `quality` / `dividend` / `value` / `garp` 各有一类，
`registry.IMPLEMENTATIONS` 是显式映射；`industry_trend` 仍无实现并报错说明等待行业数据。
共享的只有 `strategies/percentile_scorer.py` 的算术部分。行为不变的证据是
`tests/fixtures/strategy_parity.json`：期望值由**重构前**的 commit `7d58d4c` 在固定合成
横截面上生成，重构后用同一份输入逐位比对（改一个常数就会红，已实测）。

### 12.5 Candidate 为什么保持 BLOCKED

两个独立原因，都在 `astock daily` 的输出里逐条写明：

1. `DETECT_REGIME` / `MARKET_VALIDATE` / `RUN_SIGNALS` 没有实现（阈值 `Deferred`），而
   Candidate 的定义要求这三层已经表过态；
2. 入选规则本身（Candidate Qualification）尚未批准——旧规则"eligible 且有分数 → WATCH"
   已删除，因为它把"这个策略有输入"当成了产品结论。

替代物是一个显式边界：`CandidatePolicy` Protocol + `CandidateQualification`；
没有批准的 policy 时 `candidate_stage()` 抛 `CandidatePolicyNotConfigured`，管线记
`BLOCKED`。四个待选方案写在 `docs/ROADMAP.md` 第一节，Agent 未作选择。

### 12.6 实测结果（本轮，非引用历史记录）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 测试 | `uv run pytest` | **674 passed**，0 failed |
| Lint | `uv run ruff check .` | exit 0（All checks passed） |
| 格式 | `uv run ruff format --check .` | exit 0（162 files already formatted） |
| 类型 | `uv run mypy` | exit 0（85 source files） |
| CLI 冒烟 | `doctor` / `factors compute` / `strategy run` / `scan` / `daily --allow-incomplete` | 前四条不写快照（实测文件数 0），`daily` 写出 FACTOR/UNIVERSE/STRATEGY + Job Manifest |

### 12.7 仍等待项目所有者决定

1. **Candidate Qualification**：方案 A 绝对规则 / B 每策略 percentile / C 混合 / D 策略
   只产出 ResearchResult 再由独立 policy 汇总（批准前需要全市场数量、策略分布、行业
   集中度、头部与边界样本、方案间重合度）。
2. **Growth 极值稳健化**：榜首 `net_profit_parent_yoy` 达 71528%，百分位把 3000% 与
   70000% 压成相邻名次。
3. **Dividend payout shape**：榜首支付率 1950% / 274%，线性加权把 1950% 与 90% 同等看待。
4. **PEG 处理规则**：源站值域 83–1503（常见口径 0–5）且出现负值。
5. **Industry Trend 行业打分口径**：行业侧指标与"行业→个股"映射的权重。
6. **Market Regime / Market Validation / Signal 阈值**：三个模块继续 `Deferred / BLOCKED`。

## 十三、候选资格架构与校准阶段实现（2026-09-17，本轮）

### 13.1 批准的架构边界（Approved Architecture）
1. **双门槛机制（Dual-Gate Qualification）**：
   - 相对分位数底线：`rank_percentile >= 0.90`（严格 Top 10%）；
   - 独立绝对质量门槛：六个策略（Value/Growth/GARP/Quality/Dividend/Momentum）各自拥有独立规则，不跨策略借用指标。
2. **横截面代表性选择（Representative Selection）**：
   - 软保底：每策略最多 3 只（若合格数少于 3 则全部保留）；
   - 硬上限：每日最多 50 只（按策略最高分与字典序全局选拔）；
   - 绝不硬凑 20 只下限：合格几只就是几只，零只亦合法；
   - 严禁跨策略综合加权打分（global_score）；
   - `MarketValidation.CONTRADICTED` 一票否决；
   - 缺失数据（未提供或非完整输入）严禁静默兜底为 0 或伪装为 `NEUTRAL/NO_SIGNAL`。

### 13.2 为什么 Candidate 在生产管线中依然保持 BLOCKED
这是**刻意的产品安全设计**（Intentional Product Safety），绝非管线接线未完：
1. **绝对质量门槛未获所有者批准**：六个策略的绝对规则必须在看到全市场真实分布校准证据后，由项目所有者批准具体阈值。当前代码中 `build_qualifiers()` 对未配置规则抛出 `QualificationRuleNotConfigured`，日常管线 `daily` 识别到未配置 qualifier 依法将 `BUILD_CANDIDATES` 记录为 `BLOCKED`；
2. **上游 Market Regime / Market Validation / Signal 模块仍未实现**：Candidate 契约要求这三层必须提供明确研判，上游未完成前日常管线依法保持 `BLOCKED`；
3. **隔离集成测试可验证 Candidate 生成**：在提供合成完整证据的隔离测试中，`candidate_stage` 能稳定装配候选、执行代表性选择并验证所有字段血缘。

### 13.3 新增的只读校准工具（Zero Production Mutation）
新增 `astock calibrate candidates --as-of <YYYY-MM-DD> --industry-map <PATH> --output-dir <PATH>`：
- 只跑只读分析执行链（`_preview_state` / `run_analysis`），严禁调用 `run_daily`，不写 Snapshot、Watchlist、Job 目录；
- 输出 `<YYYY-MM-DD>-candidate-calibration.json` 与 `.md` 两个产物，均显式标记 `CALIBRATION ONLY — NOT APPROVED PRODUCT RULE` 警告；
- 为项目所有者审定绝对质量门槛提供全市场分布、分位数敏感性、行业集中度与重合度证据。

## 十四、行业成员映射链路（2026-09-18，Task 7）

校准报告的"行业分布与集中度"与 `astock calibrate candidates --industry-map` 都需要一份
可审计的行业映射。本节的结论是：**来源取既有 WeStock CLI 的 `sector` 组**，不新增第三方依赖。

### 7A 探源（2026-09-18 实测，非推断）

| 命令 | 实测结果 |
| --- | --- |
| `westock sector --help` | 存在 `sector` 组：constituent / info / ranking / oper / valuation / forecast / finance |
| `westock sector ranking --kind industry` | **124 个板块**，稳定 `pt0…` 代码 + 名称（`pt01801995 电视广播Ⅱ`、`pt01801783 股份制银行Ⅱ`…） |
| `westock sector constituent pt01801783` | 标题 `申万二级行业成分股-股份制银行Ⅱ [申万二级行业] (9 只)`，列为 `code,name` |

按计划 7A 的来源接受顺序，第 1 条（既有 provider/CLI 提供稳定可枚举目录）即命中，因此**不触发
STOP GATE**。计划原文把 7B 标题写作"Normalize neodata Industry Membership"，但 neodata 的行业查询
靠板块名做意图解析、枚举不出目录，故来源改用 westock：**标题与实现的差异在此记录**，落地路径为
`data/raw/westock/industry/<取数日>.csv`（不写进 `neodata/`，避免读者误判来源）。

### 链路与不变量

```text
westock sector ranking --kind industry   （权威目录，124 个申万二级板块）
        ↓ 逐板块
westock sector constituent <pt 代码>      （code,name，标题自带层级声明）
        ↓ normalize（data/normalize/industry.py）
IndustryMembership → data/raw/westock/industry/<日期>.csv
        ↓ build_industry_map
symbol → industry   （astock industry export-map 写出 symbol,industry 两列）
```

- **标题必须与调用方要的行业一致**：目录说是 A、响应标题说是 B，说明这次调用拿回的是别人的答案，
  直接报错而不是把成员挂到错误的板块名下。
- **无法解析的代码必须报错**，不跳过：跳过会让某只标的从行业分布里消失，而覆盖率数字看不出少了谁。
- **多归属必须拒绝**：同一 symbol 落在两个不同 industry 时抛 `IndustryMembershipAmbiguous`
  （文案含 `BLOCKED_PRIMARY_INDUSTRY_SEMANTICS`），绝不"先到先得"。申万二级本身是划分，正常情况下
  不会触发；这条防的是源站将来改成概念/主题口径时悄悄给出一个假的主行业。
- **时点由 `as_of` 保证**：晚于 `as_of` 的成员记录不可见，与其余数据层同一条规则。

### 命令

- `astock sync-industry --as-of <日期>`：先取目录、再逐板块取成员，落成按取数日命名的文件（重跑幂等）。
- `astock industry export-map --as-of <日期> --output <路径>`：写出**恰好两列**的 `symbol,industry` CSV；
  除该输出文件外不触碰 Snapshot / Watchlist / Job。

## 十五、全市场冷启动重构（2026-09-18，Task 10 + 真实 100 只门禁）

背景：2026-09-18 的全市场冷启动跑死在"每完成一块就重写整份 `daily_bars.csv`"上——CPU 满载、
文件一直在写、行数一根不涨，一只挂住的标的把整轮拖成静止，命令三分钟零输出。计划
`docs/superpowers/plans/2026-09-18-full-market-bootstrap-redesign-implementation-plan.md`
把重做拆成 13 个 Task，本文件这一节记录 Task 10（假源规模门禁）与 Task 11（真实 100 只门禁）。

### 15.1 Task 10：5,300 只假源规模门禁（PASS）

`tests/stress/test_bootstrap_scale_properties.py`，只走假源、但走真实编排路径。
聚焦 `4 passed in 52.13s`；全量 `794 passed / 7 skipped`（worktree 环境）。

| 场景 | 用时 | 请求数 | 观测并发峰值 | 结果 |
|---|---|---|---|---|
| 全成功 5,300 | 9.0s | 5,300（= 标的数，零重复） | 8 = `max_inflight` | 清单全 success，canonical 106,000 行 |
| 混合失败 1%/1%/1% | 11.7s | 5,322（≤ 上界 5,300+3×159） | 10（见下） | satisfied 5,141；failed 159 = 53 超时 + 53 来源错误 + 53 空历史；canonical 102,820 行，失败零残留 |
| 批量覆盖 90% | 7.5s | 批量 6 次 + 补缺**恰好 530**（= 缺口） | 8 | 全部达标 |
| 断点续跑 | — | 第二次只请求第 2,001–5,300 只 | 8 | 前 2,000 只零重抓；最终文件与一次跑完**逐字节相同** |

两条口径说明（都是为了让断言不空洞）：

- **并发断言必须写上下界**。第一版只写"峰值 ≤ 8"，跑出来实测峰值是 **1**——假源瞬时返回，
  线程根本没来得及重叠，"退化成串行"的实现也能通过。给假源加 2ms/次的最小耗时后，峰值才
  真实到达 8，断言改成必须落在 `(1, 8]`。
- **不可终止源下活调用会短暂超过 `max_inflight`**。混合失败场景实测 10 > 8：被放弃的超时
  调用仍在后台线程里跑。AkShare 路径走可终止、可 join 的子进程，其严格上界由
  `tests/unit/test_bootstrap_scheduler.py` 钉住；调度器"整批超时且无完成即停止提交"保证这种
  堆积不无限增长（该场景第二轮 159 只只提交了 22 只就停）。混合场景的断言据此写成
  `≤ 2 × max_inflight` 并注明理由。

### 15.2 Task 11：真实 100 只门禁（PASS）

命令（同一编排路径，不手工裁剪 CSV）：

```bash
ASTOCK_CSV_ROOT=<临时根> astock sync-bootstrap --as-of 2026-09-17 --limit-symbols 100 --workers 6
```

`--limit-symbols` 是本次为门禁新增的**运维专用**开关：预筛仍跑在全量 5,301 只列表上，
只把"这次真正取历史"的标的做确定性等距抽样；它不是产品阈值，不进 `configs/`，抽样等距
跨越整份列表，避免"只取代码最小的 100 只"引入交易所与板块偏差。

**A. 一次跑完（对照组）**

| 指标 | 实测 |
|---|---|
| symbols | 100（5,301 只预筛结果里等距抽样） |
| batch requests | 0（Task 3 结论 `NO_BATCH_PRIMARY_AVAILABLE`，`batch_source=None`） |
| fallback requests | 105（首轮 100 + 仍缺的 5 只重试一次） |
| timeouts | 0 |
| source errors | 5，全部是 `920069/920179/920367/920564/920790.BJ`：腾讯日线接口不支持北交所 |
| satisfied | 95（实测 ≥20 根带成交额 bar） |
| elapsed | bootstrap 段 14s；整命令 28s（含上市列表 5,565 行落地 + 预筛） |
| throughput | 6.9 sym/s |
| peak worker 进程 | 7（`--workers 6`；+1 是回收空档的瞬时重叠），命令退出后残留 **0** |
| canonical | 2,750 行 = 94×29 + 1×24，零伪造行 |
| exit code | 1（存在 5 只显式 source_error，命令按设计报非零） |

**B. 崩溃 + 续跑**

- `kill -9` @20s 现场：**33 份分片已落盘、清单一行没有、整份文件不存在**（崩溃恰好落在两次
  清单写之间）。
- 续跑首行心跳：`processed 33/100 | satisfied 33 | failed 0 | pending 67`——33 只直接判满足、
  **零重抓**；续跑只发起 72 次请求（67 + 5 次重试），bootstrap 段 9s、整命令 24s、10.7 sym/s。
- 续跑后清单 100 条完整（95 success / 5 source_error），attempts 分布 `{1: 95, 2: 5}`——
  95 只从未被重抓，只有始终失败的 5 只 BJ 标的被重试一次。
- **与对照组的 canonical 逐字节相同**；命令退出后残留进程 0。

**门禁判定**：五条判据逐条成立——进度可见、无无法解释的停顿（bootstrap 段 9–14s，无间隔超过
心跳周期）、请求数在界内、续跑有效、canonical 产出且与对照组一致。**PASS**。

### 15.3 真实门禁当场发现并修掉的三处（都已进测试）

1. **心跳在重定向日志里看不见**：stdout 重定向到文件时按 8KB 缓冲，日志里 0 行心跳（进度全
   躺在缓冲区）。修：心跳逐行 `flush`，并且**启动即发第一行**（顺带把上市/预筛输出一起冲出来）。
2. **心跳把"重试次数"说成"失败只数"**：5 只 BJ 标的重试一次后心跳写 `failed 10`，而清单只有
   5 条 source_error。修：`failed` / `satisfied` 都按**标的只数**覆盖式记录，不再按尝试次数累加。
3. **崩溃续跑会重抓已落盘的标的**：清单是攒批落盘的，硬崩时"有分片、没条目"很常见；旧语义只认
   清单，续跑把这 33 只全部重抓（实测）。修：跑首先把已落盘分片**压实进整份文件**、按实测 bar 数
   判定谁还缺，并把缺条目的分片**补记**进清单；跑尾再压实一次（整轮无需抓取时也要产出整份文件）。
   顺带修正 throughput 在不足 1 秒的分母下印出 `15489.9 sym/s` 的假数字。

### 15.4 未决事项（Task 12/13 前置）

- **北交所标的取不到**：腾讯日线（`stock_zh_a_hist_tx`）对 `920xxx.BJ` 直接报错。全市场会命中
  约 270 只。Task 13 之前需要所有者决策：换一个支持北交所的端点，还是把它们显式记为
  `source_error` 并从研究池排除（设计禁止无证据地新增 provider）。
- **没有批量来源**：全市场仍是逐标的请求，按本次实测 6.8–7.0 sym/s 估算约 **13 分钟**（不含
  上市列表与预筛），这是 Task 12/13 的基线。
- 三个 Gate 的顺序不变：Task 10（已 PASS）→ 100 只（本节 PASS）→ 500 只 → 全市场。全市场在
  500 只 Gate 记录 PASS 之前不得运行。

## 十六、真实 500 只门禁（2026-09-18，Task 12）

同一命令路径、同一临时根隔离，规模放大到 500：

```bash
ASTOCK_CSV_ROOT=<临时根> astock sync-bootstrap --as-of 2026-09-17 --limit-symbols 500 --workers 6
```

| 指标 | 实测 |
|---|---|
| symbols | 500（5,301 只预筛结果里等距抽样） |
| batch requests | 0（`batch_source=None`，无批量来源） |
| fallback requests | 500（清单 attempts 全为 1：没有一只被请求两次） |
| timeouts | 0 |
| source errors | 0（本次抽样未命中北交所标的） |
| satisfied | 500（全部达标，`short of history: 0`） |
| elapsed | 整命令 **90s**，其中 bootstrap 段约 77s |
| throughput | **6.5 sym/s**（与 100 只门禁的 6.9 sym/s 一致，规模放大没有掉速） |
| peak active worker 进程 | **7**（`--workers 6`，+1 为回收空档的瞬时重叠） |
| staging size | `bootstrap/` **2.0 MB**（500 份分片 = 1.16 MB + 清单）；整个根 3.4 MB |
| compaction duration | **0.22s**（对同一运行再压实一次；结果字节不变 ⇒ 幂等） |
| max RSS | **343 MB**（峰值，整棵进程树：CLI + 最多 7 个 worker） |
| 命令退出后残留 worker | **0**（`pgrep` 为空） |
| canonical | 1,110,370 字节 / 14,497 行（500 × ~29 根 bar） |
| exit code | 0 |

**门禁判定**：

- 无超过心跳周期的无法解释停顿：心跳在 45s / 60s / 75s / 77s 各一行，间隔约 15s；整命令开始到
  第一条输出的静默约 13s（上市列表 5,565 行落地 + 预筛阶段），仍小于心跳周期，未触发 STOP。
  已知可改进项：若要压掉这 13 秒静默，可在 landing 之前先打一行"开始取上市列表"。
- 终态之后没有仍在跑的远程工作：命令退出后 worker 进程计数为 0，无残留子进程。
- 请求数在界内：500 次 fallback = 500 只标的，零重试、零超时、零来源错误。

**PASS**。至此三道前置门禁（Task 10 假源 5,300、100 只真实、500 只真实）全部通过，
计划的 `LIVE FULL-MARKET GATE` 前置条件全部满足；全市场执行（Task 13）仍需所有者显式授权，
本文件不作自动放行。按 500 只实测速率（6.5 sym/s）估算，全市场约 **13–14 分钟**
（不含上市列表落地与预筛）。
