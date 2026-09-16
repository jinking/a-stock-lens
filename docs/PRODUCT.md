# A-Stock Lens 产品说明（V1）

## 1. 产品定位

A-Stock Lens 是一个**本地优先、单用户、面向全 A 股的多策略选股与研究生命周期系统**。

它不把“选股”理解为一次性的条件过滤，而是管理完整研究过程：

`全市场发现 → 策略解释 → 市场验证 → 交易状态 → 观察池 → 深度研究 → 持续跟踪`

核心目标不是直接输出“今天买哪只股票”，而是持续回答：

1. 哪些股票值得研究？
2. 为什么值得研究？
3. 当前市场是否认可这个逻辑？
4. 当前处于什么价格/量价状态？
5. 是否值得进入观察或深度研究？
6. 原始投资假设之后有没有发生变化？

## 2. 产品原则

### 2.1 研究、选股、择时分离

- **研究逻辑**：公司/产业是否值得研究。
- **选股逻辑**：某只股票是否符合特定投资策略。
- **市场验证**：价格、相对强弱、量价是否支持当前判断。
- **交易信号**：只描述市场状态，不直接替用户给出买卖结论。

禁止把 MACD 金叉、均线金叉等短期信号直接解释为“好公司”。

### 2.2 多策略并存，不做单一总分

V1 采用 7 个独立 Scanner：

- Value
- Growth
- GARP
- Quality
- Dividend
- Momentum
- Industry Trend

一只股票可以同时命中多个策略。V1 不把它们强行平均成一个 Global Score。

### 2.3 可解释优先

任何策略结果都必须能追溯到：

`StrategyResult → FactorSnapshot → Normalized Data → Provider`

用户必须能够看到“为什么入选”“主要风险是什么”“使用了哪些因子”。

### 2.4 Candidate ≠ Recommendation

系统输出 Candidate、Research Priority、Signal State，不输出“强烈买入”“建议满仓”。

V1 的 `next_action` 只允许：

- `IGNORE`
- `WATCH`
- `DEEP_RESEARCH`
- `TRACK_SIGNAL`

## 3. V1 用户

V1 面向单个本地用户，不做多用户、权限、云 SaaS。

主要使用方式：

- 每日收盘后查看市场与新增候选；
- 通过策略或 Factor 过滤股票；
- 打开 Stock Profile 理解策略命中原因；
- 将标的加入 Watchlist；
- 对重点候选发起深度研究；
- 跟踪研究假设、风险条件和市场状态变化。

## 4. V1 功能范围

### 4.1 全 A 股 Universe

覆盖沪深北普通股票，并通过 Universe Filter 默认排除：

- ST / *ST；
- 退市整理；
- 长期停牌；
- 上市时间过短；
- 流动性极差标的。

每个交易日保存 `UniverseSnapshot`，保证后续结果可复现。

### 4.2 数据同步

全市场批量扫描优先使用免费/公开数据源：

- AkShare；
- 交易所/公开数据；
- 可替换免费备用源。

深度研究阶段不重复造研究数据层，而是通过现有 `a-share-deep-research`：

- `westock-npm`：结构化主源；
- `westock-cli`：新闻、研报、公告、资金流增强；
- `neodata`：主营、供应链、业绩会、一致预期、风险事件等语义信息。

### 4.3 Factor Engine

V1 目标约 40–60 个核心 Factor，分为：

- Fundamental
- Growth
- Quality
- Valuation
- Market / Momentum
- Technical

核心要求：

- Factor 保存原始值，不直接混入策略评分；
- 每个 Factor 有版本；
- 财务数据遵守 `available_at <= as_of`，避免未来数据穿越；
- NULL / STALE / INVALID / SOURCE_ERROR / NOT_APPLICABLE 明确区分。

### 4.4 Strategy Scanner

#### Value

回答“相对自身历史、同行与现金流是否便宜”。

主要维度：

- PE/PB/PS；
- FCF Yield；
- 股息率；
- 历史估值分位；
- 行业相对估值；
- 盈利与资产负债质量。

边界：不允许简单把低 PE 等同低风险；周期行业必须保留独立估值 Profile 扩展点。

#### Growth

回答“经营是否真正增长”。

主要维度：

- 营收/利润同比；
- 3 年 CAGR；
- 经营现金流；
- ROE 变化；
- 毛利率趋势；
- 增长持续性与兑现质量。

Growth 不负责判断价格是否便宜。

#### GARP

回答“成长与价格是否匹配”。

GARP 复用 Growth 的增长结果，再结合：

- PE / Growth；
- PEG；
- 历史估值分位；
- ROE / FCF；
- 增长稳定性。

#### Quality

回答“生意质量是否长期稳定”。

主要维度：

- ROE / ROIC；
- 毛利率/净利率；
- OCF / FCF；
- 负债；
- 盈利稳定性；
- 现金流质量。

#### Dividend

回答“股息是否高、可持续、能被现金流覆盖”。

重点惩罚：

- 一次性特别分红；
- 周期顶部假高股息；
- 负债维持分红；
- 盈利恶化但股息率被动升高。

#### Momentum

回答“资金/价格趋势是否持续认可它”。

主要维度：

- 20/60/120 日收益；
- 相对沪深300强弱；
- 相对行业强弱；
- 距离 52 周高点；
- 均线趋势；
- 成交量趋势。

#### Industry Trend

先对 Industry 打分，再映射到股票。

由两部分组成：

- Structural Trend：行业收入/利润、需求、价格、库存、政策、资本开支等；
- Market Confirmation：行业指数趋势、成交额、广度、龙头相对强度。

## 5. Market Regime

V1 只做 5 个市场状态：

- `BULL`
- `RANGE_UP`
- `RANGE`
- `RANGE_DOWN`
- `BEAR`

输入包括主要宽基指数趋势、市场成交额、上涨家数、新高/新低与波动率。

Market Regime 不修改原始 Strategy Score，只通过 `StrategyRouter` 调整展示优先级。

## 6. Market Validation

对策略候选给出三种市场验证状态：

- `CONFIRMED`
- `NEUTRAL`
- `CONTRADICTED`

检查维度：

- 个股趋势；
- 行业趋势；
- 相对强度；
- 量价；
- 流动性。

## 7. Signal Engine

V1 信号只描述状态，不给 BUY/SELL：

- `BREAKOUT`
- `PULLBACK`
- `TREND_CONTINUE`
- `TREND_WEAKEN`
- `BREAKDOWN`
- `NO_SIGNAL`
- `WATCH`

MACD / RSI / KDJ 可作为 Factor，但不作为 V1 核心信号模型。

## 8. Candidate 漏斗

目标流程：

`全 A 股 → Universe Filter → 7 Scanner → Strategy Threshold → Market Regime → Market Validation → Signal/Risk/Liquidity → Daily Candidates`

不强制每天固定输出 10 只。候选数量应由市场本身决定。

## 9. 核心页面

V1 只做 6 个核心页面：

1. **Today**：Market Regime、今日候选、状态变化、Watchlist 异动、数据健康；
2. **Screener**：Strategy 模式 + Factor Filter 模式；
3. **Strategy**：策略定义、适用边界、当前优先级、结果；
4. **Stock Profile**：Strategy Map、Factors、Market Validation、Signals、Research、Timeline；
5. **Watchlist**：研究状态机与 thesis；
6. **Data Health**：Provider 与 Dataset 新鲜度、失败/降级信息。

## 10. Watchlist 状态机

V1 启用：

- `DISCOVERED`
- `WATCH`
- `DEEP_RESEARCH`
- `TRACK_SIGNAL`

预留未来状态：

- `READY`
- `HOLDING`
- `EXITED`
- `ARCHIVED`

Watchlist 不只是收藏夹，还保存：

- thesis；
- key_questions；
- risk_conditions；
- waiting_for；
- timeline。

## 11. 深度研究集成

A-Stock Lens 与 `a-share-deep-research` 保持仓库独立，通过标准 `ResearchRequest` + `DeepResearchAdapter` 松耦合集成。

V1 采用 CLI Adapter，接口预留未来 HTTP Adapter。

`ResearchRequest` 至少包含：

- symbol / name / as_of；
- 触发策略及分数；
- Market Validation；
- 推荐重点研究问题。

A-Stock Lens 只保存 `ResearchSummary` 与产物引用，不复制完整深研报告和证据库。

## 12. 每日使用流程

每日收盘后：

1. 打开 Today；
2. 查看 Market Regime 和新增 Candidate；
3. 打开感兴趣股票的 Stock Profile；
4. 理解其策略命中、Factor 与风险；
5. 加入 WATCH；
6. 对重点标的发起 DEEP_RESEARCH；
7. 研究成立但暂不适合交易时转入 TRACK_SIGNAL；
8. 后续由系统持续记录市场状态变化。

## 13. V1 Non-goals

明确不进入 V1：

- 自动下单；
- 券商交易 API；
- 分钟级实时扫描；
- 机器学习选股；
- LLM 直接决定买卖；
- 复杂 Portfolio Optimizer；
- 完整策略历史回测平台；
- 期货/期权；
- 港股/美股；
- 多用户/权限；
- 云端 SaaS 部署。

## 14. V1 验收标准

Fresh Install 后必须跑通：

`doctor → sync → universe → factors → 7 scanners → regime → validation → signals → candidate snapshot → Today → Stock Profile → WATCH → ResearchRequest → DeepResearchAdapter`

这条链完整跑通才视为 V1 完成。
