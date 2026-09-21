# Production Candidate v2 + Web MVP 设计规格

**日期：** 2026-09-21  
**仓库：** `jinking/a-stock-lens`  
**审计基线 HEAD：** `794e8226d7c4bcdb9245fa1ff558b93e40198ac9`

## 1. 目标

当前项目已经具备：

```text
screen
qualified
Candidate v2 算法
Candidate v2 独立沙箱验收
candidates CLI
today CLI
/candidates API
/today API
/stocks/{symbol} API
```

本升级不继续扩展选股算法，而是完成两个产品化闭环：

```text
A. Production Candidate v2 Closure
   让标准 astock daily 真正使用 Candidate v2 所需 benchmark / SW2 / 5D 证据，
   正式写 MARKET_REGIME Snapshot，并在新的交易日产生 canonical Candidate v2。

B. Web MVP
   用已有 FastAPI 查询层构建浏览器可视化：
   Today / Candidates / Stock Profile / Screener。
```

完成后用户应能：

```text
浏览器打开 A-Stock Lens
→ 默认进入最新已发布 Candidate 日期
→ 看到市场状态与候选概览
→ 查看 20~50 只研究候选
→ 点击股票查看为什么入选
→ 切换策略查看单策略排名与双门槛合格池
```

Candidate 始终表示“研究候选”，不是自动买入建议。

## 2. 当前确认的生产缺口

### 2.1 `run_daily()` 已支持 v2 输入，但 CLI composition root 未装配

`run_daily()` 已支持：

```python
benchmark_id: str = "000985.CSI"
benchmark_bars: Sequence[DailyBar] | None = None
industry_by_symbol: Mapping[str, str] | None = None
```

但 `cli/app.py::_run_daily()` 当前没有传 `benchmark_bars` 和 `industry_by_symbol`。
因此 Candidate v2 sandbox acceptance 还不等价于标准 `astock daily` 生产入口。

### 2.2 生产 Market Validation 仍允许缺维度继续判定

当前 `MarketValidator` 对：

```text
industry_excess_return
relative_strength_60d
vol_ratio
```

仍允许 `None` 后继续形成 `CONFIRMED / NEUTRAL / CONTRADICTED`。其中 `relative_strength_60d=None` 时还会回退到股票自身 `ret_60d`。

生产 v2 必须改为：

```text
5D evidence complete
or
Candidate publishing fail-closed
```

禁止 fallback。

### 2.3 R2 仍允许 breadth-only 判定

批准方案 A1 使用：

```text
market breadth
+
000985.CSI trend = MA20 / MA60
```

B3 表示 extreme volatility 暂缓，并不意味着 benchmark trend 可以缺失。生产 Candidate v2 中 `breadth_ratio` 与 `index_trend` 必须同时存在。

### 2.4 MARKET_REGIME 没有正式 Snapshot producer

枚举中已有 `SnapshotKind.MARKET_REGIME`，`today` 与 `/today` 也会尝试读取该 Snapshot，但 `_record()` 当前没有写 `state.regime_result`。

正式 daily 应写：

```text
UNIVERSE
FACTOR
STRATEGY
MARKET_REGIME
CANDIDATE
```

### 2.5 Candidate v2 目前是验收沙箱，不是新 canonical production 日

v2 审计使用：

```text
var/acceptance/candidate-v2-20260921/
```

并保持历史：

```text
data/snapshots/CANDIDATE/2026-09-19.json
```

不可变。因此不能覆盖 `2026-09-19` 把 v1 变成 v2。必须选择下一个数据完整的新交易日，使用标准 `astock daily` 正式发布 canonical Candidate v2。

## 3. Production Candidate v2 完整证据契约

### 3.1 Market Regime

生产判定要求：

```text
breadth_ratio != None
index_trend != None
```

B3 决策下 `extreme_volatility=False` 表示“该维度暂缓启用”，必须在 reasons/version 中可追溯，不能伪装成“已经测得不极端”。

### 3.2 Market Validation 5D

每个 qualified symbol 必须拥有：

```text
1. 个股趋势
   ret_20d
   proximity_52w_high

2. 行业趋势
   SW2 industry_excess_return_20d

3. 相对强弱
   stock_ret_60d - 000985.CSI_ret_60d

4. 量价
   volume_ratio_5_20

5. 流动性
   avg_amount_20d
```

任何一个必需证据缺失：

```text
MarketValidationEvidenceIncomplete
→ MARKET_VALIDATE fail-closed
→ no new CANDIDATE snapshot
```

## 4. Production evidence loading

### Industry

沿用已有：

```text
data/raw/westock/industry/<YYYY-MM-DD>.csv
```

以及：

```python
read_industry_memberships(...)
build_industry_map(...)
load_supplemental_industry_memberships(...)
```

选择规则：读取 `<= as_of` 的最新 industry landing，加 supplemental memberships，再 `build_industry_map`。文件缺失、空 membership、多行业歧义、未来日期全部显式失败。

### Benchmark

批准 benchmark：

```text
000985.CSI
```

生产输入固定为：

```text
data/raw/benchmark_bars.csv
```

canonical columns：

```text
symbol
trade_date
open
high
low
close
volume
amount
```

本升级不允许在 `daily` 内临时联网抓 benchmark。职责分开：

```text
sync/ingest benchmark → Raw
astock daily → 只读 Raw / Normalized
```

若当前 provider 没有稳定指数端点，允许使用预先落地的 canonical benchmark CSV；但少于 60 根有效 bar 时必须 fail-closed。

## 5. Snapshot publication contract

保持：

```text
同 kind + 同 as_of + 不同内容
→ SnapshotConflictError
```

不得通过删除旧文件、移动旧文件、覆盖 JSON 或切换 backend 绕过不可变约束。

## 6. Web MVP 范围

只做四页：

```text
/                         Today
/candidates               Candidate Pool
/stocks/:symbol           Stock Profile
/strategies/:strategyId   Strategy Screener
```

本轮不做：Watchlist 编辑、Deep Research 发起、Data Health 完整页、登录权限、券商交易、实时行情、自动买卖、复杂图表终端。

## 7. Web UX

### Today

展示：

```text
As-of date
Market Regime
Candidate count
Confirmed / Neutral counts
Strategy distribution
Signal distribution
Top 10 Candidates
```

### Candidate Pool

字段：

```text
Rank
Symbol
Primary Strategy
Qualified Strategies
Market Validation
Signal
Next Action
Risks
```

支持：strategy filter、validation filter、signal filter、symbol search。筛选只隐藏行，不重排 Candidate。

### Stock Profile

展示：

```text
Universe status
Candidate status
Primary strategy
Qualified strategies
Market Validation
Signal
Reasons
Risks
Strategy scores / percentiles
Factor values / status
Lineage
Watchlist status
```

### Strategy Screener

两个 tab：

```text
Ranking
Qualified
```

Ranking 调用 `GET /strategies/{strategy_id}/results`；Qualified 调用 `GET /qualifications/{strategy_id}/results`。

## 8. Web 技术边界

技术栈：

```text
React
TypeScript
Vite
React Router
native fetch
CSS
```

不引入全局状态库，不引入大型 UI framework。Web 只访问 FastAPI，不直接读取 snapshots / DuckDB，不重算 Factor / Strategy / Candidate。

新增：

```text
GET /snapshot-dates?kind=CANDIDATE
```

用于默认选择最新正式 Candidate 日期。

## 9. 验收标准

### Backend production closure

必须同时满足：

```text
standard astock daily consumes benchmark + industry evidence
5D missing evidence fails closed
R2 missing benchmark trend fails closed
MARKET_REGIME snapshot exists
new canonical Candidate v2 date exists
independent artifact validation = 0 findings
GitHub CI = green
```

### Web MVP

用户通过浏览器无需 CLI 即可完成：

```text
最新日期
→ Today
→ Candidate
→ Stock Profile
→ Strategy Ranking / Qualified
```

Web 只读，浏览页面不会改变 Snapshot / Watchlist / Job 状态。
