# A-Stock Lens 技术架构（V1）

## 1. 架构风格

V1 采用：

> **模块化单体 + Pipeline 执行 + Plugin/Adapter 扩展 + 本地优先存储**

选择原因：

- 单用户本地运行，不需要微服务复杂度；
- 全市场每日扫描天然适合 Pipeline；
- Provider / Factor / Strategy / Research 需要稳定扩展点；
- 后续可在不改领域核心的情况下接入商业数据源、回测或 HTTP 研究服务。

## 2. 依赖方向

严格保持单向依赖：

```text
External Provider
      ↓
Raw Data
      ↓
Normalizer
      ↓
Data Quality Gate
      ↓
Normalized Data
      ↓
Universe
      ↓
Factor Engine
      ↓
Strategy Engine
      ↓
Market Regime / Router
      ↓
Market Validation
      ↓
Signal Engine
      ↓
Candidate Builder
      ↓
Watchlist / Research
      ↓
API / Web / CLI
```

禁止：

- Strategy 直接调用 AkShare；
- Web 重新计算 ROE/PE；
- Research 模块复制深度研究项目业务；
- Provider 内部写策略判断。

## 3. 项目目录

```text
a-stock-lens/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── Makefile
├── docs/
│   ├── PRODUCT.md
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   ├── STRATEGY_SYSTEM.md
│   ├── DATA_SOURCES.md
│   ├── DEVELOPMENT.md
│   ├── TESTING.md
│   └── superpowers/specs/
├── configs/
│   ├── app.yaml
│   ├── universe.yaml
│   ├── providers.yaml
│   ├── market_regime.yaml
│   ├── factors/
│   └── strategies/
├── src/astock_lens/
│   ├── domain/
│   ├── data/
│   ├── universe/
│   ├── factors/
│   ├── strategies/
│   ├── market/
│   ├── signals/
│   ├── candidates/
│   ├── watchlist/
│   ├── research/
│   ├── pipelines/
│   ├── jobs/
│   ├── api/
│   └── cli/
├── web/
├── data/
│   ├── raw/
│   ├── normalized/
│   ├── factors/
│   └── snapshots/
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── fixtures/
│   └── artifacts/
└── var/
    ├── logs/
    └── astock.duckdb
```

## 4. 数据层

### 4.1 Provider Layer

全市场扫描与深度研究分层：

```text
Bulk / Screening                Research Enhancement
----------------                --------------------
AkShare（名单、日线）             a-share-deep-research
腾讯 WeStock CLI（三大表）         ├─ westock-npm
neodata（估值 / 行业 / 语义）      └─ westock-cli
交易所公开数据
免费备用源
```

V1 中 A-Stock Lens 不复制现有深研 Provider 代码，而通过 Research Adapter 使用它。

> 2026-09-16 补遗（设计规格 §24）：财务三大表改用腾讯 WeStock CLI 作为 bulk 源，
> 因为它同时给出可靠的 `EndDate` + `InfoPublDate`，并支持批量（100 只 / 11 秒，实测）。
> 调用方式是外部命令；A-Stock Lens 不导入深研项目的 Python 模块与内部状态。
>
> 2026-09-17 修订（设计规格 §24.1）：`neodata` **已升为一等 Provider**，不再是研究侧
> 专属。它是估值、行业/板块与语义三类主数据的来源，并作为财报的交叉验证源；不做标的
> 枚举（名单仍由 AkShare 提供），查询措辞固化成 Provider 内模板。全市场估值走"按板块
> 迭代"的批量路径，而不是 5,500 次单标的查询。

### 4.2 Raw Layer

Raw 数据尽量保留数据源原貌，并保存抓取元信息：

- provider；
- dataset；
- fetched_at；
- trade_date / report_period；
- provider_version；
- status；
- row_count。

### 4.3 Normalized Layer

系统定义 Canonical Schema。

示例 `DailyBar`：

- symbol
- trade_date
- open/high/low/close/pre_close
- volume/amount
- turnover_rate
- pct_change
- adj_factor

示例 `FinancialMetric`：

- symbol
- report_period
- announce_date
- available_at
- metric
- value
- unit
- source

Factor Engine 只允许读 Normalized Data。

### 4.4 Data Quality Gate

Raw → Normalized 后必须经过质量校验。

典型规则：

- `close <= 0` → invalid；
- `volume < 0` → invalid；
- 财务记录缺 `announce_date` → 无法进入时点敏感 Factor；
- 极端估值值 → warning / invalid；
- 重复主键 → invalid。

任何数据错误不得静默转成 0。

## 5. 时间模型

财务数据至少保存：

- `report_period`
- `announce_date`
- `available_at`

任何历史计算强制：

`available_at <= as_of`

Snapshot、Factor 与 Strategy 都必须保存 `as_of` 和版本信息，为未来回测避免 Look-ahead Bias。

## 6. Universe Engine

`UniverseBuilder` 每个交易日生成 `UniverseSnapshot`。

默认过滤：

- ST / 退市整理；
- 长期停牌；
- 上市不足约 120 天；
- 20 日平均成交额低于默认阈值；
- 无有效行情。

具体参数写入 `configs/universe.yaml`。

## 7. Factor Engine

### 7.1 Factor Contract

```python
class Factor:
    metadata: FactorMetadata

    def compute(self, context: FactorContext) -> FactorResult:
        ...
```

Factor Metadata 包含：

- name
- domain
- description
- inputs
- frequency
- direction
- null_policy
- version

### 7.2 FactorResult

保存：

- symbol
- factor
- as_of
- raw_value
- status
- factor_version
- source lineage

Factor 不直接输出 Strategy Score。

## 8. Strategy Plugin System

### 8.1 Contract

```python
class StrategyPlugin:
    def required_factors(self) -> set[str]: ...
    def eligibility(self, context: StrategyContext) -> EligibilityResult: ...
    def score(self, context: StrategyContext) -> StrategyResult: ...
    def explain(self, result: StrategyResult) -> Explanation: ...
```

### 8.2 StrategyResult

至少包含：

- symbol
- strategy_id / version
- as_of
- eligible
- score
- rank_percentile
- confidence
- reasons
- risks
- factor_snapshot

### 8.3 算法与参数边界

- 算法写代码；
- 权重与阈值写 YAML；
- 不设计通用复杂 YAML DSL。

## 9. Market Layer

### 9.1 Market Regime

输出：

- BULL
- RANGE_UP
- RANGE
- RANGE_DOWN
- BEAR

### 9.2 Strategy Router

只调整策略展示优先级，不改原始 Strategy Score。

### 9.3 Market Validation

输出：

- CONFIRMED
- NEUTRAL
- CONTRADICTED

## 10. Signal Engine

统一接口：

```python
class SignalDetector:
    def detect(self, context: SignalContext) -> SignalResult:
        ...
```

V1 实现：

- breakout
- pullback
- trend_continue
- trend_weaken
- breakdown

Signal 不负责估值与基本面。

## 11. Candidate Builder

Candidate 是 Strategy + Market + Signal 的组合结果，而不是推荐。

至少包含：

- symbol/name；
- strategy results；
- market validation；
- signal；
- reasons / risks；
- `next_action`。

不要求每天固定候选数量。

## 12. Watchlist

V1 状态机：

`DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL`

状态变更必须记录 Timeline。

Watchlist Record 保存：

- thesis
- key_questions
- risk_conditions
- waiting_for
- created_at / updated_at

## 13. Deep Research Integration

### 13.1 Adapter Contract

```python
class DeepResearchAdapter:
    def submit(self, request: ResearchRequest) -> ResearchJob: ...
    def status(self, job_id: str) -> ResearchJobStatus: ...
    def result(self, job_id: str) -> ResearchSummary: ...
```

V1：`CliDeepResearchAdapter`

未来：`HttpDeepResearchAdapter`

### 13.2 Repository Boundary

A-Stock Lens 与 `a-share-deep-research` 保持两个仓库。

A-Stock Lens 不直接 import 对方内部模块，避免强耦合。

## 14. 存储

V1 采用：

- Parquet：大量历史时序数据；
- DuckDB：元数据、查询、Factor Snapshot、Strategy Result、Watchlist、Job State。

暂不引入 PostgreSQL / Redis。

## 15. Snapshot Model

每日扫描完成后保存：

- UniverseSnapshot
- FactorSnapshot
- StrategySnapshot
- MarketRegimeSnapshot
- CandidateSnapshot

所有结果必须保存版本和 `as_of`，用于复现历史决策上下文。

## 16. Pipeline

每日 Pipeline：

1. `SYNC_DATA`
2. `NORMALIZE`
3. `BUILD_UNIVERSE`
4. `COMPUTE_FACTORS`
5. `RUN_STRATEGIES`
6. `DETECT_REGIME`
7. `MARKET_VALIDATE`
8. `RUN_SIGNALS`
9. `BUILD_CANDIDATES`
10. `UPDATE_WATCHLIST`
11. `GENERATE_DAILY_SNAPSHOT`

每一步都是独立 Job，支持单阶段重跑和 resume。

## 17. Job / Error Model

`JobRun` 保存：

- job_type
- as_of
- started_at
- finished_at
- status
- rows_in / rows_out
- error

错误分级：

- P0：严重数据错误，阻断扫描；
- P1：关键数据缺失，相关模块停止或降级；
- P2：非关键数据缺失，继续并警告；
- P3：展示/辅助问题，仅记录。

## 18. 数据状态

统一支持：

- VALUE
- NULL
- STALE
- INVALID
- SOURCE_ERROR
- NOT_APPLICABLE

禁止用 0 表示“没有数据”。

## 19. API / Web / CLI

### 19.1 API

FastAPI 暴露领域查询接口，Web 不直接访问 DuckDB。

### 19.2 Web

V1 使用 React + FastAPI，仅实现：

- Today
- Screener
- Strategy
- Stock Profile
- Watchlist
- Data Health

### 19.3 CLI

CLI 是一等公民：

```text
astock doctor
astock sync
astock universe build --as-of YYYY-MM-DD
astock factors compute --as-of YYYY-MM-DD
astock strategy run growth --as-of YYYY-MM-DD
astock scan --as-of YYYY-MM-DD
astock stock 000938
astock watch 000938
astock research 000938
astock daily
```

其中只有 `astock daily` 写正式快照：`universe build`、`factors compute`、`strategy run`
是纯计算，`scan` 是 non-persistent preview。工具链只有一条唯一分析执行链
（`astock_lens.pipelines.analysis`），`daily` 在同一组 stage 之上补充 Job 计时、
阶段裁定与正式快照写入。

## 20. 测试体系

### 20.1 代码测试

- Unit：Factor、Universe、Strategy、Signal、状态机；
- Integration：Provider → Normalize → Factor → Strategy；
- Contract：外部数据源字段、Research Adapter 接口。

### 20.2 产物测试

独立 `Artifact Validator` 检查：

- Snapshot 完整性；
- Candidate 引用一致性；
- Strategy/Factor 版本；
- score 范围；
- 状态枚举；
- as_of / available_at 时间约束；
- Candidate 引用的 Factor 必须真实存在。

### 20.3 Golden Dataset

维护约 30–50 只固定股票，覆盖银行、煤炭、消费、半导体、软件、创新药、亏损成长、高股息、周期、ST、新股等。

修改 Strategy 后先跑 Golden Dataset，观察入选变化及原因。

### 20.4 Strategy Characterization

验证策略整体行为仍符合定义：

- Quality Top Quantile 应表现为高 ROE/ROIC、稳定盈利、现金流质量更高；
- Value 应整体估值分位更低、FCF Yield 更高；
- Momentum 应整体 RS 更高、距离阶段新高更近。

## 21. 性能目标

正常个人电脑上，全交易日增量任务（不含 Deep Research）目标在约 10 分钟内完成。

## 22. 可扩展性预留

V1 只预留接口、不实现：

- `backtest/`
- `portfolio/`
- `events/`

未来扩展必须继续遵守现有 Domain Contract，避免侵入核心 Scanner。
