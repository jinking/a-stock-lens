# A-Stock Lens — Design Spec

**Date:** 2026-09-16  
**Status:** Design approved in conversation; written spec pending final user review  
**Path:** Architectural  

## 1. Purpose

A-Stock Lens is a local-first, single-user, whole-A-share-market stock discovery and research-lifecycle system.

It is not a “condition builder that outputs ten stocks.” Its core responsibility is to turn the full market into a small set of explainable research candidates and preserve the reasoning context over time.

Core lifecycle:

`Discover → Understand → Research → Track`

The system answers:

- Which stocks deserve research?
- Why did they qualify?
- Which investment strategy explains that qualification?
- Does the current market confirm or contradict the thesis?
- What price/volume state is the stock currently in?
- Should it be ignored, watched, deeply researched, or tracked for a signal?

It does **not** make autonomous buy/sell decisions in V1.

## 2. Confirmed Product Constraints

- Repository shape: independent project `a-stock-lens`.
- Runtime: local-first, single user.
- Coverage: full A-share universe (SSE/SZSE/BSE) with Universe filtering.
- Data approach: free/public bulk sources for full-market scanning; existing deep-research stack for candidate-level enhancement.
- V1 scope: discovery and research MVP, not full backtesting or automated trading.
- Integration with `a-share-deep-research`: loose coupling through a standard request model and Adapter; no direct Python package dependency.
- Architecture style: modular monolith, pipeline execution, plugin/adapter extension points.
- Storage: Parquet + DuckDB.
- Backend/UI: FastAPI + React, with CLI as a first-class interface.

## 3. Existing Deep Research Integration

The existing `a-share-deep-research` repository already separates research data responsibilities across three source groups:

- `westock-npm`: structured core data such as company profile, statements, daily K-line, technical indicators, shareholder structure, dividends, main-fund/margin data;
- `westock-cli`: news, broker reports, notices and fund-flow enhancement;
- `neodata`: semantic research such as latest financial results, business segment breakdown, supply-chain relationships, earnings-call content, consensus estimates and risks.

A-Stock Lens therefore does not reimplement the deep-research system. It uses bulk-friendly free/public providers for full-market screening, then creates a `ResearchRequest` for selected stocks.

*Amended by §24 (2026-09-16): the bulk financial-statement source moved to the
same Tencent WeStock CLI the deep-research stack uses. `neodata` keeps the
candidate-level role described above.*

## 4. System Boundary

```text
Public / Bulk Data
        ↓
Provider Layer
        ↓
Raw Storage
        ↓
Normalization
        ↓
Data Quality Gate
        ↓
Universe Filter
        ↓
Factor Engine
        ↓
7 Strategy Scanners
        ↓
Market Regime + Strategy Router
        ↓
Market Validation
        ↓
Signal Engine
        ↓
Candidate Builder
        ↓
Stock Profile / Watchlist
        ↓
ResearchRequest
        ↓
DeepResearchAdapter
        ↓
a-share-deep-research
```

Strict boundary rules:

1. Strategy code must not call AkShare directly.
2. UI must not recompute financial or factor values.
3. Provider code must not contain strategy decisions.
4. A-Stock Lens must not copy deep-research report/evidence logic.
5. All historical calculations must be reproducible through Snapshot + version + `as_of`.

## 5. Data Architecture

### 5.1 Layers

`Provider → Raw → Normalized → Validated → Factor`

Raw data preserves the external source shape as much as practical and includes fetch metadata.

Normalized data uses internal canonical schemas.

Financial data must include:

- `report_period`
- `announce_date`
- `available_at`

Historical computation rule:

`available_at <= as_of`

### 5.2 Bulk vs Research Data

Bulk scanning:

- AkShare;
- Tencent WeStock CLI (financial statements; see §24);
- exchange/public datasets;
- free fallback providers.

Candidate-level research enhancement:

- existing `a-share-deep-research` through Adapter.

### 5.3 Storage

- Parquet: historical and high-volume time series;
- DuckDB: metadata, factor/strategy snapshots, watchlist, job state and analytical queries.

PostgreSQL/Redis are non-goals for V1.

## 6. Universe

Universe covers all A-share ordinary stocks and applies configurable exclusions.

Default rules include:

- ST / delisting-board exclusion;
- long suspension exclusion;
- short listing-age exclusion (default around 120 days);
- minimum 20-day average turnover amount;
- valid market data requirement.

Every run creates an immutable `UniverseSnapshot`.

## 7. Factor Engine

V1 targets approximately 40–60 meaningful factors across:

- Fundamental
- Growth
- Quality
- Valuation
- Market/Momentum
- Technical

Each Factor is a first-class versioned component.

Required metadata:

- name
- domain
- description
- inputs
- frequency
- direction
- null policy
- version

Factor values remain objective raw values. Strategy interpretation and scoring are separate.

Missing-data states are explicit:

- VALUE
- NULL
- STALE
- INVALID
- SOURCE_ERROR
- NOT_APPLICABLE

No silent “error becomes zero.”

## 8. Strategy Plugin Contract

Seven V1 scanners:

1. Value
2. Growth
3. GARP
4. Quality
5. Dividend
6. Momentum
7. Industry Trend

Common contract:

```python
class StrategyPlugin:
    def required_factors(self) -> set[str]: ...
    def eligibility(self, context: StrategyContext) -> EligibilityResult: ...
    def score(self, context: StrategyContext) -> StrategyResult: ...
    def explain(self, result: StrategyResult) -> Explanation: ...
```

StrategyResult includes eligibility, score, rank percentile, confidence, reasons, risks and the factor snapshot used.

V1 intentionally does not create a single cross-strategy global score.

### 8.1 Strategy Character

- Value: cheapness relative to history, peers and cash-flow quality.
- Growth: operating growth speed, persistence and earnings/cash-flow conversion.
- GARP: growth quality versus valuation; reuses Growth output.
- Quality: durable profitability, capital efficiency, cash flow and balance-sheet quality.
- Dividend: dividend sustainability and cash-flow coverage, not just yield.
- Momentum: absolute and relative price strength, trend and volume confirmation.
- Industry Trend: structural industry trend first, then market confirmation and stock mapping.

## 9. Market Layer

Market Regime states:

- BULL
- RANGE_UP
- RANGE
- RANGE_DOWN
- BEAR

The Strategy Router only adjusts display/research priority. It never rewrites original Strategy Scores.

Market Validation output:

- CONFIRMED
- NEUTRAL
- CONTRADICTED

Validation inputs include stock trend, industry trend, relative strength, volume/price behavior and liquidity.

## 10. Signal Engine

V1 signals:

- BREAKOUT
- PULLBACK
- TREND_CONTINUE
- TREND_WEAKEN
- BREAKDOWN
- NO_SIGNAL
- WATCH

Signals describe market state and are not investment recommendations.

MACD/RSI/KDJ may exist as factors but are not the core signal abstraction.

## 11. Candidate Model

Candidate is a research object, not a recommendation.

It includes:

- symbol / name;
- matched strategies and scores;
- Market Validation;
- current Signal;
- reasons and risks;
- next action.

Allowed V1 next actions:

- IGNORE
- WATCH
- DEEP_RESEARCH
- TRACK_SIGNAL

Candidate volume is not fixed. Market conditions determine how many candidates survive.

## 12. Product Experience

Six V1 pages:

1. Today
2. Screener
3. Strategy
4. Stock Profile
5. Watchlist
6. Data Health

### 12.1 Today

Shows Market Regime, daily scan counts, newly added/removed candidates, watchlist state changes, pending research and data health.

### 12.2 Screener

Two modes:

- Strategy mode;
- Factor-filter mode.

These are kept conceptually separate.

### 12.3 Strategy Page

Explains strategy purpose, holding horizon, appropriate market regimes, failure modes, current priority and current results.

### 12.4 Stock Profile

Contains:

- Overview
- Strategy Map
- Factor details
- Market Validation
- Signals
- Research
- Timeline

Every score is expandable to factor-level explanation.

## 13. Watchlist State Machine

V1 active states:

`DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL`

Future reserved states:

- READY
- HOLDING
- EXITED
- ARCHIVED

Each Watchlist item stores:

- thesis
- key questions
- risk conditions
- waiting-for conditions
- timeline

## 14. Deep Research Adapter

Standard interface:

```python
class DeepResearchAdapter:
    def submit(self, request: ResearchRequest) -> ResearchJob: ...
    def status(self, job_id: str) -> ResearchJobStatus: ...
    def result(self, job_id: str) -> ResearchSummary: ...
```

V1 implementation: CLI Adapter.

Future compatible implementation: HTTP Adapter.

A-Stock Lens stores only research summary and artifact reference; full report/evidence stays owned by `a-share-deep-research`.

## 15. Pipeline

Daily pipeline:

1. SYNC_DATA
2. NORMALIZE
3. BUILD_UNIVERSE
4. COMPUTE_FACTORS
5. RUN_STRATEGIES
6. DETECT_REGIME
7. MARKET_VALIDATE
8. RUN_SIGNALS
9. BUILD_CANDIDATES
10. UPDATE_WATCHLIST
11. GENERATE_DAILY_SNAPSHOT

Every stage is independently restartable.

Job state records run dates, counts, errors and timing.

Incremental processing is required: do not redownload/recompute full history every day when unchanged.

## 16. Error Handling and Data Health

Severity levels:

- P0: potentially corrupts selection; block current scan;
- P1: key dataset unavailable; block/degrade related module;
- P2: non-critical missing data; continue with warning;
- P3: presentation/auxiliary problem; log only.

Provider and Dataset freshness are visible in the Data Health page and via CLI doctor command.

## 17. CLI

Required V1 commands:

```text
astock doctor
astock sync
astock universe build --as-of YYYY-MM-DD
astock factors compute --as-of YYYY-MM-DD
astock strategy run <strategy> --as-of YYYY-MM-DD
astock scan --as-of YYYY-MM-DD
astock stock <symbol>
astock watch <symbol>
astock research <symbol>
astock daily
```

CLI must be usable by cron and coding agents without relying on the Web UI.

## 18. Testing Strategy

Two independent lines:

### 18.1 Code Tests

- Unit tests for factor calculations, universe rules, strategy eligibility/score, signal detection and state machines.
- Integration tests for Provider → Normalize → Factor → Strategy.
- Contract tests for external data schemas and Research Adapter.

### 18.2 Artifact Tests

An independent Artifact Validator checks final snapshots and candidates rather than trusting internal implementation.

Checks include:

- snapshot completeness;
- score/state validity;
- factor references exist;
- factor/strategy versions present;
- `available_at <= as_of`;
- candidate lineage consistency.

Artifact failures become regression cases.

### 18.3 Golden Dataset

Maintain a fixed 30–50 stock fixture set covering multiple industries and edge cases.

Strategy changes must first run against this set.

### 18.4 Strategy Characterization

Test whether top-ranked outputs still exhibit the intended strategy phenotype, e.g. Quality candidates should actually show higher quality metrics overall.

## 19. Project Layout

```text
a-stock-lens/
├── docs/
├── configs/
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
├── scripts/
├── tests/
└── var/
```

Full details live in `docs/ARCHITECTURE.md`.

## 20. V1 Non-goals

- automated trading;
- broker API execution;
- minute-level real-time scanning;
- machine-learning stock selection;
- LLM autonomous investment decisions;
- advanced portfolio optimizer;
- full historical backtest platform;
- futures/options;
- Hong Kong/U.S. markets;
- multi-user authorization;
- cloud SaaS deployment.

Backtest, portfolio and event subsystems may have reserved interfaces/directories but no V1 business implementation.

## 21. Performance Target

On a normal personal workstation, daily incremental whole-market processing excluding Deep Research should target completion within roughly 10 minutes.

## 22. V1 Acceptance Test

A clean installation must complete the following chain:

`doctor → sync → universe → factors → seven scanners → regime → market validation → signals → candidate snapshot → Today → Stock Profile → WATCH → ResearchRequest → DeepResearchAdapter`

Only when this chain is demonstrably functional should V1 be called complete.

## 23. Design Principles to Protect During Implementation

1. Explainability over opaque ranking.
2. Time correctness over convenience.
3. Snapshot reproducibility over “always recalculate latest.”
4. Data problems must be visible, not silently hidden.
5. Strategy definitions remain distinct; do not converge them into one generic weighted model.
6. Keep Stock Lens focused on discovery and lifecycle; keep Deep Research focused on evidence-heavy company research.
7. Keep V1 narrow enough to finish.

## 24. 补遗 2026-09-16 — 数据源边界

**状态：** 项目所有者在对话中批准，并记录于此。

归档设计包把深研项目的三组数据源（`westock-npm`、`westock-cli`、`neodata`）全部划给研究侧。
2026-09-16 的实测改变了其中一部分：

- 腾讯 WeStock CLI（`westock finance`）是唯一同时满足两个条件的数据源：把**报告期与可靠的
  公告日期**配成一对（`EndDate` + `InfoPublDate`，§5.1 要求两者），并支持**批量**
  （`westock finance sh600000,sz000001`）。100 只约 11 秒且返回完整，因此全市场三张表约需
  半小时——那是季度刷新任务，而不是每日扫描的一部分，这也正是 §15 增量规则想要的结果。
  AkShare/Sina 三大表返回的 `公告日期` **不是原始公告日**（实测：2025 年报在资产负债表里标
  `20260815`，而同一报告期在利润表里标 `20260417`），因此它们无法单独承载时点规则。
- 因此**财务三大表的 bulk 源是 WeStock**，并且仍然走
  Provider → Raw → Normalized → Quality Gate 这条常规路径。WeStock 以外部命令调用；
  A-Stock Lens 不导入深研项目的 Python 模块，也不读取它的内部状态。
- **`neodata` 保持 candidate 级角色。** 它以自然语言提问、以渲染后的 Markdown 作答，
  逐标的查询，凭证 12 小时有效且只能由 WorkBuddy 平台刷新，因此不适合作为批量因子源。
  它和其余研究侧能力一样，只经 `ResearchRequest` → `DeepResearchAdapter` 使用。
- AkShare 保留它已有的两个角色：交易所名单（标的枚举）与日线行情。

§3、§4 与 §5.2 的其余内容保持不变。
