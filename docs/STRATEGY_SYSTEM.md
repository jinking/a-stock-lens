# 策略系统（V1）

## 1. 七个独立 Scanner

V1 有 7 个互不合并的 Scanner，定义在 `configs/strategies/*.yaml`：

| id | 回答的问题 |
| --- | --- |
| `value` | 相对自身历史、同行与现金流是否便宜 |
| `growth` | 经营是否真正增长 |
| `garp` | 成长与价格是否匹配（复用 Growth 的增长结果） |
| `quality` | 生意质量是否长期稳定 |
| `dividend` | 股息是否高、可持续、能被现金流覆盖 |
| `momentum` | 资金与价格趋势是否持续认可它 |
| `industry_trend` | 产业趋势是否成立，以及个股是否映射到该趋势 |

一只股票可以同时命中多个策略。V1 **不产生跨策略的全局总分**。

## 2. 共同契约

```python
class StrategyPlugin:
    def required_factors(self) -> set[str]: ...
    def eligibility(self, context: StrategyContext) -> EligibilityResult: ...
    def score(self, context: StrategyContext) -> StrategyResult: ...
    def explain(self, result: StrategyResult) -> Explanation: ...
```

`StrategyResult` 至少包含：`symbol`、`strategy_id`、`strategy_version`、`as_of`、`eligible`、`score`、`rank_percentile`、`confidence`、`reasons`、`risks`、`factor_snapshot`、`lineage`。

解释链必须可达：`StrategyResult → FactorSnapshot → Normalized Data → Provider`。

## 3. 算法与参数边界

- 算法写代码；
- 权重与阈值写 YAML；
- 不设计通用复杂 YAML DSL。

## 4. Market Layer 与策略的关系

- Market Regime 只有展示与研究优先级的作用，**不得改写原始 Strategy Score**；
- Market Validation 输出 `CONFIRMED`、`NEUTRAL`、`CONTRADICTED`，输入包括个股趋势、行业趋势、相对强弱、量价行为与流动性；
- Signal 只描述市场状态（`BREAKOUT`、`PULLBACK`、`TREND_CONTINUE`、`TREND_WEAKEN`、`BREAKDOWN`、`NO_SIGNAL`、`WATCH`），不负责估值与基本面，也不构成买卖结论。

## 5. Deferred

- 每个策略的权重、评分阈值、`rank_percentile` 与 `confidence` 的计算方式：`Deferred`。V1 配置文件目前只包含 `id`、`enabled`、`version`、`description`、`dimensions`。
- `eligibility` 的最低数据覆盖要求：`Deferred`。
- 策略特征化（phenotype）测试的具体判定指标：`Deferred`。
