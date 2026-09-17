# A-Stock Lens

本地优先、单用户、面向全 A 股的多策略选股与研究生命周期系统。

它不把选股当成一次性条件过滤，而是管理完整研究过程：

`全市场发现 → 策略解释 → 市场验证 → 交易状态 → 观察池 → 深度研究 → 持续跟踪`

## Candidate ≠ Recommendation

系统输出 Candidate、Research Priority 与 Signal State，不输出"强烈买入"这类结论。Candidate 是一个**研究对象**，不是推荐；`next_action` 只允许 `IGNORE`、`WATCH`、`DEEP_RESEARCH`、`TRACK_SIGNAL`。

## 与 a-share-deep-research 的关系

两个仓库保持独立。A-Stock Lens 负责全市场发现与生命周期管理；证据密集的公司深度研究由现有 `a-share-deep-research` 承担。

集成方式是标准 `ResearchRequest` + `DeepResearchAdapter` 松耦合：V1 提供 CLI Adapter，未来可替换为 HTTP Adapter。A-Stock Lens 只保存 `ResearchSummary` 与产物引用，不复制深研报告与证据库，也不把对方作为 Python 依赖导入。

## 架构链路

严格单向的依赖方向：

```text
External Provider → Raw → Normalized → Data Quality Gate → Universe
  → Factor → Strategy → Market Regime/Router → Market Validation
  → Signal → Candidate → Watchlist / Research → API / Web / CLI
```

关键约束：

- Strategy 不得直接调用 AkShare；
- API / Web 不得重新计算因子；
- Research 模块不得复制深研项目业务；
- Provider 内部不得写入策略判断。

## V1 范围与非目标

V1 做：全 A 股 Universe、每日增量同步、约 40–60 个核心 Factor、7 个独立 Scanner（Value / Growth / GARP / Quality / Dividend / Momentum / Industry Trend）、Market Regime、Market Validation、Signal、Candidate 快照、Watchlist 状态机、深研适配器、6 个前端页面。

V1 不做：自动下单、券商交易 API、分钟级实时扫描、机器学习选股、LLM 直接决定买卖、复杂 Portfolio Optimizer、完整历史回测平台、期货/期权、港股/美股、多用户与权限、云端 SaaS 部署。

详见 `docs/PRODUCT.md`。

## 当前状态

项目处于**每日 Pipeline 切片已贯通**：`CSV → Raw → Normalized → Quality Gate → Factor → Universe → Strategy（横截面评分排名）→ Candidate → 四类快照`，加上 Watchlist 状态机、Job Manifest 与 CLI 生命周期命令，可以端到端跑通，且不需要网络、不需要可选依赖。

| 已具备 | 尚未实现 |
| --- | --- |
| 设计三件套（spec / PRODUCT / ARCHITECTURE） | Market Regime、Market Validation、Signal 检测器（阈值 `Deferred`） |
| 类型化配置加载；阈值/因子/权重全部写在 YAML | Watchlist 状态机、深研 Adapter 实现、React 前端 |
| Watchlist 状态机（`DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL`）+ Timeline + CLI/API | 深研 Adapter 需要外部命令，默认未配置时明确报错 |
| 领域枚举、时间模型、扩展契约 Protocol | `confidence` 算法（设计未定义，保持 `null`） |
| 本地 CSV Provider、Normalizer、Data Quality Gate | 权重正式评审（当前是等权草案 `PENDING REVIEW`） |
| Universe 引擎与不可变 `UniverseSnapshot`（含 deferred rule 上报） | 停牌天数数据源（设置 `long_suspension_days` 阈值的前置依赖） |
| 动量因子（`ret_20d` / `ret_60d` / `proximity_52w_high`）+ 流动性因子 | Parquet 行情存储 |
| 横截面评分与排名（percentile 加权混合）、`next_action` 路由（D5：仅按排序） | |
| `DuckDBSnapshotStore` / `DuckDBWatchlistStore` 与 JSON store 同协议互换（`ASTOCK_SNAPSHOT_BACKEND` / `ASTOCK_WATCHLIST_BACKEND`） | |
| AkShare Provider（腾讯域日线 + 三交易所名单）+ 真实录制契约 fixture | |
| WeStock CLI Provider（三大表，含 `EndDate` + `InfoPublDate`，批量 100 只 / 11 秒）+ 录制 fixture | 财报的 Normalized / Quality Gate / 基本面因子（下一片） |
| 财务 Normalized（48 个指标）+ Financial Quality Gate + 观测进入因子上下文 | 基本面因子本身（下一片）、全市场财报同步的限流验证 |
| 12 个基本面因子（5 个比值 + 7 个指标透传），带时点选择、证据引用与单位 | 估值类因子（需要市值/股本口径评审）、行业适用的豁免规则 |
| Growth / Quality / Dividend 三个 Scanner 的**资格判定**（打分待权重评审） | Value / GARP（缺估值口径）、Industry Trend（缺行业数据） |
| 全市场财报同步已验证（5,576 只 × 三大表，37 分钟，缺口 4–6 只且有名有姓） | AkShare 全市场日线（5564 只 × 全history，尚未跑过） |
| 评分机器（`WeightedPercentileScanner`，支持极性）+ 权重评审工具（真实全市场数据） | **权重本身仍是 `PENDING REVIEW`**——等你定数字 |
| Job Run 记录与 Manifest（每阶段独立可重跑）、`astock daily`；CLI `sync` / `stock` / `watch` / `research` / `strategy run`；API `/health` `/universe` `/factors` `/candidates` `/watchlist` | |
| 独立 Artifact Validator（快照 + Job Manifest，不导入生产代码） | |

包结构已按 `docs/ARCHITECTURE.md` 建立，`src/astock_lens/` 下的 `backtest`、`portfolio`、`events` 等目录只是预留边界，没有 V1 实现。

### 本切片刻意留空的部分

- **权重仍是等权草案。** `configs/strategies/momentum.yaml` 的 `weights:` 已生效（三条动量因子各 1.0），但标注 `PENDING REVIEW`——正式评审前它只是占位，不是结论。
- **`confidence` 恒为 `null`。** 设计要求该字段但未定义算法；资格判定已要求全部因子在场，"因子齐备比例"会恒等于 1.0，那是一个看起来有用实则无信息的数。
- **停牌天数诚实缺失。** 交易所名单不提供停牌天数，`suspended_trading_days` 允许 `None`（缺失 ≠ 0）。给 `long_suspension_days` 设阈值前，必须先有提供停牌天数的数据源。
- **快照后端可选。** 默认 JSON（零依赖），`ASTOCK_SNAPSHOT_BACKEND=duckdb` 切到 DuckDB，两者同协议。
- **窗口不完整即 `NULL`。** 60 日窗口内少一天，`ret_60d` 输出 `NULL`，不用更短的窗口凑数。
- **四个阶段显式 `BLOCKED`。** Market Regime、Market Validation、Signal 的词表已确认但阈值是 `Deferred`，`UPDATE_WATCHLIST` 也没有确认的自动变更规则；`astock daily` 把它们记为 `BLOCKED` 并写明原因，`MARKET_REGIME` 快照因此没有生产者（缺失被显式列出，而不是写占位值）。
- **深研 Adapter 默认不接。** `ASTOCK_DEEP_RESEARCH_CMD` 未配置时 `astock research` 直接报错——没有可提交的对象时不会伪造 job。
- **Watchlist 只走确认路径。** 后退、跳步与预留状态都会被拒绝并指出涉及的状态；设计没有定义这些转移，接受它们等于替产品做决定。
- **血缘版本可并列。** 同一只标的可能被多个 Scanner 打分，`SnapshotLineage` 的版本字段因此是逗号分隔的集合，判定"这条结果是否被该血缘覆盖"用成员关系；详见 `docs/REVIEW_NOTES.md`。

## 环境要求与安装

需要 Python >= 3.12 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync                                   # 默认轻量环境（CLI / API / 配置）
uv sync --extra data --extra providers    # 需要 DuckDB / PyArrow / Polars / AkShare 时
```

DuckDB、PyArrow、Polars 与 AkShare 是可选依赖，因此 bootstrap 阶段的测试不需要安装大数据栈。

## 快速检查

```bash
uv run astock --help
uv run astock doctor
```

`doctor` 只读本地文件：检查 Python 版本、加载 `configs/app.yaml`、报告配置中的存储路径是否存在，并按 `docs/DATA_SOURCES.md` §4 报告 Data Health——每个已落地 dataset 的行数与交易日区间、Provider 可用性。它不会抓取行情、不会连接外部数据源、也不会创建 DuckDB 文件。

### 跑一遍每日扫描

数据源指向本地 CSV 目录（默认 `data/raw`），快照写入目录（默认 `data/snapshots`），两者都可用环境变量覆盖：

```bash
export ASTOCK_CSV_ROOT=tests/fixtures/csv
export ASTOCK_SNAPSHOT_ROOT=tests/.tmp/demo
export ASTOCK_DATASET=daily_bars_long            # 长 fixture：300 个交易日

uv run astock universe build --as-of 2026-09-04  # 每条规则的判定结果 + UNIVERSE 快照
uv run astock scan --as-of 2026-09-04            # 排名、评分、next_action、四类快照
uv run astock factors compute --as-of 2026-09-04 # 每个因子一行 JSON，走 stdout
uv run astock strategy run momentum --as-of 2026-09-04   # 单个 scanner 的排名
uv run astock daily --as-of 2026-09-04 --allow-incomplete # 11 个阶段逐个 Job Run

uv run uvicorn --factory astock_lens.api.app:create_app
curl "http://127.0.0.1:8000/universe?as_of=2026-09-04"
curl "http://127.0.0.1:8000/candidates?as_of=2026-09-04"
curl "http://127.0.0.1:8000/watchlist"
```

`--as-of` 接受交易日 `YYYY-MM-DD`，按当日 A 股收盘（15:00 +08:00）解析。

### 生命周期命令

```bash
export ASTOCK_WATCHLIST_ROOT=tests/.tmp/watchlist
export ASTOCK_JOB_ROOT=tests/.tmp/jobs

uv run astock stock 300750.SZ --as-of 2026-09-04   # Stock Profile：Universe 判定、因子、策略、Candidate、血缘
uv run astock watch 300750.SZ --thesis "结构性增长"  # 新建条目，起始状态 DISCOVERED
uv run astock watch 300750.SZ --state WATCH         # 只接受设计确认的路径，其余按名字拒绝
uv run astock watch                                 # 列出已跟踪标的
uv run astock research 300750.SZ                    # 需要 ASTOCK_DEEP_RESEARCH_CMD，未配置则报错
```

`astock daily` 会为设计的 11 个阶段各写一条 Job Run 到 `ASTOCK_JOB_ROOT/<date>.json`。目前 6 个阶段可跑，`DETECT_REGIME`、`MARKET_VALIDATE`、`RUN_SIGNALS`、`UPDATE_WATCHLIST` 记录为 `BLOCKED` 并写明等待的决策，因此该命令在补齐前退出码为 1；需要允许不完整时显式加 `--allow-incomplete`。

`astock sync` 需要 `providers` extra（`uv sync --extra providers`）：它把 AkShare 的名单与日线落到 `ASTOCK_CSV_ROOT`，已经带有目标日期的标的不会重复抓取（`spec §15` 的增量要求）。

接真实数据时用 `astock sync`（AkShare，落地到 `ASTOCK_CSV_ROOT`）或把该变量指向已有落地目录；fixture 录制脚本见 `scripts/record_akshare_fixture.py`。`factors compute` 的 JSON 走 stdout、运行说明走 stderr，因此可以直接管道给别的工具。

环境变量汇总：`ASTOCK_CSV_ROOT`、`ASTOCK_SNAPSHOT_ROOT`、`ASTOCK_DATASET`、`ASTOCK_SECURITIES_DATASET`、`ASTOCK_FACTOR_CONFIG_DIR`、`ASTOCK_UNIVERSE_CONFIG`、`ASTOCK_STRATEGY_CONFIG_DIR`、`ASTOCK_SNAPSHOT_BACKEND`、`ASTOCK_WATCHLIST_ROOT`、`ASTOCK_WATCHLIST_BACKEND`、`ASTOCK_JOB_ROOT`、`ASTOCK_DEEP_RESEARCH_CMD`、`ASTOCK_WESTOCK_BIN`。

### 财务数据源（2026-09-16 设计补遗 §24）

财务三大表的 bulk 源是腾讯 WeStock CLI，因为它同时给出可靠的 `EndDate`（报告期）与 `InfoPublDate`（公告日期），且支持批量。二进制不随仓库分发：

```bash
export ASTOCK_WESTOCK_BIN=/path/to/westock
uv run astock doctor                 # 报告 provider westock-cli [ok] / [unavailable]
uv run python scripts/record_westock_fixture.py   # 需要时重录契约 fixture
```

`neodata`（自然语言语义检索）留在研究侧，只经 `ResearchRequest` / `DeepResearchAdapter` 使用：它逐标的、输出渲染后的 Markdown、凭证 12 小时有效且只能由 WorkBuddy 平台刷新，不适合做批量因子源。

### 全市场财报刷新（季度任务）

```bash
export ASTOCK_WESTOCK_BIN=/path/to/westock
uv run astock sync --as-of 2026-09-16 --statements-only   # 只拉三大表，不碰日线
```

实测（2026-09-16，5,576 只标的 × 三大表，100 只/批，共 168 次调用）：

| 数据集 | 结果 | 行数 | 源站未返回 |
| --- | --- | --- | --- |
| `financial_balance` | VALUE | 44,430 | 4 只 |
| `financial_cashflow` | VALUE | 44,450 | 6 只 |
| `financial_income` | VALUE | 44,464 | 4 只 |

耗时 **37 分钟**（含一次针对缺口的补抓），缺口标的是 `000003.SZ`、`000005.SZ`、`830799.BJ`、`900948.SH` 这类退市/B 股/新三板标的——它们不是"抓失败"，而是源站确实没有当期报表，并且被逐一点名而不是从统计里消失。

随后归一化：**2,133,636 条观测 / 5,565 只标的 / 48 个指标，92 秒，峰值内存约 2.9 GB，0 个阻断问题**（NULL 类问题 97,876 个，多为银行没有毛利率这类真实缺失）。

规模上的两点事实：内存 ~2.9 GB 来自一次性物化 213 万个观测对象，是当前最大开销；全市场抓取 + 归一化合计约 40 分钟，因此它是季度任务，不是每日任务的一部分。

### 落财务数据

```bash
export ASTOCK_WESTOCK_BIN=/path/to/westock
uv run astock sync --as-of 2026-09-04 --financials            # 名单 + 日线 + 三大表
uv run astock sync --as-of 2026-09-04 --financials --symbol 600519.SH --symbol 000001.SZ
```

落地的是 CLI 的逐字表格（`code` / `EndDate` / `InfoPublDate` + 各科目列）。合并键：名单按 `symbol`、日线按 `(symbol, trade_date)`、财报按 `(code, EndDate)`，所以重复同步只替换、不追加。

管线随后把三大表归一化为 `FinancialObservation` 并过质量门：实测 3 只股票 → **1152 条观测 / 48 个指标**，每条都带 `report_period`、`announce_date`、`available_at`（= 公告日 A 股收盘，保守取值），且 `available_at <= as_of`。

缺失的处理是三种不同的事实，不会互相冒充：源里没有值（`-`）→ `NULL` 观测；值读不出来 → 失败记录 + `INVALID`；某张表**根本没落地** → `absent_datasets` 里点名，而不是当成"空表"。

### 基本面因子

```bash
uv run astock factors compute --as-of 2026-09-04 | grep ocf_to_net_profit
```

已实现 5 个比值因子（分子分母都是源站已发布的 TTM 或时点字段，代码里不拼年度）：现金流覆盖、有息负债/权益、商誉/权益、分红支付率、营收/存货。

时点规则是硬的：因子只用 `available_at <= as_of` 的最新一期，公告在 `as_of` 之后的报告对它**不可见**（有测试专门钉住"最好看的那一期恰好还没公告"）。每个结果都带 `inputs`，写明用了哪个指标、哪一期、哪天公告、原值多少，所以 `StrategyResult → FactorSnapshot → Normalized Data → Provider` 这条解释链能一步步走回去。

缺失用同一套 6 态词表，优先级显式：`NOT_APPLICABLE`（该标的报表没有这一行）> `NULL`（有行无值）> `STALE`（超过已评审的新鲜度上限）。`stale_after_days` 在配置里显式写 `null` = 未评审，机制就绪但不触发。

实测（3 只股票，55 个基本面因子结果）：`VALUE 13 / NULL 2 / NOT_APPLICABLE 40`——那 40 个是没落地财报的 8 只标的，报"不适用"，不是 0。

一个已知的解读边界：银行的经营现金流包含存款变动，`ocf_to_net_profit` 对金融企业不具"利润含金量"的含义（实测 000001.SZ = 8.20）。因子本身是客观数字，是否按行业豁免属于策略层决定，设计尚未确认，因此这里只记录不改写。

### 策略 Scanner 的当前状态

```bash
uv run astock strategy run quality --as-of 2026-09-04
```

| Scanner | 状态 |
| --- | --- |
| `momentum` | 有排名与分数（权重是等权草案，标注 `PENDING REVIEW`） |
| `growth` / `quality` / `dividend` | **只给资格判定，不给分数**：设计把权重与评分阈值列为 `Deferred`（`docs/STRATEGY_SYSTEM.md` §5），打分会是没人评审过的判断 |
| `value` / `garp` | 未实现：需要估值类因子（PE/PB/PS、FCF yield、历史估值分位、行业相对估值），而它们需要先评审股本/市值口径 |
| `industry_trend` | 未实现：需要行业数据（板块成分、行业汇总），目前没有落地 |

资格判定的含义是"证据是否完整到足以让这个 Scanner 考虑它"，可证伪且有用。实测（3 只有财报 + 8 只没有）：

```
quality : 300750.SZ 合格、600519.SH 合格、000001.SZ 不合格（银行报表没有毛利率这一行）
growth  : 000001.SZ 合格、300750.SZ 合格、600519.SH 合格
dividend: 000001.SZ 合格、300750.SZ 合格、600519.SH 合格
其余 8 只（未落地财报）：三个 Scanner 全部不合格，理由写明缺哪个因子
```

银行在 Growth/Dividend 上合格、在 Quality 上不合格——这正是 6 态缺失词表要表达的区别：不是"数据坏了"，而是"这张报表没有这一行"。

### 权重评审（待你拍板）

评分机器已经就绪：一旦 `configs/strategies/<id>.yaml` 里写上 `weights:`，`WeightedPercentileScanner` 立刻开始打分，无需改代码；没写权重就仍只做资格判定。评审工具用真实全市场数据把候选方案的后果摊开：

```bash
uv run python scripts/review_strategy_weights.py --root /path/to/raw --as-of 2026-09-16
```

权重的符号表达极性：正数表示"越大越好"，负数表示"越小越好"（例如 `debt_to_asset: -1.0`）。`weights` 必须**恰好覆盖** `required_factors`，权重为 0 会被拒绝——一个 0 权重意味着这个因子本不该出现在要求里。

实测（5,565 只，2026-09-16 数据）：

| 策略 | 候选方案 | top-12 与等权重重合 | 观察 |
| --- | --- | --- | --- |
| Quality | 等权 vs 收益+现金流优先 | **3/12（25%）** | 权重真的改变你看到谁 |
| Quality | 等权 vs 资产负债表优先 | 6/12（50%） | 是否把杠杆当一票否决，差别很大 |
| Growth | 等权 vs 3 年持续性优先 | 7/8（88%） | 权重几乎无效 |
| Growth | 等权 vs 最新一期优先 | 7/8（88%） | 同上 |
| Dividend | 等权 vs 现金流覆盖优先 | 7/8（88%） | 同上 |

评审同时暴露了两个**因子设计问题**（权重调不动它们，需要你定口径）：

1. **比值在分母塌缩时不可用**。`dividend_payout_ttm` 与 `ocf_to_net_profit` 的分母是 TTM 归母净利润，当它接近 0 时比值爆炸——实测榜首是 `603439.SH` 的支付率 **6407%**、现金流覆盖 **691 倍**，而百分位排名恰好专挑这类公司，与"可持续分红"相反。源站自己发布的年报支付率是正常的（茅台 79.00%、平安银行 27.13%、603439 51.84%），因此可选口径包括：改用源站 `DividendPaidRatio`、或给分母设一个下限（阈值需你确认）、或保留现状并接受噪声。
2. **Growth 被极端值主导**。榜首的 `revenue_yoy` 高达 1819%、`net_profit_parent_yoy` 达 71528%，而百分位排名让 3000% 与 70000% 的差距被压缩成一个名次——所以换权重也改变不了榜单（88% 重合）。这属于"是否需要稳健化处理"的评审决定。

在你确认之前，三个 Scanner 仍然只给资格判定，不产生任何分数。

## 测试与质量检查

```bash
uv run pytest --cov=astock_lens --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

等价的 Makefile 目标：`make test`、`make lint`、`make typecheck`。

## 下一步

1. **AkShare 全市场落地**：`securities` 名单（5564 只）与全市场日线的批量抓取、限流与断点续跑（`astock sync` 的机制已就绪，缺的是全量运行的验证）。
2. **全市场财报同步**：100 只/批 ≈ 11 秒/表，三大表全市场约 30 分钟，属季度任务；限流与断点续跑尚未验证。
3. **策略权重正式评审**：把等权草案换成评审后的权重，并给 Growth / Quality / Dividend 定评分口径（现在是资格判定）。
4. **估值口径评审**：定了股本/市值口径，Value 与 GARP 才能落地。
5. **Market Regime / Market Validation / Signal 检测器**：需要先确认各输入的阈值，否则只能继续保持 `BLOCKED`。
6. **其余 6 个 Scanner**：依赖基本面因子落地。
7. **React 前端 6 个页面**：目前只有 `web/README.md`。

每条切片的计划都放在 `docs/superpowers/plans/`，设计权威仍是 `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`。

## 文档索引

- `docs/PRODUCT.md`：产品说明与 V1 范围
- `docs/ARCHITECTURE.md`：技术架构与模块边界
- `docs/DATA_MODEL.md`：时间模型、快照血缘、缺失状态与生命周期
- `docs/STRATEGY_SYSTEM.md`：7 个 Scanner 与共同契约
- `docs/DATA_SOURCES.md`：批量数据源与深研集成边界
- `docs/DEVELOPMENT.md`：开发环境与工作流
- `docs/TESTING.md`：测试体系
- `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`：完整设计规格
- `docs/REVIEW_NOTES.md`：本次一致性实现中做出的判断与偏离记录
- `web/README.md`：前端页面规划

权威顺序：设计 spec → `docs/PRODUCT.md` → `docs/ARCHITECTURE.md` → `README.md`。
