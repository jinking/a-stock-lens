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

## 十七、全市场冷启动执行（2026-09-18，Task 13）

**授权条件**：Task 10 + Task 11 + Task 12 均有显式 PASS 证据（第 15、16 节），所有者以"继续"放行。

### 17.1 预检

`git rev-parse HEAD` = `2346b87`（main），工作树干净（一处采样脚本移入已忽略的 `var/bench-500-task12/`），
`astock doctor` 全绿：Python 3.14.3、24 个因子配置、7 个策略、local-csv `data/raw` 已有 103,940 行、
akshare 1.18.94 可导入。

### 17.2 执行

```bash
astock sync-bootstrap --as-of 2026-09-17 --workers 6     # 已批准的 6 路并发，无 --limit-symbols
```

一次跑完，未中断；中途心跳每 15 秒一行（`processed/satisfied/failed/pending/inflight/sym/s/elapsed`），
无需 `ps/lsof` 推断是否在动。

| 指标 | 实测 |
|---|---|
| broad symbols（预筛） | 5,301 |
| 其中已在上一轮达标、**未重抓** | 455 |
| 本轮实际取数标的 | 4,846 |
| satisfied | **5,008**（全部有 20+ 根带成交额 bar） |
| short | 293 |
| timeout | 0 |
| source_error | **293，全部是 `920xxx.BJ`**（腾讯日线不支持北交所） |
| batch calls | 0（无批量来源） |
| fallback calls | **5,436**（= attempts 之和：首轮 4,846 + 两轮对仍缺标的的重试） |
| elapsed | bootstrap 段 **16m06s**（整命令约 16m20s，含上市列表落地与预筛） |
| throughput | 5.5 sym/s（累计口径，含 455 只复用；纯抓取速率与 100/500 门禁的 6.5–6.9 sym/s 一致） |
| compaction duration | **3.69s**（对同一运行再压实一次；字节不变 ⇒ 幂等） |
| staging size | `data/raw/bootstrap/2026-09-17/` **19 MB**（4,553 份分片 + 清单） |
| canonical rows | **167,751 行 / 12.9 MB**（跑前 103,940 行 / 8.0 MB） |
| **Research Universe（按 avg_amount_20d 之后）** | **4,935 只**（跑前 453 只） |
| exit code | 1（293 只显式 source_error，命令按设计报非零） |

### 17.3 关键结论

- 研究池从 **453 只涨到 4,935 只**：原先 5,110 只被 `NO_LIQUIDITY_MEASURE` 排除是因为历史只有
  ~15 根 bar（2026-09-18 的窗口口径缺陷），现在只剩 557 只（293 只北交所 + 少数无行情）。
- 达标标的**没有被重复请求**：455 只预筛后即判满足、第一轮就跳过；清单 attempts 分布
  `{1: 4549, 2: 4, 3: 293}`——只有始终失败（北交所）与被判缺的标的被重试。
- 规模放大后没有掉速：100 只 6.9 sym/s、500 只 6.5 sym/s、5,300 只 5.5 sym/s（累计口径含复用标的）。

### 17.4 仍未解决 / 未执行

- **北交所（293 只 `920xxx.BJ`）**：腾讯日线接口不支持。设计禁止无证据新增 provider，因此本轮
  只把它们**显式记为 source_error** 并排除出研究池，需要所有者决定是否换端点。
- **策略打分仍只有 5 只有分**：流动性窗口（20 根）已补齐，但 `proximity_52w_high` 等策略因子需要
  252 根历史，宽基的"策略长度历史"（`astock sync-research`）尚未对本轮研究池执行；基本面策略
  还依赖三大表（目前仅 5 只有数据）。**要得到全市场的排序列表，下一步是跑 `sync-research`
  （策略长度历史，约 4,935 只、预计 13 分钟左右）**。
- 研究池 4,935 只高于设计文档的"观察性目标 2,000–3,000"：命令自身打印的说明是"target size is
  observational, not a quota"，本轮不擅自调整任何阈值（产品规则不在本次授权范围内）。
- 全程未使用 `--limit-symbols`（该开关只用于 100/500 门禁），未手工裁剪任何 CSV。

## 十八、研究池的策略长度历史与全市场打分（2026-09-18，Task 13 延伸）

流动性窗口（20 根）补齐后，全市场仍只有 5 只能被策略打分：`proximity_52w_high` 等因子需要
252 根历史。按所有者"继续"补跑同一套加固路径：

```bash
astock sync-research --as-of 2026-09-17 --workers 6
```

| 指标 | 实测 |
|---|---|
| research universe | 4,935 只 |
| price history required | 252 根/只 |
| satisfied | **4,864** |
| short | 71（上市时间不足等） |
| could not be fetched | 1 |
| elapsed | **50m31s**（1.6–2.4 sym/s：每次请求要带回 252 根 bar，比补流动性时慢） |
| timeout | 0 |
| canonical | 167,751 → **1,675,723 行**（128.6 MB） |

随后 `astock scan --as-of 2026-09-17`（1 分 42 秒，只打印不落盘）：

| 策略 | 可打分只数 |
|---|---|
| momentum | **4,864**（全市场） |
| dividend / growth | 5 |
| quality | 3 |
| value | 2 |
| garp | 1 |
| industry_trend | 0（缺行业映射，`BLOCKED_PENDING_INDUSTRY_PATH`） |

- 动量榜前 10：300741.SZ 99.88、688004.SH 99.81、688137.SH 99.80、000993.SZ 99.68、
  601579.SH 99.64、600371.SH 99.44、688209.SH 99.42、301390.SZ 99.40、001326.SZ 99.26、
  300939.SZ 99.20；完整前 100 见运行产物 `var/scan-momentum-top100.csv`（不随仓库提交）。
- **基本面策略仍只有个位数标的**：三大表目前只有 5 只（Task 13 前的历史遗留），需要单独一轮
  财务数据落地（westock 三大表 + 行业映射）才能对全市场做股息/质量/成长/价值筛选。
- 口径提醒：这些是**研究排序**（因子百分位加权），不是买卖建议；产品边界未变。

## 十九、研究池范围与门槛（所有者决定，2026-09-18）

### 19.1 三个决定

| 决定 | 落点 | 结果 |
|---|---|---|
| 暂不纳入北交所，只要沪深两市 | `configs/universe.yaml` 的 `exchanges` 去掉 `BSE` | 预筛里 344 只北交所标的被 `EXCHANGE` 明确排除，不再以 `source_error` 混在研究池边界里 |
| 研究池保持在 2,000–3,000 | 同文件的 `min_average_turnover_20d` 由 20,000,000 上调 | 实测：100M → 2,961、150M → **2,303**（取中段）、200M → 1,853 |
| 财务数据用现成接口取 | westock-cli 批量（100 只/次） | 2,303 只研究池 × 三大表全部落地（各 ~18,400 行 / 14–15 MB） |

`data/raw` 的行情仍是 **AkShare**（逐标的腾讯日线 + 上市列表），财务是 **WeStock CLI**；
**neodata（估值/语义）本轮仍未启用**：它的批量覆盖极低，需要先有行业映射，CLI 明确打印
`valuation enrichment: BLOCKED_PENDING_INDUSTRY_PATH`（行业映射走 westock `sync-industry`，尚未跑）。

### 19.2 实测

```bash
astock sync-research --as-of 2026-09-17 --workers 6 --financials
```

- 研究池 2,303 只；价格历史 252 根/只：satisfied 2,281、short 22（新上市）。
- 财务：`financial_balance 18,418 行 / financial_cashflow 18,423 行 / financial_income 18,423 行`，
  覆盖 2,303 只标的。
- `astock scan --as-of 2026-09-17`（3 分 30 秒，只打印不落盘）可打分只数：

| 策略 | 可打分 | 说明 |
|---|---|---|
| growth | 2,302 | 三大表到位后全池可算 |
| momentum | 2,281 | 价格类 |
| quality | 1,697 | 部分标的缺所需科目 |
| dividend | 1,612 | 同上 |
| garp | 1 | 需要 PEG → 依赖估值数据（neodata 未启用） |
| value | 2 | 需要 PE/PB → 同上 |
| industry_trend | 0 | 需要行业映射（未跑 `sync-industry`） |

榜单前 100 分别导出到 `var/scan-<strategy>-top100.csv`（运行产物，不入库）；口播口径仍是
**研究排序**，不是买卖建议。

### 19.3 测试跟随

门槛属于产品规则，测试里原先写死的旧值随之更新（fixture 的"健康流动性"样本从 8,000 万
抬到 2 亿；北交所样本从"应当纳入"改为"应当被 EXCHANGE 排除"；横截面百分位随样本数从 7→6
变化）。全量 `uv run pytest` **837 passed**；ruff、format、mypy、`git diff --check` 全过。

## 二十、行业映射落地与三个待决策点（2026-09-18）

- `astock sync-industry --as-of 2026-09-18`：落地 **5,542 只 × 124 个申万二级板块**
  （`data/raw/westock/industry/2026-09-18.csv`），并导出 `symbol,industry` 映射
  （`var/industry-map-2026-09-18.csv`）。命令只在结束时打印，无中途进度。
- 行业映射的消费方是**校准命令**（`calibrate candidates`），不是打分器。它坚持零容忍：
  研究池 2,303 只里有 9 只没有行业归属（行情里共 18 只不在行业图中），于是
  `IndustryCoverageUnavailable` 直接拒绝出报告——宁可拒绝也不给残报告，这个行为是对的。
- `industry_trend` 打分为 0 与数据无关：`configs/strategies/industry_trend.yaml` 只有描述性
  `dimensions`，**没有任何因子权重**，属于未批准的产品规则，本次不擅自填写。
- `value` / `garp` 仍只有个位数标的：需要 neodata 估值。行业目录到位后"按板块迭代取估值"
  这条路解锁，但需要新切片（板块批量 provider + 落地 + 因子接线 + 测试），且历史上 neodata
  批量覆盖很差（10 只一批只回 1–2 只），因此先做只读探针再决定。
- 本节结论与三条岔路整理成给所有者的阅读文档：`docs/OWNER-BRIEF-2026-09-18.md`。

## 二十一、存储分层迁移落地：Normalized Parquet + 业务状态入 DuckDB（2026-09-18）

所有者给出四层裁决（口径落成 `docs/STORAGE.md`，任务分解见
`docs/superpowers/plans/2026-09-18-storage-layer-migration-implementation-plan.md`）。
本节记录**本轮实际搬完的数据**与四关校验实测，不含尚未批准的默认读取路径切换。

### 21.1 搬了什么，搬到哪

一次性脚本 `scripts/migrate_storage.py`（可重跑；`--state-only` 只搬状态，
`--verify-only` 只校验不写）：

| 层 | 载体与形态 | 本轮结果 |
| --- | --- | --- |
| Raw | **CSV 原件不动**；DuckDB 里只建 `read_csv` 视图（零拷贝，不产生第二份会漂移的副本） | `raw_daily_bars` 1,675,723 行、`raw_securities` 5,565 行、三大表各 18,418/18,423/18,423 行 |
| Normalized | **Parquet 是权威副本**；DuckDB 里挂指向它的同名视图 | `daily_bars` 1,675,723 行 / 31.6 MB、`securities` 5,565 行、`financial_observations` 902,652 行 / 5.2 MB、`valuations` 230 行 |
| 业务状态 | **DuckDB 实体表**，JSON 已迁入 | `snapshots` 9 行（3 类 × 3 天）、`job_runs` 33 行（3 天）、`watchlist` 0 行（尚无条目） |
| 小对象 | JSON | 质量门报告 4 份 → `data/normalized/quality_findings/quality_findings.json`（小型 manifest） |

关键取舍：归一化数据**不**在库里灌实体表。灌一份就等于承认"两份归一化数据"，和
`pipelines/analysis.py` 里"同一个项目不能有两个真相"是同一条原则。视图用仓库相对路径，
因此要从仓库根目录打开 `var/astock.duckdb`。副作用是库文件从 115 MB 降到 **5.5 MB**。

`data/normalized/**` 与 `var/astock.duckdb` 都是运行时产物，已加进 `.gitignore`
（保留 `.gitkeep` 占位）。

### 21.2 四关校验：全市场实测全绿

`--as-of 2026-09-17`，四关 + 零值检查（`docs/STORAGE.md` §4）：

| 数据集 | 结构 | 计数 | 主键 | 空值/零值 | 双读摘要 |
| --- | --- | --- | --- | --- | --- |
| daily_bars | PASS 12 列 | PASS 1,675,723 | PASS `symbol,trade_date` | PASS | PASS `06a429ed737d` |
| securities | PASS 7 列 | PASS 5,565 | PASS `symbol` | PASS | PASS `f9d3abce78e2` |
| financial_observations | PASS 9 列 | PASS 902,652 | PASS `symbol,report_period,metric` | PASS | PASS `ced7628a67d6` |
| valuations | PASS 9 列 | PASS 230 | PASS `symbol,valuation_date,metric` | PASS | PASS `a6efbe836792` |
| snapshots / job_runs | — | PASS 9 份 ↔ 9 行 / 3 天 ↔ 3 天 | — | — | — |

双读的严格程度：把 Parquet 每一行**重建成规范模型**（`DailyBar` / `SecurityProfile` /
`FinancialObservation` / `ValuationObservation`）后与内存记录逐条做 SHA-256 摘要比对——
不是只比行数。全市场 258 万条重建耗时约 467s。

**校验器非空转的证明**：在 3 行样本上把某个 NULL `close` 改成 0 重写 Parquet，三条 P0
同时命中（`空值 close` Parquet 0 ≠ 内存 1、`零值 close` Parquet 2 ≠ 内存 1、`双读` 摘要不一致）。
报告落在库里的 `migration_verification` 表。

### 21.3 本轮踩到并绕开的四个环境坑（留给后续切片）

1. **`files.pythonhosted.org` 不可达**：`uv sync --extra data` 跑 29 分钟后以
   `polars-runtime-32` 拉取超时失败，`pyarrow` / `polars` 至今**未安装**。
   于是 Parquet 的读写全部改由 **DuckDB 原生完成**（DuckDB 自己就能读写 Parquet），
   迁移链路不再依赖 pyarrow。这条也意味着 `data` extra 在本机当前是不完整的。
2. **不要用 `executemany` 灌数据**：实测约 **6,000 行/秒**（全市场要 4.5 分钟以上）。
   改为归一化记录先落暂存 CSV（`\N` 表示 NULL，避免空串与 NULL 混淆），
   再由 `read_csv → COPY TO (FORMAT PARQUET)` 一票直出：167 万行暂存 78s + 导出 8s。
3. **DuckDB Python 客户端回读 `TIMESTAMPTZ` 需要 `pytz`**，本机没有、装不上，
   直接 `fetchmany` 会抛 `ModuleNotFoundError: No module named 'pytz'`。
   绕法：时间列在 SQL 侧 `CAST(... AS VARCHAR)`，Python 侧 `datetime.fromisoformat` 还原，
   比较的仍是同一瞬时（`SET TimeZone='UTC'` 固定渲染，与机器时区无关）。
4. **沙箱不允许写 `/tmp`**（`tests/conftest.py` 早有一条同名说明），且 **Bash 默认
   120 秒超时会杀掉长进程**。前者要求所有落盘都在仓库内，后者要求长任务必须后台跑。

### 21.4 与 v2 计划的关系（重要）

本轮执行到一半时，仓库里出现了 `docs/superpowers/plans/2026-09-18-storage-migration-v2-implementation-plan.md`，
它明确**替代**早先那份 `...-storage-layer-migration-implementation-plan.md` 的实施步骤，
并把 `docs/STORAGE.md` 当作规格引用。因此本节的产物要这样看：

- 早先那份计划的实施步骤已被取代（文件已加被取代标注），门禁 A/B/C/D 大多被 v2 回答
  （目录布局、Normalized 装什么、现存 JSON 走任务 2.6 的历史迁入与回滚）；
- 本脚本的**扁平布局 `data/normalized/<dataset>/<dataset>.parquet` 是临时口径**，
  会被 v2 的不可变数据包 `data/normalized/v1/<as_of>/<bundle_id>/`（8 张表 + `manifest.json`
  + `active.json`）取代。**数据已可查，但布局不是最终形态**；
- 一条会影响 v2 技术栈的环境事实：v2 写的是 **PyArrow Parquet**，而本机
  `uv sync --extra data` 因 `files.pythonhosted.org` 不可达而失败，**pyarrow/polars 装不上**。
  本轮已证明**只用 DuckDB 原生也能完成 Parquet 的读写与校验**（见 21.3 第 1、2 条），
  需要所有者裁决走哪条路。

其余未做：默认读取路径仍是 CSV（`normalize_stage(source=...)` 与 Parquet 读取器未实现）；
三个业务后端的默认值仍是 `json`，Job 状态尚无 DuckDB 实现类；
`Normalized` 层目前只装**过了质量门**的记录，被拒记录的明细在 `quality_findings.json` 里
（不是 Parquet 表），v2 的证据表（`financial_evidence` / `diagnostics` / `headers`）尚未实现。

## 二十二、迁移前的研究基线：输入清单（2026-09-18/19，第一步任务 1.1）

任务 1.1 的目标不是"跑通一个脚本"，而是**在把数据从 CSV 搬到 Parquet + DuckDB 之前，
先把迁移前的样子固定成一份可逐字节比对的证据**。没有它，迁移之后只能证明"这次跑出来的
东西看起来还行"，无法证明"结果没变"。

### 22.1 产物与命令

```bash
uv run python scripts/audit_research_baseline.py --root . \
  --output var/acceptance/baseline-20260918/input-inventory.json
```

退出码 0。清单里 **5,058 个文件 / 300,127,558 字节**，五类白名单根逐个点名：

| 白名单根 | 形态 | 文件数 | 字节 | 目录存在 |
| --- | --- | --- | --- | --- |
| `data/raw` | `*.csv` | 5,009 | 293,987,928 | 是 |
| `data/snapshots` | `*.json` | 9 | 5,764,589 | 是 |
| `data/watchlist` | `*.json` | 0 | 0 | **否** |
| `var/jobs` | `*.json` | 3 | 14,745 | 是 |
| `configs` | `*.yaml` | 35 | 25,562 | 是 |
| `pyproject.toml`、`uv.lock` | 单文件 | 2 | — | 是 |

清单路径（以下产物按 `.gitignore` 的 `var/acceptance/` **不入库**）：
`var/acceptance/baseline-20260918/input-inventory.json`。

五类数据文件的摘要按相对路径稳定排序，逐条记 `bytes` 与 `sha256`；CSV 再记解析出的
`rows` 与 `columns`，JSON 再记 `shape`、`records` 与外壳声明的 `declared_as_of`。
旧快照与全池数据各自成条，不会被合并成一个数字：`data/snapshots/FACTOR/2026-09-04.json`
（264 条）与 `.../2026-09-17.json`（120 条）是两条独立证据。

### 22.2 `data/watchlist` 不存在，这不是错误

`data/watchlist/` 在本机**没有这个目录**：还没有 tracked 标的，目录本身也不入库。
把它当成错误会逼着脚本要么伪造一个空目录、要么拒绝出清单，两者都让基线失真。因此
清单用 `scanned_roots` 记录"声明过、本次为空"（`present=false, files=0`），而不是让
这一项从清单里消失。反向的规则同样明确：**扫描的根目录本身不存在**是显式失败，
不会返回空清单冒充"没有文件"。

### 22.3 三条实现红线与它们对应的测试

1. **CSV 用解析器计数，不数换行。** neodata 的单元格里带真实换行，按 `\n` 数会把一条
   记录算成两条。`test_multiline_cell_is_one_record` 钉住：`'code,content\n1,"甲\n乙"\n'`
   必须是 1 行；`test_csv_columns_and_rows_are_the_real_parse` 用单元格内含两处换行的
   数据钉住 3 行 2 列。
2. **损坏不是空。** 非法 JSON、缺少外壳字段、CSV 无表头，一律显式抛出并点名路径，
   绝不在清单里退化成 `rows=0` / `records=0`。对应四条单测。外壳约定直接照抄仓库里
   三种 Store 各自的读契约（`records` 列表 / `runs` 列表 / 映射），**没有另发明一套
   更松或更严的规矩**。
3. **输入必须冻结。** 每个文件读前读后各取一次 `(size, mtime_ns)`；不一致即中止并提示
   "固定输入后重试"。`test_a_file_rewritten_during_the_scan_aborts_with_the_freeze_hint`
   通过注入"签名漂移"制造并发写入，并断言该接缝确实被询问了两次——否则用例会因为
   "根本没检查"而假绿。

### 22.4 反向验证（红→绿，实跑）

在副本 `var/acceptance/baseline-20260918/reverse-1.1/`（含真实快照 9 份、Job 3 份、
configs 35 份与 3 个真实 CSV，共 52 个被盘点文件）上：

| 步骤 | 操作 | 退出码 | 输出 |
| --- | --- | --- | --- |
| 绿 | 原样扫描 | 0 | `total: 52 files, 7369384 bytes` |
| 红 A | 把 `UNIVERSE/2026-09-17.json` 截成 `{broken` | 1 | `invalid JSON (...); a broken file is not an empty one`，点名该文件 |
| 红 B | 把 `STRATEGY/2026-09-17.json` 的 `records` 改成标量 `0` | 1 | `snapshot envelope carries no records list, it has ['as_of', 'kind', 'records']` |
| 绿 | 两个文件按原样还原 | 0 | 清单与首次绿色运行**逐字段一致**（除 `generated_at`） |

两个红色运行都**没有落任何产物**（`reverse-1.1-red-*.json` 不存在）：失败就是失败，
不会留下一份看起来成功的半成品。副本里 `data/snapshots` 的 9 个文件 sha256
与源仓库逐一相同，证明脚本确实只读。

### 22.5 两处偏离计划原文（都是工程事实，不是放宽）

1. **测试夹具用 `local_tmp`，不是计划示例里的 `tmp_path`。** 本机 `tmp_path` 落在系统
   临时根下，被运行环境以 `PermissionError` 拒绝（`tests/conftest.py` 早已写明这条），
   实测确认不可用。行为断言逐条保留，只换了存放位置。
2. **`scanned_roots` 这一节是新增的。** 计划要求"清单含 `data/raw`、`data/snapshots`、
   `data/watchlist`、`var/jobs`、`configs`"，而 `data/watchlist` 在本机没有文件，
   它不可能以文件条目出现。让"空根也被点名"必须有一个位置放它，于是清单头部有了
   `scanned_roots`。`inventory()` 的返回签名不变，仍是计划规定的
   `tuple[dict[str, object], ...]`。

### 22.6 工程前置（计划已点名，实测确认）

- `scripts/` 原本不是包、`sys.path` 上也没有仓库根，计划里的
  `from scripts.audit_research_baseline import inventory` 必然 `ModuleNotFoundError`。
  已新建空 `scripts/__init__.py`，并在 `[tool.pytest.ini_options]` 加 `pythonpath = ["."]`。
  RED 证据分两段保留：先 `No module named 'scripts'`，补包后再
  `cannot import name 'audit_research_baseline' from 'scripts'`——两段都只差实现。
- `var/acceptance/` 之前没被忽略，`.gitignore` 已加一行（既有规则一律未动）。

### 22.7 基线时点

- 提交前地基 `HEAD`：`08d597cc251cad971695cf6e25d1c2edc08162cc`
- 工作区差异摘要：`M .gitignore`、`M pyproject.toml`、
  `?? scripts/__init__.py`、`?? scripts/audit_research_baseline.py`、
  `?? tests/unit/test_research_baseline_audit.py`，外加一个与本任务无关的
  既有未跟踪文件 `var/industry-map-2026-09-18.csv`（保留未动、不入库）。
- 本任务的提交只包含上面 5 个文件（外加本节所在的 `docs/REVIEW_NOTES.md`），
  没有 `git add -A`，没有触碰 `configs/**` 与 lint/mypy 配置。

## 二十三、校准报告显式携带行业证据（2026-09-19，第一步任务 1.2）

研究池 2,303 只里有 9 只没有行业归属。旧行为是：canonical 路径直接抛
`IndustryCoverageUnavailable`，报告一个字都不落。问题是**缺 9 只不等于整份材料
没有价值**——把它整份扔掉，读者拿到的信息量是零；而把缺口悄悄抹平，读者拿到的
是假信息。这一节记录的是第三种做法：把缺口写成报告的一部分。

### 23.1 两个新模型与三个新字段（`calibration/candidate_report.py`）

```python
class IndustryEvidence(DomainRecord):
    origin: Literal["canonical", "external", "unspecified"] = "unspecified"
    source_ref: str | None = None
    source_sha256: str | None = None
    mapping_as_of: datetime | None = None
    diagnostic_only: bool = True

class IndustryCoverage(DomainRecord):
    missing_symbols: tuple[str, ...]
    known_count: int
    total_count: int
    ratio: float
```

`CandidateCalibrationReport` 新增 `unknown_industry_symbols: tuple[str, ...] = ()`、
`industry_coverage: IndustryCoverage | None = None`、
`industry_evidence: IndustryEvidence = Field(default_factory=IndustryEvidence)`。
三个字段都有默认值，**既有调用方不传也照常构造**（有测试钉住）。旧的
`industry_coverage_ratio` 与 `unknown_industry_count` 一个都没删、语义也没改。

缺口用**集合差**算，不是"总数减已知数"：

```python
missing_symbols = tuple(sorted(set(all_symbols) - set(known_symbols)))
```

后者在去重失误或重复代码时会给出一个自洽而错误的数字；集合差只会如实列出真正
缺的那些代码。同时有一条测试盯住"标量计数 / 代码列表 / 结构化覆盖"三者必须
说的是同一件事——这三处一旦漂移，读者会拿到两个互相矛盾的覆盖率。

### 23.2 外部映射允许残缺，规范映射一律拒绝

分界线写在 CLI 里，而不是写在模型里：

| 路径 | `origin` | 缺标的时 |
| --- | --- | --- |
| `--industry-map <csv>` | `external` | 出诊断，缺口如实列出（`require_full_industry_coverage=False`） |
| 自动加载 canonical | `canonical` | 仍然抛 `IndustryCoverageUnavailable` |

`external` 不会被改写成 `canonical`：那等于用一次便利输入替换掉正式证据。
本阶段所有报告 `diagnostic_only=True`，没有任何"已批准"标识（有测试禁掉了
`decision_grade` / `approved_by` / `已批准` 这类字眼）。

### 23.3 映射日期：只能是声明的，或是"未知"

- 新增 `--industry-map-as-of`（可选，**带时区** ISO 时间）。它只描述
  `--industry-map`；只给日期不给映射是用法错误（退出码 2）。裸时间（没有时区）
  被拒绝，而不是被悄悄补上本机时区。
- 不给就是 `None`，报告里写**日期未知**，并明说"不以文件 mtime 顶替，也不把
  分析时点当成映射日期"。
- canonical 的日期取**可见成员自己声明的**取数时点
  （`max(m.as_of for m in canonical if m.as_of <= day)`）。因为
  `build_industry_map` 已经过滤掉晚于 `as_of` 的记录，所以一个未来日期不可能
  被当成历史口径；有一条测试专门在成员文件里塞了一条未来记录（还换了行业），
  断言它既不改行业也不改映射日期。

### 23.4 加字段不许改数字

最硬的一条：**换一份 `industry_evidence` 进去，报告里除它自己之外逐字段完全
相同**（`test_industry_evidence_never_changes_a_single_computed_number`）。
证据是"附加说明"，不是"计算输入"。

实测（全池、`--as-of 2026-09-17`）也验证了这一点：`external` 基线缺 9 只，
把映射里的一只（`000001.SZ`）删掉后缺 10 只，**多出来的恰好是被删的那一只**；
把两份报告逐字段对照，唯一变化的是 `value` 策略的 `industry_counts`
（`股份制银行Ⅱ` → `未知行业`）——那是**映射派生**的标签，本来就该随映射变。
其余全部逐字节相同：

| 对照项 | 结果 |
| --- | --- |
| 六个策略的 score / rank_percentile / ranked_count / 分位 / 重叠 / 敏感度 | 全部相同 |
| `factor_distributions`（24 个因子的分位与计数） | 相同 |
| `data_status_counts` | 相同 |
| `factor_anomalies` | 相同 |
| `population`（5565 / 4991 / 2303） | 相同 |
| `value.industry_counts` | **不同**（映射派生标签，符合预期） |

### 23.5 实测数字（全池 2026-09-17）

```bash
uv run astock calibrate candidates --as-of 2026-09-17 --output-dir <dir> \
  --industry-map var/acceptance/baseline-20260918/reverse-1.2/industry-external-2026-09-17.csv
# 退出码 0
```

- 研究池 **2,303**；覆盖 **2,294 / 2,303 = 0.9961**；缺口 **9**：
  `000592.SZ`、`000968.SZ`、`002679.SZ`、`300896.SZ`、`600158.SH`、`600185.SH`、
  `600938.SH`、`601888.SH`、`689009.SH`。
- 四榜可打分（`ranked`）：growth **2,302**、momentum **2,281**、quality **1,697**、
  dividend **1,612**——与开工现状给的数字**逐个一致**。
- `industry_evidence` 落成：
  `{"diagnostic_only": true, "mapping_as_of": null, "origin": "external",
    "source_ref": "...", "source_sha256": "f3e0d692…"}`。
  `mapping_as_of` 是 `null` 而不是分析日：那份 CSV 确实没声明日期。

### 23.6 反向验证（红→绿，实跑）

| 步骤 | 命令 | 退出码 | 结果 |
| --- | --- | --- | --- |
| 绿 | `--industry-map`（覆盖 2,294 只） | 0 | 报告落盘，`unknown_industry_symbols` 恰 9 只 |
| 绿 | `--industry-map` 删掉 `000001.SZ` | 0 | 仍出报告，缺口恰 10 只且**包含**被删的那只 |
| 红 | 不给 `--industry-map`（走 canonical） | 1 | `IndustryCoverageUnavailable: decision-grade calibration requires canonical industry coverage for every symbol, but 9 of 2303 have no industry membership; run 'astock sync-industry' or pass an explicit --industry-map and label the report as externally mapped` |
| 红 | `--industry-map-as-of 2026-09-16T15:00:00`（裸时间） | 2 | `needs a timezone offset (e.g. 2026-09-17T15:00:00+08:00); a bare time is not a fact` |
| 红 | 只给 `--industry-map-as-of` 不给 `--industry-map` | 2 | 点名需要 `--industry-map` |

canonical 的"仍拒绝"是在**全池真实数据**上跑的（不是小夹具），所以上表里那句
`9 of 2303` 就是现状描述里那一句，一个字不差。

**正式状态零改动**：跑完 1.2 的三次真实运行之后，`data/snapshots` 与 `var/jobs` 的
12 个 JSON 文件 sha256 与开工前逐一相同（`diff` 无输出）。

### 23.7 一处偏离计划原文

计划写"新增 `--industry-map-as-of` 为可选的带时区 ISO 时间，未提供就存 `None`"，
没有规定"给了日期却没给映射"怎么办。实现选择**显式拒绝（退出码 2）**：那个日期
描述的是某一份外部映射，没有那份映射时它无话可说，静默忽略会让用户以为日期
被记下了。这条选择连同测试一起留在
`tests/integration/test_calibration_readiness_cli.py`。

## 二十四、迁移前的研究分析与校准基线（2026-09-19，第一步任务 1.3）

任务 1.1 固定了**输入**，这一节固定**输出**：一次只读分析，六个产物，供迁移后
逐字节对照。目标是让"结果变了没有"这个问题有一个可以算的答案。

### 24.1 命令与产物

```bash
uv run python scripts/capture_research_baseline.py \
  --csv-root data/raw --as-of 2026-09-17 --config-root configs \
  --industry-path data/raw/westock/industry/2026-09-17.csv \
  --output-dir var/acceptance/baseline-20260918/analysis
# 退出码 0，耗时 3 分 23 秒
```

| 产物 | 大小 | 条数 | sha256（前 16 位） |
| --- | --- | --- | --- |
| `factors.jsonl` | 25,215,694 B | 55,272 | `2a50747793dc78e6` |
| `strategies.jsonl` | 170,801,773 B | 13,818 | `15ce4f251cb4ad83` |
| `research-universe.json` | 761,099 B | 2,303 只 | `fe817691aa0e0925` |
| `calibration.json` | 218,037 B | 6 个策略 | `f7e418cf8e637de9` |
| `calibration.md` | 116,661 B | — | `293e3c102b47e0b7` |
| `manifest.json` | 9,831 B | — | 记上面五项的哈希 |

55,272 = 24 因子 × 2,303；13,818 = 6 策略 × 2,303。两个数字都是**算出来的**，
不是期望值。

`manifest.json` 里 `artifact_kind = "research_diagnostic"`、
`registered_as_business_state = false`：它是 `var/acceptance` 下的交换证据，
不是 SnapshotStore 的产物，正式链路不读它。manifest 记录的输入共 33 个文件
（成员 CSV + `universe.yaml` + 24 个因子 YAML + 6 个策略 YAML），每一个都带
`bytes` 与 `sha256`。

### 24.2 四条实现红线

1. **只调用一次 `run_research_analysis`。** 报告与两个 JSONL 都由这一次的返回
   结果渲染；有测试记账断言调用次数恰为 1。
2. **离线。** 三个外部 Provider（AkShare / WeStock CLI / Neodata）的 `fetch`
   在测试里被换成抛异常，流程仍然通过；同时记账断言**只有** `LocalCsvProvider`
   被问到过数据。这条守卫防的是回归：一旦 capture 依赖外部抓取，"迁移前基线"
   就成了网络状况的函数。
3. **数值不四舍五入。** 每行直接写 `record.model_dump_json()`。测试断言每一行
   都能被领域模型原样读回并原样再序列化（逐字符串相同），并要求至少有一个因子值
   ≠ `round(value, 4)`——如果写入端做了四舍五入，后一条会红。四舍五入会在迁移
   比对时把真实差异抹平，那正是这份基线唯一要做的事。
4. **排序键显式。** 因子 `(symbol, factor)`、策略 `(strategy_id, symbol)`，
   与输入顺序无关。测试断言键序列等于自身排序结果，且无重复键。

`--industry-path` 是**显式输入**而不是按约定路径探测：基线必须能记录它实际用的
是哪一份成员文件（连 sha256），否则"用的是哪份映射"无从复算。缺行业时关掉
`require_full_industry_coverage`——这里的产物是诊断材料，不是决策材料。

### 24.3 实测数字（全池 2026-09-17）

- 宽名单 5,565 → 前置筛选 4,991 → 研究池 **2,303**（比率 0.4138）。
- `unknown_industry_symbols` **9** 只，覆盖 **2,294 / 2,303 = 0.9961**。
- 四榜可打分：growth **2,302**、momentum **2,281**、quality **1,697**、
  dividend **1,612**。**与开工现状给的数字逐个一致**，没有一处需要"改数据凑数"。
- `industry_evidence`：`origin=canonical`、
  `source_ref=data/raw/westock/industry/2026-09-17.csv`、
  `source_sha256=5557063cc415e0fce7e8f4aff15b7aafc4ce59956dce586ddcc5219d52c9fec1`、
  `mapping_as_of=2026-09-17T15:00:00+08:00`（成员自己声明的取数时点，不是分析日
  硬填出来的）、`diagnostic_only=true`。

### 24.4 反向验证（红→绿，实跑）

| 步骤 | 命令 | 退出码 | 输出 |
| --- | --- | --- | --- |
| 绿 | 验收命令原样 | 0 | 六个产物齐全，`total` 见 24.1 |
| 红 A | `--industry-path data/raw/westock/industry/1999-01-01.csv` | 1 | `capture failed: FileNotFoundError: --industry-path does not exist: …`；**产物目录没有被创建** |
| 红 B | `--as-of 2026-09-17T15:00:00`（裸时间） | 1 | `capture failed: ValueError: --as-of needs a timezone offset when a time is given, got '2026-09-17T15:00:00'` |
| 绿 | 还原参数重跑到 `analysis-recheck/` | 0 | 五个交换产物 sha256 与首次运行**逐个相同** |

红 A 与红 B 都在**读输入阶段**就失败：输入先读、先失败，绝不在输出目录里留下一份
"看起来跑过了"的半成品。红 A 的文件不存在与"文件存在但没有成员"是两件不同的事实，
实现里分成 `FileNotFoundError` 与 `ValueError` 两条路径，没有合并成一个含糊的
"没有成员"（`read_industry_memberships` 对不存在的文件返回空，那是它守的另一条规矩）。

### 24.5 约束零改动：指纹比对

在 1.3 全部真实运行（1 次 capture + 1 次 canonical 拒绝 + 1 次重跑 + 2 次红）之后，
重跑 1.1 的盘点脚本并与**开工时那份清单**逐条比对：

| 集合 | 文件数 | 新增 | 消失 | sha256 变化 |
| --- | --- | --- | --- | --- |
| `data/raw` + `data/snapshots` + `data/watchlist` + `var/jobs` | 5,021 | 0 | 0 | **0** |
| 全量白名单（再加 `configs` / `pyproject.toml` / `uv.lock`） | 5,058 | 0 | 0 | **0** |

两次盘点的 `total_bytes` 都是 300,127,558，逐字节相同。**仓库没有多出任何数据产物**：
所有本轮产物都落在 `var/acceptance/` 下，而该目录已按 `.gitignore` 的
`var/acceptance/` 不入库。

### 24.6 一处与计划措辞的差别（不是偏离行为）

计划写"JSONL 每行直接用领域对象的 `model_dump_json()`，排序键为因子
`(symbol, factor)`、策略 `(strategy_id, symbol)`"——照做。计划同时也说
"完整 JSONL 是明确的 CLI 交换证据，不注册成持久化业务状态"——照做，manifest 里
用一个显式布尔字段把这件事写下来，免得将来有人把这份文件当成正式快照读。

## 二十一、第一阶段（研究证据基线）验收结论（2026-09-19，管理者复跑）

明卷与抽查全部亲自复跑，结论：**通过**。

- 明卷：`tests/unit/test_research_baseline_audit.py` 21 passed；1.2 四文件 32 passed；`tests/integration/test_research_baseline_capture.py` 11 passed；全量 `uv run pytest -q` **890 passed / 0 skipped**（基线 837，只增不减）；`ruff check`／`mypy`（108 files）/`git diff --check` 全绿。
- 抽查一（清单可复现）：本人重跑 `scripts/audit_research_baseline.py`，与交付清单比对 **5,058 个文件 sha256 零差异**——清单是机器产出的，且 `data/raw`、`data/snapshots`、`data/watchlist`、`var/jobs` 自基线以来零漂移。
- 抽查二（提交范围）：三条提交只用白名单文件（`git show --stat` 核对），`tests/**` 差异为纯新增（0 删除断言、0 新增 skip/xfail）。
- 抽查三（基线可复现）：两次独立 capture 的五个产物 `sha256` 逐字节一致，`population` 与 `config_summary` 相同。
- 数字复核：研究池 2,303；四榜可打分 growth 2,302／momentum 2,281／quality 1,697／dividend 1,612；`unknown_industry_symbols` = 9（`000592.SZ`、`000968.SZ`、`002679.SZ`、`300896.SZ`、`600158.SH`、`600185.SH`、`600938.SH`、`601888.SH`、`689009.SH`）；`industry_evidence.origin=canonical` 且带 `source_sha256` 与时区化 `mapping_as_of`。
- 反向验证复核：external 缺一只仍出诊断报告（exit 0），canonical 缺一只仍拒绝（exit 1）；正式状态 pre/post 指纹一致。
- 遗留（已在本节修正）：`ruff format --check .` 的 1 个待重排文件是**本次验收方自己上一轮引入**的（`tests/unit/test_bootstrap_sync.py` 的长断言行），已拆行修正；另把验收方遗留的未跟踪文件 `var/industry-map-2026-09-18.csv` 移入已被忽略的 `var/benchmarks/`。
- 待所有者裁决（见 `BLOCKED.md` 第三节）：是否单独处理 `data/watchlist/` 目录缺失的口径、是否解决脚本层 `tmp_path` 不可用的环境问题。

## 二十五、存储路径解析收敛到一处（2026-09-19，第二步任务 2.1）

### 25.1 做了什么

新增 `data/storage/paths.py`：`resolve_storage_paths(*, config_path=None, environ=None)`
是**唯一**读 env、唯一读配置文件的存储路径解析点，返回冻结 dataclass
`StoragePaths`（`database` / `normalized_root` / `snapshot_root` / `watchlist_root` /
`job_root` + `sources`）。规则：env 优先于配置；配置文件缺失或非法必须抛错；
相对路径保持相对（不做绝对化）；三个 JSON root 沿用既有环境变量与既有默认，
不引入新的配置键。

改动面：`settings.py`（新增 `resolve_config_path`，把非法 YAML 包成 `ValueError`）、
`cli/app.py`（`_storage_paths()` 成为唯一来源，`_store` / `_watchlist_store` /
`_job_store` 都从它取；`doctor` 打印五条生效路径与来源）、`api/app.py`（默认走
统一路径，显式传 root 的调用方保留旧的按 root 数据库位置）、`snapshots/resolve.py`
与 `watchlist/store.py`（新增 keyword-only `database`，显式传入时优先）。

### 25.2 两处需要所有者知道的口径变化

1. **命令现在依赖配置文件可读。** `_store()` / `_job_store()` 以前只读 env，现在
   会加载 `configs/app.yaml`。这是"指定配置文件缺失必须报错"的直接后果，也正是
   计划要的口径；但如果将来有人想在**没有 configs/** 的目录里跑 CLI，得先设
   `ASTOCK_CONFIG` 指到一份合法配置。这属于有意为之，不是回归。
2. **非法 YAML 由 `YAMLError` 改报 `ValueError`**（原始异常挂在 `__cause__`）。
   原因：`doctor` 只捕获 `OSError` / `ValueError` / `ValidationError`，不包装就会
   以一条回溯结束、而不是一条"配置读不了"的失败信息。异常类型变了，报错这件事
   没变。

### 25.3 验证

- 验收命令 `tests/unit/test_storage_paths.py tests/unit/test_settings.py tests/unit/test_api.py`
  → **28 passed**；反向 A（非法 YAML）`astock doctor` 退出码 **1** 且无回溯；
  反向 B（`ASTOCK_DATABASE`）生效路径即该文件且 `sources['database'] == 'env'`。
- 默认后端仍是 `json`；本任务没有切换任何默认读取路径，也没有发布 Parquet 布局。

## 二十六、归一化读取边界（2026-09-19，第二步任务 2.2）

### 26.1 做了什么

三个数据模型（`FinancialInputs` / `ValuationInputs` / `NormalizeOutcome`）原样
从 `pipelines/stages.py` 移入 `data/repository/models.py`，`stages` 继续以同一批
名字重导出；CSV 回放算法搬进 `data/repository/csv.py` 的
`CsvNormalizedRepository`；新增 `data/repository/contracts.py` 声明
`NormalizedRepository` 协议（`@runtime_checkable`）。

`normalize_stage`、`compute_research_universe`、`compute_factor_state`、
`run_analysis`、`run_research_analysis` 与 `run_daily` 都新增同名可选参数
`repository`；为 `None` 时走 CSV 回放（与迁移前完全一致），显式传入时**只**从它读。
`run_research_analysis` 现在归一化**一次**，研究池与完整分析复用同一个 `outcome`
对象（抽出 `research_universe_from_outcome`，只调用既有 stage，不重写算法）。

### 26.2 实测发现（计划片段没写、但比较时会踩）

`RawDataset.fetched_at` 是 provider 用 `datetime.now(UTC)` 打的**墙钟**。因此
`normalize_stage()` 的两次调用**永远不可能相等**——计划给的那段
`assert actual == expected` 在真实仓库上按字面是过不去的。

处理方式：比对前递归摘掉 `fetched_at` 这**一个**字段，其余每一个字段照旧逐项
比对。这不是放宽断言——留着它等于断言"两次调用发生在同一微秒"，那是在断言一件
假事。同理，`AnalysisState` / `ResearchUniverseState` 的相等性比较也按此口径。

这条事实值得记住：以后任何"比对两份 `NormalizeOutcome`"的代码都必须先决定
要不要看 `fetched_at`，默认的比较会永远不相等。

### 26.3 验证

- 验收命令 `tests/unit/test_normalized_repository.py tests/integration/test_analysis_pipeline.py
  tests/integration/test_research_universe_flow.py tests/integration/test_daily_pipeline.py`
  → **46 passed**。
- 反向验证：注入一个必抛异常的 repository、同时给一个**真实可用**的 CSV 根
  （回退在技术上做得到，正因如此它必须是错的）→ `run_research_analysis` 抛
  `RuntimeError`，`read` 只被调用 **1** 次，没有 CSV 回退。
- 依赖方向：`src/astock_lens/data/**/*.py` 里没有任何 `astock_lens.pipelines`
  引用，有专门用例守护。

## 二十二、第二阶段第一刀（2.1＋2.2）验收结论（2026-09-19，管理者复跑）

明卷与抽查全部亲自复跑，结论：**通过**。

- 明卷：2.1 `uv run pytest tests/unit/test_storage_paths.py tests/unit/test_settings.py tests/unit/test_api.py -q` = 28 passed；2.2 四文件 = 46 passed；全量 `uv run pytest -q` = **917 passed / 0 skipped / 0 failed**（5m18s；890 基线 + 27 新增，数字自洽）。
- 行为不变硬证据（本人复跑，非采信日志）：用迁移后代码重跑 capture 到 `var/acceptance/verify-stage2-by-manager/analysis/`，`factors.jsonl`（`2a507477…`）、`strategies.jsonl`（`15ce4f25…`）、`research-universe.json`（`fe817691…`）与迁移前基线**逐字节相同**；基线自身未被覆盖（哈希仍等于第一阶段验收时记录的值）。
- 数据指纹零漂移（本人复跑 `scripts/audit_research_baseline.py`）：5,058 个白名单文件 sha256 与基线清单完全一致，`configs/**`、`data/**`、`var/**` 零改动；工作区干净。
- 反向验证（本人独立重放）：`ASTOCK_DATABASE` 覆盖生效且 `sources["database"] == "env"`；坏 YAML 配置报 `ValueError` 而非静默默认；`tests/unit/test_normalized_repository.py` 中"异常不回退 CSV"与"只读一次"两处为真断言（后者还故意传入不存在的 CSV 根，回退必然失败）。
- 防作弊抽查：两条提交范围均落在计划点名文件内（`6a824fe` 8 个文件、`cee456f` 14 个文件）；`tests/**` 无新增跳过，唯一被删的一行断言来自本次验收方自己的格式修复（`fbeba36`）；`data/` 层未 import `pipelines/`（且有测试守这条）。
- 如实记录的偏差：计划片段里的 `assert actual == expected` 按字面不可成立（`RawDataset.fetched_at` 是取数墙钟，两次调用必然不同）。执行方改为只摘 `fetched_at` 一个字段、其余逐项比对，并在测试与评审记录里写明——本次验收确认它只摘了这一个字段，比较强度未被放宽。
- 待所有者裁决（本轮未动）：① 是否把"全量测试的沙箱模式差异"写进 `README.md`/`Makefile`（本次验收在普通模式下 917 passed/5m18s，未见执行方报告的删除守卫拖慢，说明是执行环境特有）；② 是否恢复沙箱下不可用的 `tmp_path` 夹具（现用 `local_tmp`）。

## 二十三、安装 PyArrow（2026-09-19，第二阶段 2.3 前置）

所有者指示"装 pyarrow"。实测与处理：

- `uv sync --extra data --extra providers` 在本机网络下**卡在 `polars-runtime-32`（46.1MiB）轮子**：直连 PyPI 约 200–230KB/s 且多次重试、清华与阿里云镜像同样超时（分别 125s 超时 / 长时间停在同一下载）。已中止，未污染依赖树（`uv.lock` 未改）。
- 改用 `uv pip install "pyarrow>=17.0"` → **装成 `pyarrow==25.0.1`**（本地缓存命中，127ms）。`duckdb 1.5.5`、`akshare 1.18.94` 原有环境保留。
- **`polars` 仍未安装**，且当前代码库**没有任何模块 import polars**（`rg 'import polars|from polars' src/ scripts/ tests/` 为空）；第二阶段 2.3–2.6 只需要 PyArrow。若后续确有需要，请在网络条件好时补跑 `uv sync --extra data --extra providers`（它不会移除已装的 pyarrow）。
- 环境验证：`uv run mypy`（112 源文件）无问题；`ruff check .` 全绿；全量 `uv run pytest -q` = **917 passed / 0 skipped**（5m10s），与装之前一致。

## 二十七、跑测试的耗时归因与并行评估（2026-09-19）

所有者问"每次执行耗时这么长，是不是跑测试太慢"。本轮把耗时拆开实测，结论是**测试本身不慢，
锅在运行环境与跑法**。

### 27.1 测试本身的量级

917 个用例、剥离 shim 后串行跑，全量 **560.90s**（9 分 20 秒）——平均 0.61s/用例。对一个含
"全池研究分析"（研究池 2,303 只、因子行 55,272）的仓库，这是正常量级，不是病态。

### 27.2 真正的单价：注入的删除 shim

环境经 `PYTHONPATH` 注入 `sitecustomize.py`，把 `os.remove` / `os.rmdir` / `shutil.rmtree` /
`Path.unlink` / `Path.mkdir` 改道（每条操作起 Node 子进程做守卫检查 + broker 往返）。
同一次 `mkdir + write`：

| 运行方式 | 耗时 |
| --- | --- |
| 注入 shim | **0.372s** |
| `PYTHONPATH=` | **0.0125s** |

差约 30 倍，而一次全量有上万次这类操作。本轮还观察到 shim 会随时间**退化**：上一轮同一跑法
全量 582.30s，本轮单条 stress 用例（假源、5,300 只标的）21 分钟跑不完。

### 27.3 并行（pytest-xdist）实测：本仓库不要用

| 跑法（都剥离 shim） | 结果 | 耗时 |
| --- | --- | --- |
| 非 stress 子集 + `-n auto` | 912 passed + 1 failed | 350.97s |
| 全量 + 串行 | 916 passed + 1 failed | **560.90s** |
| 全量 + `-n auto` | 916 passed + 1 failed | 711.29s |

① 并行**更慢**（711.29s 对 560.90s：用例多为真实计算，12 个 worker 互相争抢）；
② 并行**多一条假失败**：`tests/unit/test_akshare_provider.py::test_process_isolation_bounds_a_non_returning_live_transport`
（`spawn` 子进程后断言 `elapsed < 1.0`）在争抢下超时，而**串行时它是绿的**。插件已移除。

### 27.4 两条"环境敏感"用例（不是本切片引入）

1. `tests/stress/test_bootstrap_scale_properties.py::test_mixed_failures_stay_explicit_and_the_run_still_converges`：
   剥离 shim（运行变快）后**串行连跑两次都失败**（118.00s / 78.20s，同一断言）。机制见
   `BLOCKED.md` 第三节第 5 条。
2. 上面 27.3 那条 akshare 用例：只在并行下红。

两者的共同点是"用真实墙钟给并发/进程隔离设边界"，机器变快或发生争抢时，边界假设不再成立。
本切片（2.1 / 2.2）没碰 `bootstrap*` 与 akshare provider；串行跑时 xdist 也不参与。

### 27.5 处置

- `docs/DEVELOPMENT.md` 新增 §7（分层跑法 + 运行环境实测）；
- `README.md` 测试章节、`AGENTS.md` 命令节各留一个指针；
- `Makefile` 新增 `test-fast` / `test-stress`，并让 `PYTHONPATH` 可透传（`make test PYTHONPATH=`）；
- `pyproject.toml` 增加 `[[tool.uv.index]]`（阿里云镜像，default=true）。它同时闭合了上一会话
  记为"未决隐患"的 `uv.lock` 换源问题——镜像源从"只存在于 lock"变成"有正式声明且可复现"；
- `pytest-xdist` 装后又卸；`tests/conftest.py` 未改；`configs/**`、`data/**`、`var/**` 零改动。

## 二十八、股票发现 MVP 立项与当前真实基线锁定（2026-09-19）

根据项目所有者指导，正式立项 Stock Discovery MVP，消除与代码库当前真实状态的文档漂移。

### 28.1 真实仓库基线记录（Fresh Baseline Evidence）

于实施前实测记录本切片起点状态，绝不复用过时数字：

- **Git HEAD SHA**: `0876b2aa4df9c9c72b607bcd01fc02d638fcf12c`
- **工作区状态 (`git status --short`)**:
  ```text
  ?? docs/superpowers/plans/2026-09-19-stock-discovery-mvp-implementation-plan.md
  ?? docs/superpowers/specs/2026-09-19-stock-discovery-mvp-design.md
  ```
  （两份规划文档就位前，工作区零脏改动）
- **测试实测基线 (`uv run --no-sync pytest tests/unit tests/contract tests/integration tests/artifacts -q`)**:
  `913 passed, 10 warnings in 69.39s (0:01:09)`，退出码 0，无任何失败与跳过。

### 28.2 确认已提交的研究基线硬证据（Committed Baseline Evidence）

复核版本库中已提交固化的研究分析基线产物（由提交 `bd5a93a` / `0111eea` 产生，落地于 `var/acceptance/baseline-20260918/analysis/`，元数据见 `manifest.json`）：

- **Research Universe**: **2,303** 只（产物 `research-universe.json`，sha256: `fe817691aa0e0925115a24c507739a1bdbd2be9bbd2f86c989be8655a100e941`）
- **FactorResult**: **55,272** 条（产物 `factors.jsonl`，sha256: `2a50747793dc78e64c721867a04922e0b762226a2b45656d6c9b2800a47a597c`）
- **StrategyResult**: **13,818** 条（产物 `strategies.jsonl`，sha256: `15ce4f251cb4ad83b58f07eaafab69f8ffbc4bea7628644319ae44d58989cbd3`）
- **六策略真实覆盖分布（已提交基线证据）**：
  - `growth`: 2,302 只可打分
  - `momentum`: 2,281 只可打分
  - `quality`: 1,697 只可打分
  - `dividend`: 1,612 只可打分
  - `value`: 2 只可打分（显式受限于估值覆盖）
  - `garp`: 1 只可打分（显式受限于估值覆盖）
  - `industry_trend`: 0 只可打分（行业 membership 已落地 5,542 只 / 124 行业，覆盖研究池 2,294/2,303 只；打分为 0 系行业聚合指标与打分口径未获批准，属于产品规则阻塞而非数据缺失）

以上数据明确标注为版本库中已提交的审计基线证据（Committed Baseline Evidence），证明代码库已具备全研究池策略打分与排序能力。

### 28.3 修正 ROADMAP 文档漂移与边界锁定

1. **废除"全市场仅 5 只能打分"的过时陈述**：
   - 2026-09-18 策略长度历史（252 根 bar）与三大表批量获取已在 2,303 只研究池上落地，Growth / Momentum / Quality / Dividend 策略已具备全池级真实横截面排序能力。更新相关条目为已完成状态。
2. **纠正 Industry Trend 阻塞口径**：
   - 替换原"缺行业数据"口径为准确事实：`行业 membership 已可用；缺口是行业聚合指标、Industry Trend 打分口径及对应实现仍未批准/完成。`
3. **显式保持 Value / GARP 估值覆盖限制**：
   - 明确 Value / GARP 策略仍然受限于 neodata 估值数据（PE TTM、PB、PEG）覆盖，目前仅个位数标的可打分。
4. **归档规范与实施方案**：
   - 落地设计规格：`docs/superpowers/specs/2026-09-19-stock-discovery-mvp-design.md`；
   - 落地实施计划：`docs/superpowers/plans/2026-09-19-stock-discovery-mvp-implementation-plan.md`。

## 二十九、只读策略选股与研究画像验收实测（Task 7，2026-09-19）

本节记录股票发现 MVP 只读验收检查（Task 7）的实测证据。本轮运行严格遵守**零外部 Provider 抓取**边界，仅读取本地已落地数据与快照。

### 29.1 正式 STRATEGY 快照状态确认（Step 1）

- 检查 `data/snapshots/STRATEGY/2026-09-17.json`：文件存在（624,388 字节，mtime 2026-09-17 22:47:34），存储格式为标准 JSON 快照，包含 30 条 `StrategyResult` 评估记录（覆盖 5 只标的 × 6 个策略）。
- 检查 DuckDB 快照存储（`var/astock.duckdb` 之 `snapshots` 表）：`kind='STRATEGY', as_of='2026-09-17'` 条目同样存在且内容一致。
- 依据规约，快照已存在且内容完备，无需也不得执行重新计算（避免触发 `SnapshotConflictError`，且杜绝静默网络访问）。

### 29.2 CLI 策略选股实测（Step 2 & Step 3）

命令运行实测数据（各命令前置 `time uv run astock screen <strategy> --as-of 2026-09-17 --top 20`）：

| 策略 (`strategy_id`) | total | eligible | scored | ranked | returned | 覆盖告警 (Coverage Warning) | 墙钟耗时 | 榜首标的 (Top 1) |
|---|---|---|---|---|---|---|---|---|
| `growth` | 5 | 5 | 5 | 5 | 5 | 无（全覆盖） | 0.623s | `300750.SZ` (score=90.00, pctl=0.9000) |
| `momentum` | 5 | 5 | 5 | 5 | 5 | 无（全覆盖） | 0.606s | `000001.SZ` (score=93.33, pctl=1.0000) |
| `quality` | 5 | 3 | 3 | 3 | 3 | `only 3/5 stored results have a score; ranking reflects available data` | 0.478s | `600519.SH` (score=83.33, pctl=1.0000) |
| `dividend` | 5 | 5 | 5 | 5 | 5 | 无（全覆盖） | 0.611s | `000001.SZ` (score=80.00, pctl=1.0000) |
| `value` | 5 | 2 | 2 | 2 | 2 | `only 2/5 stored results have a score; ranking reflects available data` | 0.605s | `000001.SZ` (score=83.33, pctl=1.0000) |
| `garp` | 5 | 1 | 1 | 0 | 1 | `only 1/5 stored results have a score; ranking reflects available data` | 0.605s | `600519.SH` (score=100.00, pctl=None) |

- **行为特征核实**：
  1. `growth` / `momentum` / `dividend` 无告警，全部标的参与打分与分位数排名；
  2. `quality` 准确剔除非实体经营（如银行缺毛利率）标的，仅 3 只合格打分并触发覆盖告警；
  3. `value` 与 `garp` 严格受限于 neodata 估值覆盖（仅有落地数据的标的可计算），准确触发覆盖告警；
  4. `garp` 榜首仅 1 只标的，`rank_percentile` 准确呈现为 `None`（单样本不满足分位数计算），绝不静默兜底为 0.0。

### 29.3 全量 2,303 只研究池基线筛选压测（Committed Baseline Query Benchmark）

基于已提交固化的全量研究分析产物（`var/acceptance/baseline-20260918/analysis/strategies.jsonl`，共 13,818 行记录），调用 `screen_strategy` 进行真实内存排序与筛选性能压测：

| 策略 | 研究池总数 | eligible | scored | ranked | top 20 返回 | 纯查询/排序耗时 | 覆盖告警说明 | 榜首标的 |
|---|---|---|---|---|---|---|---|---|
| `growth` | 2,303 | 2,302 | 2,302 | 2,302 | 20 | 15.01ms | `only 2302/2303 scored` | `001309.SZ` (score=99.60, pctl=1.0) |
| `momentum` | 2,303 | 2,281 | 2,281 | 2,281 | 20 | 30.95ms | `only 2281/2303 scored` | `300741.SZ` (score=99.76, pctl=1.0) |
| `quality` | 2,303 | 1,697 | 1,697 | 1,697 | 20 | 13.14ms | `only 1697/2303 scored` | `600519.SH` (score=85.56, pctl=1.0) |
| `dividend` | 2,303 | 1,612 | 1,612 | 1,612 | 20 | 14.71ms | `only 1612/2303 scored` | `002271.SZ` (score=99.35, pctl=1.0) |
| `value` | 2,303 | 2 | 2 | 2 | 2 | 12.16ms | `only 2/2303 scored` | `000001.SZ` (score=83.33, pctl=1.0) |
| `garp` | 2,303 | 1 | 1 | 0 | 1 | 12.21ms | `only 1/2303 scored` | `600519.SH` (score=100.00, pctl=None) |

- **压测结论**：在 2,303 规模横截面上，`screen_strategy` 查询与全排序操作耗时均在 12–31ms 之间，排序稳定且确定性满足亚秒响应要求。

### 29.4 API 冒烟实测与契约验证（Step 4 & Step 5）

使用 `FastAPI TestClient` 进行只读端点调用，实测结果：

1. **`GET /strategies?as_of=2026-09-17`**：
   - 状态码：`200 OK`
   - 返回结构：6 个策略的 `StrategyCoverage` 对象数组，包含每个策略的 `total_count`、`eligible_count`、`scored_count`、`ranked_count`。
2. **`GET /strategies/growth/results?as_of=2026-09-17&limit=20`**：
   - 状态码：`200 OK`
   - 返回结构：包含 `strategy_id="growth"`、`coverage` 摘要以及 5 条排序结果项（Top 1: `300750.SZ`）。
3. **`GET /stocks/300750.SZ?as_of=2026-09-17`**：
   - 状态码：`200 OK`
   - 返回结构：
     - `symbol="300750.SZ"`, `as_of="2026-09-17"`
     - `universe={"included": True, "exclusion_rules": []}`
     - `factors`: 24 个因子结果已落地
     - `strategies`: 6 个策略评估已落地
     - `candidate_status="not_published"`（严格遵守安全发布边界，由于候选阶段未批准/阻断，绝不伪造入选状态）
     - `candidate=None`
4. **`GET /candidates?as_of=2026-09-17`**：
   - 状态码：`404 Not Found`
   - 返回详情：`{"detail": "no CANDIDATE snapshot for 2026-09-17"}`。
   - 验证结论：由于 Candidate 阶段因绝对质量门槛与 Market Validation 依赖而安全阻断，未写出快照，查询端点严格返回 404，不静默返回空列表或假成功。

## 三十、股票发现 MVP 最终验证与停机门禁（Task 8，2026-09-19）

本节记录股票发现 MVP 最终验证（Task 8）的完整质量检查证据与停机门禁确认。

### 30.1 仓库全量检查结果（Step 1）

在当前支持的工作环境下执行全套仓库门禁检查，实测结果如下：

1. **快速回归与领域测试 (`make test-fast PYTHONPATH=`)**：
   `955 passed, 10 warnings in 70.71s (0:01:10)`，退出码 0。
2. **代码风格与规则检查 (`uv run ruff check .`)**：
   `All checks passed!`，退出码 0。
3. **格式检查 (`uv run ruff format --check .`)**：
   `230 files already formatted`，退出码 0。
4. **严格类型检查 (`uv run mypy`)**：
   `Success: no issues found in 115 source files`，退出码 0。
5. **Git 空白与冲突检查 (`git diff --check`)**：
   无任何输出，退出码 0。
6. **全市场压力测试 (`uv run --no-sync pytest tests/stress -v`)**：
   `4 passed in 62.24s (0:01:02)`，4 项标的规模收敛与断点续跑压力属性测试全绿，退出码 0。
7. **全量回归测试 (`PYTHONPATH= uv run --no-sync pytest -q`)**：
   `959 passed, 10 warnings in 131.69s (0:02:11)`，全套 959 项测试无一失败、无一跳过，退出码 0。

### 30.2 语义隔离与防泄露审计（Step 2 & Step 3）

1. **严禁跨策略综合打分泄漏（Cross-Strategy Score Leakage Scan）**：
   执行 `rg -n "global_score|combined_strategy_score|cross_strategy_score" src configs`：
   输出 0 行匹配（退出码 1），确认未引入任何跨策略大乱斗加权或全局综合分。
2. **严禁未授权资格生产配置（Production Qualification Config Scan）**：
   执行 `find configs -maxdepth 2 -type f -path '*/qualifications/*' -print`：
   输出 0 项（退出码 0），`configs/` 目录保持为 `app.yaml`、`factors/`、`market_regime.yaml`、`providers.yaml`、`strategies/`、`universe.yaml`，绝对质量门槛生产配置未被自行发明。
3. **API 计算隔离审计（API Computation Engine Isolation）**：
   执行 `rg -n "astock_lens\.pipelines|build_scanner|strategy_stage|factor_stage|run_analysis" src/astock_lens/api`：
   输出 0 行匹配（退出码 1）；测试 `test_api_never_imports_the_computation_engines` 自动化断言通过，确认 API 仅读取已有快照，绝对不导入或调用因子与策略计算引擎。
4. **选股只读保证审计（Screen CLI Read-Only Guarantee）**：
   测试 `test_screen_read_only_guarantee` 基于目录树 SHA256 指纹比对通过，确认 `astock screen` 执行前后快照目录（`snapshots`）、自选目录（`watchlist`）与作业目录（`jobs`）无任何新增、修改或删除。

### 30.3 停机门禁确认（Mandatory Stop Gate）

股票发现 MVP 现已完整可用，覆盖 CLI `astock screen` 与 API 端点 `/strategies`、`/strategies/{id}/results`、`/stocks/{symbol}`。
根据架构原则与停机门禁要求，严格禁止越界推进以下后续阶段工作：
- 严禁自行发明或创建六策略绝对质量生产门槛配置；
- 严禁将策略顶部选股结果直接升级或包装为 `Candidate` 对象；
- 严禁合成假 `MarketValidation.NEUTRAL` 或假 `Signal.NO_SIGNAL`；
- 严禁将选股结果宣称为“买入推荐”或提供买卖结论；
- 严禁初始化 React Web 页面；
- 严禁擅自修改策略打分权重；
- 严禁在缺乏真实数据时臆造估值数据来修补 Value/GARP。

所有后续工作必须遵循 ROADMAP 明确划分的 P1–P5 独立阶段，经项目所有者审定后方可启动。

## 三十一、估值覆盖扩容（P1，2026-09-19）

计划：`docs/superpowers/plans/2026-09-19-valuation-coverage-implementation-plan.md`。
本轮把"估值覆盖受限"从一句结论变成可复算的证据与可重复运行的补齐能力。

### 31.1 交付物

| 交付 | 位置 | 作用 |
| --- | --- | --- |
| 落地按块身份合并 | `src/astock_lens/data/sync.py::land_neodata_blocks` | 分批补抓不再互相覆盖 |
| 研究池名单读取 | `src/astock_lens/data/sync.py::read_universe_symbols` | JSON `research_symbols` / CSV `symbol`，空名单报错 |
| 覆盖报告 | `src/astock_lens/calibration/valuation_coverage.py` | 字段级 + 策略估值侧因子交集 |
| 补抓命令 | `astock sync-valuation` | 缺口驱动多轮、可重跑、缺口显式 |
| 覆盖命令 | `astock valuation-coverage` | 只读核对，分母为显式研究池 |

覆盖模块放在 `calibration/`（报告层）而不是 `data/quality/`：它要复用
`factors/valuation.py` 的因子语义，而数据层不得依赖因子层（`AGENTS.md` 架构边界）。

### 31.2 失败证据（RED）

`land_neodata_blocks` 原为整天覆盖写。改动前先跑新用例：

```text
FAILED tests/unit/test_neodata_landing.py::test_the_same_day_replaces_and_another_day_is_kept
FAILED tests/unit/test_neodata_landing.py::test_a_second_landing_the_same_day_keeps_the_first_batch
2 failed, 9 passed in 0.43s
```

断言实际输出 `len(rows) == 2`（旧行为只剩最后一批），期望为并集 3；这正是"多轮补抓
会把前一轮冲掉"的证据。实现合并后 17 passed。

任务 2/3 是新增模块与新增命令，没有既有行为可以先失败；它们的证据是新增测试本身。

### 31.3 真实验收数字（不是估算）

`astock valuation-coverage --as-of 2026-09-17 --universe
var/acceptance/baseline-20260918/analysis/research-universe.json --output
var/acceptance/valuation-coverage-20260919/report.json`：

- 落地文件：`data/raw/neodata/valuation/2026-09-17.csv`（230 条观测，2 只标的）；
- 研究池 2,303 只；有任意估值 2 只，缺口 2,301 只；
- 因子级：`pe_ttm`/`pb`/`ps_ttm`/`pe_percentile`/`pcf_operating_ttm` 各 2 只，
  `peg` 1 只，`dividend_yield_ttm` 0 只；
- 策略估值侧可打分：`value` 2 / 2,303；`garp` 1 / 2,303。

**这与 `var/acceptance/baseline-20260918/analysis/strategies.jsonl` 的分布独立吻合**
（value 2 / garp 1）——一个来自原始内容块经真实因子语义计算，一个来自策略产物，
两条路径对上了。同时可见字段级与因子级必须分开报：字段 `peg` 有 2 只有值，
因子 `peg` 只有 1 只可计算（`000001.SZ` 的 PEG 为负，判 `NOT_APPLICABLE`）。

### 31.4 前置门禁：凭证过期，未发起真实抓取

```text
load_token status: expired
candidate: ~/.workbuddy/plugins/cache/cb_teams_marketplace/finance-data/1.6.0/skills/.neodata_token exists=True
（saved_at=2026-09-18 20:07，TTL 12 小时）
```

`astock sync-valuation --as-of 2026-09-17 --universe … --limit 100` 实测：
退出码 1，输出 `provider neodata is not usable: 凭证已过期（12 小时有效）`，
**未发出任何请求**（健康检查在循环之前）。这是 blocker 的当前真实状态：
能力已就绪，缺的是有效凭证。

### 31.5 全量回归

| 检查 | 结果 |
| --- | --- |
| `uv run pytest tests/unit tests/integration tests/contract tests/artifacts -q` | `972 passed in 72.09s` |
| `PYTHONPATH= uv run pytest -q`（含 stress） | `976 passed, 10 warnings in 133.50s` |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `233 files already formatted` |
| `uv run mypy` | `Success: no issues found in 116 source files` |

文档订正：`docs/REMAINING_PRODUCT_BLOCKERS.md` §2 的"抓了 5 只"改为"请求 5 只、回 2 只"，
"`SOURCE_ERROR` 或 `NULL`"改为实际口径（`NOT_APPLICABLE` / `NULL`），
并注明 90% 覆盖率阈值无设计文档出处、属 `Deferred`，需所有者签发。

## 三十二、估值全池补抓实跑与覆盖结果（2026-09-19，凭证刷新后）

### 32.1 源的"批量"是名义上的（本轮实测，推翻设计规格 §24.1 的吞吐估算）

| 每批带几只 | 一次请求返回几块 | 每块耗时 |
| --- | --- | --- |
| 1 | 1（100% 命中） | ~1.8s |
| 3 | 4 块 / 3 次调用 | ~2.3s |
| 5 | 4 块 / 3 次调用 | ~2.5s |
| 10 | 2 块 / 2 次调用 | ~2.3s |

结论：**一次请求无论带几只标的，响应都被截到 1–2 个内容块**。设计规格 §24.1 写的
"全市场按 10 只/次约 558 次调用，与 westock 的 37 分钟同量级"因此不成立；
全池 2,303 只的实际量级是**约 1,900 次调用**（本轮实跑 8 轮合计约 1,900 次），
这也是本命令默认 `--batch-size 5` 的原因。

### 32.2 实跑（`astock sync-valuation --as-of 2026-09-19 --batch-size 5 --max-rounds 8`）

| 轮 | 请求 | 落地 | 仍缺 |
| --- | --- | --- | --- |
| 1 | 2,267 | 817 | 1,450 |
| 2 | 1,450 | 522 | 928 |
| 3 | 928 | 335 | 593 |
| 4 | 593 | 214 | 379 |
| 5 | 379 | 137 | 242 |
| 6 | 242 | 88 | 154 |
| 7 | 154 | 56 | 98 |
| 8 | 98 | 36 | 62 |

- 耗时约 77 分钟，退出码 1（缺口未闭合——这是事实，不是失败）；
- 落地文件 `data/raw/neodata/valuation/2026-09-19.csv`，2,241 块（97.3%）；
- 缺口清单 `var/acceptance/valuation-backfill-20260919/missing.json`（62 只，原样保留）；
- `2026-09-17.csv` 一字未动，冻结基线的输入保持原样。

### 32.3 覆盖结果（`report-20260919.json`，独立于策略产物）

| 口径 | 2026-09-17（补抓前） | 2026-09-19（补抓后） |
| --- | --- | --- |
| 有任意估值（标的） | 2 | 2,241 / 2,303 |
| `pe_ttm` / `pb` / `pe_percentile`（字段） | 2 | 1,958 |
| `ps_ttm` / `pcf_operating_ttm`（字段） | 2 | 2,241 |
| `peg`（字段 / 因子） | 2 / 1 | 1,872 / 957 |
| **Value 估值侧可打分** | **2** | **1,578** |
| **GARP 估值侧可打分** | **1** | **850** |

两处"字段有值但因子不可算"是语义而非缺失，必须分开看：
`pcf_operating_ttm` 446 只市现率为非正、`peg` 915 只 PEG 为非正 → `NOT_APPLICABLE`。
`dividend_yield_ttm` 仍是 0（源端该列整列为空，Value 已按评审结论不把它列为必需项）。

### 32.4 修掉的两个 O(标的数 × 观测数) 退化

报告命令首次实跑耗时 251 秒。定位到两处：`_metric_coverage` 把 `set()` 写在推导式里
（每个 symbol 重建一次集合），以及 `covered_symbols` 用 `any(... for item in available)`
逐 symbol 扫全池观测（2,303 × 25.7 万）。两处都改成先收集合再按研究池顺序取，
**251 秒 → 10 秒**，报告 JSON 与优化前逐字节一致（`identical to pre-optimization report: True`）。

同时把因子层从"每次调用喂全池数据集"改成按 symbol 分组喂入：`ValuationFactor.compute`
是按 symbol 线性过滤的，喂全池会让 2,241 × 7 次调用各扫 25.7 万条。语义等价，
原因是因子只读属于该 symbol 的行（含"从没有过该指标"与"晚于 as_of"两种区分）。

## 三十三、Candidate Readiness 升级：估值时点可见性与基线钉住（2026-09-20）

### 33.1 基线状态

- 启动 HEAD：`dd45d1de77b80229447822b57d4f8de5b104c87b`
- 全量测试基线：977 passed, 10 warnings, 0 failed
- 类型与代码检查：`ruff check .` 全部通过，`mypy` 116 个源文件全部通过

### 33.2 估值时点可见性（PIT）隔离回归

- 在 `tests/unit/test_normalized_repository.py` 中新增 `test_valuation_inputs_point_in_time_isolation`：
  - 构造包含 `2026-09-17.csv` 和 `2026-09-19.csv` 且同一标的（000001.SZ）指标不同的临时 Raw 树；
  - 验证 `as_of=2026-09-17` 严格只读取 `2026-09-17.csv`，指标值为 5.18；
  - 验证 `as_of=2026-09-19` 读取 `2026-09-19.csv`，指标值为 6.25；
  - 冻结基线 `data/raw/neodata/valuation/2026-09-17.csv` 零变动。

### 33.3 估值补齐后的只读研究分析基线固化（任务 2）与休市日对齐修复

- **休市日对齐修复**：
  - 发现事实：当 `as_of` 为休市日（如周六 2026-09-19），全市场当天无日线 bar。原 `UniverseBuilder.build` 中 `traded = {bar.symbol for bar in bars if bar.trade_date == as_of.date()}` 会将休市误判为全市场停牌，排除全部股票（`research_count: 0`）。
  - 修复方案：在 `src/astock_lens/universe/builder.py` 中，当 `as_of.date()` 当天全市场无 bar 时，自动对齐不晚于 `as_of` 的最近有效交易日；并增加 `test_a_non_trading_day_as_of_aligns_with_latest_effective_trade_date` 单元测试。
  - **所有者要求备忘**：后续需单独列出休市日日历，并在休市日当天直接跳过获取股市行情数据。
- **产物固化与层级统计**（`var/acceptance/post-valuation-20260919/analysis/`）：
  - 研究池基线：**2,303 只**（`research_count: 2303`）；
  - 因子层：55,272 条（2,303 × 24）；
  - 策略层：13,818 条（2,303 × 6）；
  - 六策略打分数量：
    - growth: evaluable=2,302, ranked=2,302
    - momentum: evaluable=2,281, ranked=2,281
    - quality: evaluable=1,697, ranked=1,697
    - dividend: evaluable=1,612, ranked=1,612
    - value: evaluable=**1,578**, ranked=**1,578**（旧基线为 2）
    - garp: evaluable=**849**, ranked=**849**（旧基线为 1）
  - 估值因子 DataStatus 分布：
    - `pe_ttm`: VALUE 1,958, NOT_APPLICABLE 62, NULL 283
    - `pb`: VALUE 1,958, NOT_APPLICABLE 62, NULL 283
    - `ps_ttm`: VALUE 2,239, NOT_APPLICABLE 64
    - `pe_percentile`: VALUE 1,958, NOT_APPLICABLE 62, NULL 283
    - `pcf_operating_ttm`: VALUE 1,794, NOT_APPLICABLE 509
    - `peg`: VALUE 957, NOT_APPLICABLE 977, NULL 369
  - 产物 SHA256：
    - `research-universe.json`: `6030cd9fe7573b31cc9e1abd2abf3ec44e9e0e08b40ad466b2a91ebd10404654`
    - `factors.jsonl`: `66d299b293f92b28a1e6ef0220cd3b81b0e65d9bfb73059b905a3cfdd46b9a3e`
    - `strategies.jsonl`: `867975da6cdba9e292cdd9b8ee363636b276c44d6da99ef0ec41cf28e0abd48e`
    - `calibration.json`: `af9c5e91e510595304cc71cb31806cf9003ae6451591784537d6c963392fa09d`
    - `calibration.md`: `e2550effa6c562e228208737c6cb8d51f47b0bfedc623b891d38af9858c1651f`

### 33.4 正式快照发布与等价性验证（任务 4）

- **正式执行写入**：
  - 运行 `astock daily --as-of 2026-09-19 --allow-incomplete`；
  - 产出快照：
    - `data/snapshots/FACTOR/2026-09-19.json` (80.5MB, 55,272 条记录)；
    - `data/snapshots/UNIVERSE/2026-09-19.json` (774KB, 2,303 只研究池标的)；
    - `data/snapshots/STRATEGY/2026-09-19.json` (290.6MB, 13,818 条策略评分)；
  - `data/snapshots/CANDIDATE/2026-09-19.json` 依法未生成。
- **调度阶段状态核验（`var/jobs/2026-09-19.json`）**：
  - `NORMALIZE`：SUCCEEDED（1,675,723 行）；
  - `COMPUTE_FACTORS`：SUCCEEDED（5,008 行入，120,192 行出）；
  - `BUILD_UNIVERSE`：SUCCEEDED（5,565 行入，2,303 行出）；
  - `RUN_STRATEGIES`：SUCCEEDED（2,303 行入，13,818 行出）；
  - `GENERATE_DAILY_SNAPSHOT`：SUCCEEDED（写入 FACTOR, UNIVERSE, STRATEGY）；
  - `DETECT_REGIME`：BLOCKED（缺少市场状态阈值，拒绝伪造）；
  - `MARKET_VALIDATE`：BLOCKED（缺少技术/流动性验证阈值，拒绝伪造）；
  - `RUN_SIGNALS`：BLOCKED（缺少买卖信号阈值，拒绝伪造）；
  - `BUILD_CANDIDATES`：BLOCKED（无有效上游信号、未获所有者批准的绝对门槛，拒绝发布 Candidate）；
  - `UPDATE_WATCHLIST`：BLOCKED（V1 状态流转需用户驱动与状态机验证）。
- **与任务 2 只读分析全量逐条等价性比对**：
  - STRATEGY：13,818 条记录完全等价；
  - UNIVERSE：2,303 只研究池标的及字段完全等价；
  - FACTOR：55,272 条记录完全等价。
- **Candidate 绝对隔离性与 API 契约验证**：
  - API 端点 `GET /candidates?as_of=2026-09-19` 返回 `404 {"detail": "no CANDIDATE snapshot for 2026-09-19"}`；
  - `GET /strategies?as_of=2026-09-19` 正常返回六策略覆盖汇总，Value 达 1,578，GARP 达 849。

### 33.5 六策略选股榜正式快照验收与单股画像抽查（任务 5）

- **六策略 CLI 只读选股榜实测（`astock screen <strategy> --as-of 2026-09-19 --top 20`）**：
  - `growth`：total=2303, eligible=2302, scored=2302, ranked=2302, returned=20, 耗时 8.91s（榜首 `001309.SZ` score=99.60）；
  - `momentum`：total=2303, eligible=2281, scored=2281, ranked=2281, returned=20, 耗时 8.31s（榜首 `300741.SZ` score=99.76）；
  - `quality`：total=2303, eligible=1697, scored=1697, ranked=1697, returned=20, 耗时 8.34s（榜首 `600519.SH` score=85.56）；
  - `dividend`：total=2303, eligible=1612, scored=1612, ranked=1612, returned=20, 耗时 8.31s（榜首 `002271.SZ` score=99.35）；
  - `value`：total=2303, eligible=1578, scored=1578, ranked=1578, returned=20, 耗时 8.35s（榜首 `601336.SH` score=93.68）；
  - `garp`：total=2303, eligible=849, scored=849, ranked=849, returned=20, 耗时 8.68s（榜首 `000688.SZ` score=96.24）。
- **只读零突变核验**：
  - 在执行 6 个 screen 查询前后，对 `data/snapshots`、`data/watchlist`、`var/jobs` 全部文件状态与哈希进行严格比对：**零变动（Zero Mutation）**。
- **单股画像抽查（`GET /stocks/{symbol}?as_of=2026-09-19`）**：
  - Value 榜首 `601336.SH`（新华保险）：`universe.included=True`，`candidate_status="not_published"`，`candidate=None`；6 个估值因子状态全为 `VALUE`，Value 策略得分 93.68，分位数 1.0；
  - GARP 榜首 `000688.SZ`（国城矿业）：`universe.included=True`，`candidate_status="not_published"`，`candidate=None`；6 个估值因子状态全为 `VALUE`，GARP 策略得分 96.24，分位数 1.0；
  - 因子层数据与策略层打分无缝衔接，且绝对未产生伪造候选。
- **产品状态文档订正**：
  - 更新 `docs/ROADMAP.md` 与 `docs/REMAINING_PRODUCT_BLOCKERS.md`，彻底移除“估值仅覆盖个位数”的过时结论，明确 Value 1,578 只与 GARP 849 只的打分基准；
  - 在 `ROADMAP.md` 中立项记录用户关于“单独列出休市日并在休市日跳过股市数据抓取”的后续待做项。

### 33.6 研究池行业覆盖核验与决策级 Blocker 保持（任务 6）

- **研究池行业覆盖核验统计**：
  - 研究池总数：**2,303 只**；
  - Canonical 映射已覆盖：**2,294 只**；
  - 覆盖率：**99.61%**；
  - 缺口数量：**9 只**；
  - 缺失标的清单（9 只）：
    - `000592.SZ`（平潭发展）
    - `000968.SZ`（蓝焰控股）
    - `002679.SZ`（福建金森）
    - `300896.SZ`（爱美客）
    - `600158.SH`（中体产业）
    - `600185.SH`（珠免集团）
    - `600938.SH`（中国海油）
    - `601888.SH`（中国中免）
    - `689009.SH`（九号公司）
- **根因调查结论**：
  - 经排查 `data/raw/westock/industry/2026-09-18.csv`（上游源端 124 个申万二级行业抓取结果），这 9 只标的在源端各行业成分股中**完全缺失**，并非解析器（Parser）或代码逻辑 Bug。
  - 依第一性原理与 `AGENTS.md` 架构红线：**严禁静默兜底，严禁伪造假行业**。
- **决策级校准门禁（Blocker）保持**：
  - 依据设计规格与校准契约，决策级 Candidate 审定要求 100% 行业覆盖；当 Canonical 存在 9 只缺口时，系统依法抛出并保持 `IndustryCoverageUnavailable` 阻断。
  - 此 Blocker 为**产品安全预期行为**，在获得完备行业全源或所有者正式豁免前，绝对禁止在正式状态中假装完整。
  - 任务 7 的校准分析将通过显式标记的诊断链路（`--industry-map` + `diagnostic_only=True`）产出分布建议包，绝不破坏正式状态。

### 33.7 绝对资格门槛诊断校准包与全量验证门禁（任务 7 与任务 8）

- **诊断级校准包产出（任务 7）**：
  - 显式导出诊断用行业映射：`var/calibration/industry-2026-09-18.csv`（覆盖 2,294 只，SHA256: `c22a8595dbd59c708539682346d95185e8e6db8ba79dd4fa2bfb70fec2f50e67`）；
  - 运行校准分析（`--industry-map var/calibration/industry-2026-09-18.csv --diagnostic-only`），产出完整诊断校准包：
    - `var/calibration/2026-09-19-candidate-calibration.json`
    - `var/calibration/2026-09-19-candidate-calibration.md`
  - 编写并固化正式决策材料：
    - `docs/decision-packets/2026-09-20-candidate-qualification-diagnostic-packet.md`
  - 将 `var/calibration/` 纳入 `.gitignore`，防止大型校准运行时产物污染 Git 树。
- **四大核心因子异象深度剖析（产品所有者决策关键输入）**：
  - **成长极值基数异象**：`net_profit_parent_yoy` 极大值达 415,612.12%（超 4,100 倍），因微利基数引起，纯相对分位数无法识别不可持续性，必须由 3 年 CAGR 与营收增速交叉过滤；
  - **红利超额支付异象**：`dividend_payout_ttm` 最大值达 92.82（9282%），存在大额清仓式派息，需在绝对门槛中设置支付率上限（建议 <= 80% 或 100%）；
  - **GARP 策略源端 PEG 量纲异象**：`peg` 中位数高达 166.27，极大值达 407,402.50，上游口径可能为非标准百分比，在确定清洗换算前暂不宜直接套用传统经典门槛（如 <= 1.5）；
  - **价值榜首金融保险高度集中**：Top 5 全部为头部保险央国企（新华保险、中国人寿、中国人保、中国太保、中国平安），低 PE/PB 特征鲜明。
- **全量代码质量与测试验证（任务 8）**：
  - `ruff check .`：通过，0 errors；
  - `ruff format --check .`：通过，全部代码符合格式；
  - `mypy`：通过，116 个源文件类型检查无错误；
  - `make test-fast PYTHONPATH=`：通过，977 passed, 10 warnings；
  - `git diff --check`：通过，无空白异常。
- **安全红线与状态机完整性核验**：
  - `configs/qualifications/` 严格保持不存在（0 个文件），未获所有者审批前绝不伪造任何资格配置文件；
  - 代码库中不存在任何跨策略伪合成评分字段（无 `global_score` / `combined_strategy_score` / `cross_strategy_score`）；
  - `GET /candidates?as_of=2026-09-19` 严格返回 404；调度作业 `BUILD_CANDIDATES` 状态严格保持 `BLOCKED`；
  - 升级包第一阶段准备工作全部闭环，进入项目所有者决策审批门禁（Owner Stop Gate）。

### 33.8 休市日交易日历与行情跳过机制落地（2026-09-20）

- **背景与第一性原理**：
  - 响应项目所有者要求：“把休市日下次给单独列出来，这一天不要去获取股市的数据”。
  - 解决周末或法定节假日执行 `astock daily --sync` 或 `sync-research` 时产生无意义外部行情网络请求与报错的问题。
- **交易日历模块架构（`src/astock_lens/calendar/`）**：
  - 契约接口：`TradingCalendar` 协议定义 `is_trade_date(target: date) -> bool` 与 `get_latest_trade_date(target: date) -> date`；
  - 核心实现：`ChinaTradingCalendar` 内置 2024~2027 年已知法定节假日与调休规则，周末（周六/周日）一律判定为休市；支持传入自定义交易日集合；
  - 零外部网络依赖，单测秒级响应，符合本地优先与确定性原则。
- **底层落地层门禁拦截（`src/astock_lens/data/sync.py::land_raw`）**：
  - 当 `as_of` 为非交易日时，严格跳过向 Provider 发送 `daily_bars` 请求；
  - `DatasetLanding` 明确返回 `DataStatus.NOT_APPLICABLE`，附带 `note="non-trading day (weekend/holiday), skipped market data fetch"`；
  - 保证休市日零外部网络 I/O，且不产生虚假空数据。
- **CLI 命令增强与友好提示（`src/astock_lens/cli/app.py`）**：
  - 新增 `astock calendar is-open --date YYYY-MM-DD`（查询指定日期开市/休市状态）；
  - 新增 `astock calendar latest --date YYYY-MM-DD`（查询指定日期不晚于当天的最近交易日）；
  - `astock sync-research` 在休市日自动检测并友好提示，非财务模式下直接优雅退出，彻底跳过全池价格历史抓取。
- **严格 TDD 验证与回归结果**：
  - 新增 `tests/unit/test_trading_calendar.py`（6 passed）；
  - `tests/unit/test_raw_sync.py` 增加休市日跳过单测（17 passed）；
  - `tests/unit/test_cli.py` 增加 CLI 查询与跳过单测（9 passed）；
  - 全量 `make test-fast`：**986 passed**，`ruff` 与 `mypy` 全部 Clean。

### 33.9 补全研究池 9 只标的二级行业映射与 100% 行业覆盖门禁解除（2026-09-20）

- **背景与根因定位**：
  - 任务 6 审计发现 2,303 只研究池标的中，有 9 只标的缺失申万二级行业映射；
  - 根因调查表明：上游 WeStock CLI 的 `sector ranking --kind industry` 仅列出了按指标排序的 124 个板块，漏掉了申万 2021 二级分类中剩余的 10 个细分板块（如“林业Ⅱ”、“油气开采Ⅱ”、“旅游零售”、“体育Ⅱ”、“医疗美容”等）；此外科创板 CDR 股票（如九号公司 689009.SH）在部分普通股票池中也易被遗漏。
- **权威申万二级分类确认（经过官方资料核对）**：
  - `000592.SZ`（平潭发展）：林业Ⅱ（`sw2_480200`）
  - `000968.SZ`（蓝焰控股）：油气开采Ⅱ（`sw2_210200`）
  - `002679.SZ`（福建金森）：林业Ⅱ（`sw2_480200`）
  - `300896.SZ`（爱美客）：医疗美容（`sw2_730400`）
  - `600158.SH`（中体产业）：体育Ⅱ（`sw2_720400`）
  - `600185.SH`（珠免集团）：房地产开发（`sw2_430100`）
  - `600938.SH`（中国海油）：油气开采Ⅱ（`sw2_210200`）
  - `601888.SH`（中国中免）：旅游零售（`sw2_320200`）
  - `689009.SH`（九号公司）：摩托车及其他（`sw2_280300`）
- **架构实现（零造假、确定性优先、防歧义）**：
  - 建立权威配置文件：`configs/industry_supplement.yaml`，记录每只补充标的的 symbol、行业 ID、行业名称、数据源声明与版本；
  - 在 `src/astock_lens/data/industry.py` 实现 `load_supplemental_industry_memberships`；同时通过 `ASTOCK_INDUSTRY_SUPPLEMENT_PATH` 环境变量支持配置覆盖与测试隔离；
  - 严格保持防歧义门禁：同一标的若被不同板块同时认领且无主行业声明时，立即抛出 `IndustryMembershipAmbiguous` 阻断，杜绝“先到先得”虚假主行业；
  - 在 `src/astock_lens/cli/app.py` 中的 `export-map` 和 `calibrate_candidates` 自动合并补充映射。
- **验证结果与 Blocker 正式解除**：
  - 单测与集成测试：`test_load_supplemental_industry_memberships`、`test_build_industry_map_with_supplemental_records`、`test_industry_export_map_includes_supplements`、`test_calibrate_candidates_canonical_merges_supplement` 全部绿灯通过；
  - 真实环境运行 `astock calibrate candidates --as-of 2026-09-18`（不加 `--industry-map`）：
    - 行业覆盖率：**2,303 / 2,303 (100.0%)**，`missing_symbols` 为空列表；
    - 证据来源：`origin="canonical"`，`mapping_as_of="2026-09-18T15:00:00+08:00"`；
    - `IndustryCoverageUnavailable` 阻断彻底解除，成功生成决策级校准报告；
  - 全量快速回归测试通过：`make test-fast PYTHONPATH=` 达 **990 passed**（新增 4 个用例，0 失败），`ruff` 与 `mypy` 严格通过。

### 33.10 六策略稳健平衡型绝对质量门槛生产落地与日常管线接入（2026-09-20）

- **背景与裁决执行**：
  - 基于项目所有者正式批准的【方案 1：稳健平衡型规则】及决策文件 `docs/decision-packets/2026-09-20-candidate-qualification-diagnostic-packet.md`；
  - 终结 `configs/qualifications/` 长期保持 0 个规则的空白状态，由规范 YAML 配置赋予六大策略显式数字门槛。
- **六策略绝对质量门槛规则生产落地（`configs/qualifications/`）**：
  - `growth.yaml`：`net_profit_parent_yoy >= 15.0%`、`revenue_yoy >= 5.0%`、`net_profit_parent_cagr_3y >= 10.0%`（防范微利暴增异象，强化持续验证）；
  - `momentum.yaml`：`proximity_52w_high >= 0.80`（创一年新高附近，价格强度确认）；
  - `quality.yaml`：`roe_ttm >= 12.0%`、`gross_margin >= 20.0%`、`debt_to_asset <= 65.0%`（优秀盈利、产品护城河与安全负债）；
  - `dividend.yaml`：`0.10 <= dividend_paid_ratio <= 0.80`、`ocf_to_net_profit >= 0.50`（剔除 9282% 等清仓式分红与微利分红，要求经营现金流支撑）；
  - `value.yaml`：`0 < pe_ttm <= 25.0`、`0 < pb <= 2.5`、`roe_ttm >= 5.0%`（兼顾低估值与正向收益底线，防止低价价值陷阱）；
  - `garp.yaml`：`pe_percentile <= 0.60`、`net_profit_parent_cagr_3y >= 15.0%`、`roe_ttm >= 10.0%`（历史估值分位未透支前提下的高质复合增长）。
- **规则引擎与加载器架构（`src/astock_lens/qualifications/`）**：
  - 新增 `FactorThreshold` 与 `FactorThresholdRule`（实现 `AbsoluteQualificationRule` 协议），基于 `StrategyResult.factor_snapshot` 逐项校验因子存在性、`DataStatus.VALUE` 状态与 `[min, max]` 区间，生成明确原因与风险；
  - 新增 `load_qualification_rule` 与 `load_canonical_qualifiers`（支持 `ASTOCK_QUALIFICATION_DIR` 环境变量路径隔离与测试覆盖）；
  - 严格保持契约：若任一启用策略缺少规则配置文件，抛出 `QualificationRuleNotConfigured` 强拦截。
- **日常管线调度接入与状态机核验**：
  - 在 `src/astock_lens/cli/app.py::_run_daily` 中将 `qualifiers=load_canonical_qualifiers()` 注入 `run_daily`；
  - 运行 `astock daily --as-of 2026-09-18` 实测验证：
    - `BUILD_CANDIDATES` 阶段成功装配资格规则，`"strategy qualification rules are not configured: absolute quality thresholds have not been approved"` 阻断原因完全消除；
    - 阶段依法依规保持受限于上游未实施的 Regime / Validation / Signal 模块与 Candidate Selection Policy，继续输出 `5 blocked, 0 failed`，符合设计预期；
  - 全量快速回归测试通过：`make test-fast PYTHONPATH=` 达 **996 passed**（新增 6 个测试用例，0 失败），`ruff` 与 `mypy` 静态检查完全 Clean。

### 33.11 锁定六策略资格规则契约测试：生产规则漂移 RED 证据（2026-09-20）

- **任务**：Qualification Correctness Hardening 实施计划 Task 1（Step 1–6）。
- **新增契约测试**：`tests/contract/test_qualification_production_rules.py`。把所有者于 2026-09-20 批准的六策略绝对资格规则逐字写死为 `EXPECTED`，并对生产 YAML 做硬契约断言；在 Task 4 修复生产 YAML 之前保持 RED。
- **运行命令与结果**（`PYTHONPATH= .venv/bin/python -m pytest tests/contract/test_qualification_production_rules.py -v`）：

  ```text
  5 failed, 3 passed in 0.19s
  ```

  逐用例：

  ```text
  test_production_rule_matches_owner_approval[value]    FAILED
  test_production_rule_matches_owner_approval[growth]   FAILED
  test_production_rule_matches_owner_approval[garp]     FAILED
  test_production_rule_matches_owner_approval[quality]  PASSED
  test_production_rule_matches_owner_approval[dividend] FAILED
  test_production_rule_matches_owner_approval[momentum] PASSED
  test_dividend_rule_uses_approved_metrics_not_percent_ratio_substitute FAILED
  test_momentum_liquidity_is_an_upstream_universe_gate  PASSED
  ```

- **真实失配清单（契约测试实际输出）**：
  - **value**：生产 YAML 私自追加了未经审批的正数下限。
    - 现状：`pe_ttm {min: 0.0001, max: 25.0}`、`pb {min: 0.0001, max: 2.5}`、`roe_ttm {min: 5.0}`；
    - 批准：`pe_ttm {max: 25.0}`、`pb {max: 2.5}`、`roe_ttm {min: 5.0}`；
    - 差异：`pe_ttm`、`pb` 多出 `min: 0.0001`。非正 PE/PB 已由 Factor 层判定 `NOT_APPLICABLE`，资格层不得重复发明"正数"语义。
  - **growth**：`roe_ttm >= 8%` 被未经审批替换为 `net_profit_parent_cagr_3y >= 10%`。
    - 现状：`net_profit_parent_yoy {min: 15.0}`、`revenue_yoy {min: 5.0}`、`net_profit_parent_cagr_3y {min: 10.0}`；
    - 批准：`net_profit_parent_yoy {min: 15.0}`、`revenue_yoy {min: 5.0}`、`roe_ttm {min: 8.0}`。
  - **garp**：指标替换 + 单位错误。
    - 现状：`pe_percentile {max: 0.6}`、`net_profit_parent_cagr_3y {min: 15.0}`、`roe_ttm {min: 10.0}`；
    - 批准：`pe_ttm {max: 35.0}`、`net_profit_parent_yoy {min: 15.0}`、`roe_ttm {min: 10.0}`；
    - `pe_percentile` 原始单位为 `%`，`0.60` 实为 `0.60%` 而非 `60%`。
  - **dividend**：指标替换 + 单位错误（专项用例 `KeyError: 'dividend_yield_ttm'`）。
    - 现状：`dividend_paid_ratio {min: 0.10, max: 0.80}`、`ocf_to_net_profit {min: 0.50}`；缺 `dividend_yield_ttm`；
    - 批准：`dividend_yield_ttm {min: 3.0}`、`dividend_payout_ttm {min: 0.10, max: 0.80}`；
    - `dividend_paid_ratio` 单位是 `%`，真实值可为 `27.13` / `79.00`，`0.10~0.80` 实际退化为 `0.10%~0.80%`。
  - **quality**：与批准一致（`roe_ttm>=12`、`gross_margin>=20`、`debt_to_asset<=65`），PASSED。
  - **momentum**：与批准一致（仅 `proximity_52w_high {min: 0.80}`），PASSED；流动性由 canonical Universe `min_average_turnover_20d = 150,000,000` 承担，专项用例 PASSED。
- **结论**：生产资格规则存在 4 个策略的审批漂移（value/growth/garp/dividend），其中 2 个同时含单位错误（garp/dividend）。本契约测试即为后续 Task 4 必须达成的目标，RED 证据已留存。

### 33.12 六策略资格规则全研究池修复审计完成（2026-09-20）

- **范围**：Qualification Correctness Hardening 实施计划 Task 1–7。生产资格规则与所有者批准口径逐字一致；资格判定改为读取该股票完整 Factor 证据；非法配置失败关闭；并在正式全研究池基线上完成只读审计。
- **关键提交**：`0686d31`（契约测试）、`540ec0b`（QualificationContext）、`de3f18b`（严格 fail-closed 配置）、`3b28a6e`（恢复六份生产 YAML）、`674baef`（堵住空值/未知阈值键绕过）、`5182673`（管线接入完整因子证据）、`ba0430d`（只读资格影响审计 CLI）。
- **审计基线（读实际存储）**：Research Universe 2,303；FACTOR 快照 **120,192 = 5,008 × 24（全市场口径）**；STRATEGY 快照 **13,818 = 2,303 × 6**；无 CANDIDATE 快照。
- **六策略分布**（`astock calibrate qualification-impact --as-of 2026-09-19`）：value 158/320/132、growth 231/445/151、garp 85/196/61、quality 170/324/111、momentum 229/303/166、**dividend top10=162 但 absolute-pass=0、dual-pass=0**（dual÷ranked 0.0000）。
- **安全复核（触发 `dual_pass_count == 0`）**：`dividend` 全灭系**上游股息率数据缺口**，非阈值/单位缺陷：
  - FACTOR 快照 `dividend_yield_ttm`：`VALUE=0`、`NULL=2241`、`NOT_APPLICABLE=2767`，`unit=%`；
  - 上游 `data/raw/neodata/valuation/2026-09-19.csv`（2241 只）的「静态股息率（%）」「滚动股息率（%）」两列，**24,619 个单元格非空值为 0**（全 `--`）；
  - 对照 `dividend_payout_ttm` 有 `VALUE=1622`（其中 1309 在 `[0.10,0.80]`）。
  - 抽样 22 只边界样本：`dividend_yield_ttm` 全部 `NULL`；`dividend_payout_ttm` 18/22 达标。
  - **裁定：规则正确、数据缺失。严禁改已批准阈值**；已作为上游阻塞记入 `docs/REMAINING_PRODUCT_BLOCKERS.md`，需所有者决定补数据源或重新审批 Dividend 门槛。
- **三策略直接验证**：Growth 合格样本 5 只全部满足 `npyoy>=15 / revenue_yoy>=5 / roe_ttm>=8`（`roe_ttm` 不在评分快照内）；GARP 合格样本全部满足 `pe_ttm<=35 / npyoy>=15 / roe_ttm>=10`，阈值键不含 `pe_percentile`；Dividend 合格样本为空（见上）。
- **无 Candidate 发布证明**：审计命令只读（执行前后 Snapshot/Watchlist/Job 指纹逐字节相等）；`data/snapshots/CANDIDATE/` 不存在；`astock daily` 仍在 `BUILD_CANDIDATES` 阻断（`5 blocked, 0 failed`, `candidates: 0`）。
- **不改产出的独立佐证**：修复后重跑 `astock daily --as-of 2026-09-19` 未产生快照冲突，`FACTOR/UNIVERSE/STRATEGY` 的 `2026-09-19.json` mtime 仍为 `09:49:45/46/58` → 重跑产出与正式快照逐字节一致，即本次修复未改变 FACTOR/STRATEGY 产出。
- **完整审计文档**：`docs/decision-packets/2026-09-20-qualification-repair-audit.md`。产物：`var/calibration/qualification-repair/qualification-impact-2026-09-19.{json,md}`。

## 三十四、资格审计硬化（M1/M2/m1/m5）与实施计划台账偏差（2026-09-20）

### 34.1 硬化项（QA 两段式评审遗留 Major/Minor）

- **M1（去无检查 cast，失败响亮可诊断）**：`src/astock_lens/calibration/qualification_impact.py` 删除 `_ThresholdBearingQualifier` / `_AbsoluteThresholds` 两个结构性 Protocol 与 `cast` 导入，改为 `_absolute_thresholds()` 显式运行时校验 `getattr(qualifier, "absolute_rule", None).thresholds` 是否为 `Mapping`，否则抛新增的具名异常 `QualificationImpactUnsupportedQualifier`（消息点名 `strategy_id` 与 qualifier 类型）。旧行为：只满足公开 `StrategyQualifier` 协议的 qualifier 会抛裸 `AttributeError`；新行为：可诊断异常，且绝不把"读不到阈值"降级为"边界样本为空"。
- **M2（不静默丢弃 risk）**：失败原因聚合键改为"能抠出因子名用因子名，抠不出用 risk 原文"，任何 risk 都不得被省略（`AGENTS.md` 禁止静默兜底）。排序规则不变（count 降序、同 count 键名升序）。
- **m1（根级未知键拒绝）**：`src/astock_lens/qualifications/rules.py::load_qualification_rule` 把根级允许键收紧为 `{strategy_id, version, description, thresholds}`，出现其他键 → `QualificationConfigInvalid`（可抓 `descripton:` 拼写错误）。六份生产 YAML 只含这四键，仍严格加载通过。
- **m5（测试替身签名过期）**：`tests/integration/test_candidate_qualification_pipeline.py` 的 `_DummyPassRule` / `_DummyFailRule`.`evaluate` 由旧签名 `(result: StrategyResult)` 改为契约新签名 `(context: QualificationContext)`（原断言未改弱）。
- **回归门禁**：审计产物与已提交产物**逐字节一致**（`diff` MD/JSON 均无差异，M2 未改变聚合口径）；聚焦 4 文件 31 passed；`mypy` 0 errors；`ruff check`/`format --check` 全过。

### 34.2 实施计划台账偏差（如实记录，非缺陷）

- 计划 **Task 5** 的 Modify 清单列了 `tests/unit/test_candidate_routing.py`，但该文件在 `44e3e15..HEAD` **零改动**——它不依赖本轮变更的签名（`evaluate(context)`），实际无需修改（属台账未同步，非缺陷）。
- `tests/integration/test_candidate_qualification_pipeline.py` 同理只到本轮 **m5** 才补齐测试替身签名；此前其 `_DummyPassRule`/`_DummyFailRule` 的旧签名因未被触发而未被发现。
- 多出一次**未映射到 Task 编号**的修复提交 **`674baef`**（«修复：堵住资格配置空值与未知阈值键的失败关闭绕过»，堵住 `str(None)` 强转与未知阈值键的 fail-closed 绕过），属 Task 3/Task 4 的补丁。
