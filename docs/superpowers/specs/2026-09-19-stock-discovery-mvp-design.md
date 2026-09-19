# Stock Discovery MVP 设计规格

**日期：** 2026-09-19  
**状态：** 已按项目所有者确认的方向形成  
**目标：** 把已经真实计算出的 StrategyResult 变成可快速查询的股票研究榜单，而不提前绕过 Candidate Qualification / Market Validation / Signal 的产品 Gate。

## 1. 当前事实

当前项目已经具备真实的全研究池分析能力：

- Research Universe：2,303 只；
- FactorResult：55,272 条；
- StrategyResult：13,818 条；
- Growth / Momentum / Quality / Dividend 已具备大规模真实排序能力；
- Value / GARP 仍受估值覆盖限制；
- CandidatePolicy、StrategyQualification 架构已经实现，但六策略绝对质量规则、Market Validation、Signal 尚未批准/实现，因此正式 Candidate 发布继续 BLOCKED。

当前主要缺口不是“算不出来”，而是“算出来以后缺少适合日常使用的查询面”。

## 2. 产品边界

本 MVP 引入 **Stock Discovery / Strategy Screener**。

它回答：

> 某个策略下，当前研究池中排名靠前的是哪些股票？为什么？

它不回答：

> 今天应该买哪些股票？

因此必须保持：

```text
Strategy Result / Research Ranking != Candidate != Investment Recommendation
```

允许使用：Strategy Ranking、Research Shortlist、Stock Discovery、Screener Result。禁止把 Screener 结果称为最终 Candidate 或买入推荐。

## 3. 核心使用体验

### CLI

新增：

```bash
astock screen growth --as-of 2026-09-17 --top 20
astock screen momentum --as-of 2026-09-17 --top 30
astock screen quality --as-of 2026-09-17 --top 20 --min-percentile 0.95
```

结果来自已落地的正式 `STRATEGY` Snapshot，不重新计算全市场。

输出至少包含：

```text
rank
symbol
score
rank_percentile
eligible
confidence
```

并显示 total / eligible / scored / returned 数量。默认 `--top 20` 只是展示数量，不是 Candidate 规则。

### API

新增：

```http
GET /strategies?as_of=2026-09-17
GET /strategies/growth/results?as_of=2026-09-17&limit=20
GET /stocks/600519.SH?as_of=2026-09-17
```

API 只读取正式 Snapshot / Watchlist，不调用 Factor/Strategy 计算引擎。

### 单股查询

Stock Profile API 聚合：

```text
Universe verdict
Factor results
Strategy results
Candidate（如果正式 Candidate snapshot 存在）
Watchlist entry（如果存在）
```

Candidate snapshot 不存在是当前正常状态，Stock Profile 不应因此整体 404。

## 4. 统一查询层

新增：

```text
src/astock_lens/discovery/
    models.py
    service.py
```

建议模型：

```python
class StrategyScreenQuery(DomainRecord):
    strategy_id: str
    limit: int = 20
    eligible_only: bool = True
    min_percentile: float | None = None

class StrategyScreenItem(DomainRecord):
    rank: int
    symbol: str
    strategy_id: str
    strategy_version: str
    score: float | None
    rank_percentile: float | None
    confidence: float | None
    eligible: bool
    reasons: tuple[str, ...]
    risks: tuple[str, ...]

class StrategyCoverage(DomainRecord):
    strategy_id: str
    total_count: int
    eligible_count: int
    scored_count: int
    ranked_count: int

class StrategyScreenResult(DomainRecord):
    strategy_id: str
    coverage: StrategyCoverage
    items: tuple[StrategyScreenItem, ...]
```

排序：

```text
rank_percentile DESC
score DESC
symbol ASC
```

没有 `rank_percentile` 的结果排在有排名结果之后。

禁止在该层创建跨策略 global score、应用 Candidate Qualification、或伪造 MarketValidation / Signal。

## 5. 数据源语义

`astock screen` 读取正式 `SnapshotKind.STRATEGY`。如果该日期没有 Snapshot，明确提示：

```text
no STRATEGY snapshot for YYYY-MM-DD;
run astock daily --as-of YYYY-MM-DD --allow-incomplete
```

不静默重新计算。

已有 `astock strategy run` / `astock scan` 继续作为计算预览：

```text
strategy run / scan = compute preview
screen              = query stored result
```

## 6. 覆盖率必须可见

每次查询必须展示：

```text
strategy total results
eligible count
scored count
ranked count
```

Value / GARP 如果覆盖不足必须显式警告，不能让用户误解为来自完整研究池。

## 7. Candidate 边界

本 MVP 不解除 Candidate BLOCKED。

Stock Profile 中：

```text
candidate = null
candidate_status = "not_published"
```

是合法结果。

禁止从 StrategyScreenResult 临时构造 Candidate。

## 8. 文档状态修正

本轮必须修正：

1. ROADMAP 不得再写“全市场只有 5 只能打分”；
2. 记录当前真实 Research Universe 2,303 和真实 Strategy baseline；
3. `industry_trend` blocker 不应再写“没有 industry data landed”；
4. blocker 改为行业聚合指标与 Industry Trend 打分口径尚未批准/实现；
5. 当前测试基线必须来自实际命令。

## 9. 非目标

本 MVP 不做 React Web、Candidate 绝对门槛、Market Regime、Market Validation、Signal、Industry Trend、Value/GARP 估值补全、自动买入推荐、跨策略综合排名、Watchlist 自动迁移。

## 10. 验收

完成后至少支持：

```bash
astock daily --as-of 2026-09-17 --allow-incomplete
astock screen growth --as-of 2026-09-17 --top 20
astock screen momentum --as-of 2026-09-17 --top 20
astock stock 600519.SH --as-of 2026-09-17
```

以及：

```http
GET /strategies?as_of=2026-09-17
GET /strategies/growth/results?as_of=2026-09-17&limit=20
GET /stocks/600519.SH?as_of=2026-09-17
```

同时 API 不触发计算、Screener 不写 Snapshot、Candidate 不被伪造、覆盖不足显式提示、重复查询稳定。
