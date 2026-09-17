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

每个策略有**自己的一类**，不是"一套通用加权实现 + 七份配置"：

| 策略 | 实现 | 资格与算法边界 |
| --- | --- | --- |
| `momentum` | `strategies/momentum.py` | 自带横截面评分实现 |
| `growth` | `strategies/growth.py` | 独立类；打分委托共享 scorer |
| `quality` | `strategies/quality.py` | 独立类；打分委托共享 scorer |
| `dividend` | `strategies/dividend.py` | 独立类；打分委托共享 scorer |
| `value` | `strategies/value.py` | 独立类；打分委托共享 scorer |
| `garp` | `strategies/garp.py` | 独立类；打分委托共享 scorer |
| `industry_trend` | 尚无实现 | 缺行业数据，`build_scanner` 按名字拒绝 |

类与类的区别**不**由 YAML 里的 `weights` 推断：`registry.IMPLEMENTATIONS` 是显式
映射表，加策略 = 加一个类 + 登记一行。这样每个策略才能拥有自己的资格规则
（例如"增长要两端同时成立""分红要看现金流覆盖"），而不是被锁在一个通用实现里。

共享的部分只有算术：`strategies/percentile_scorer.py` 负责 percentile、极性、
加权混合与贡献分解。它不知道自己被哪个策略调用。

## 2. 共同契约

```python
class StrategyPlugin:
    def required_factors(self) -> set[str]: ...
    def eligibility(self, context: StrategyContext) -> EligibilityResult: ...
    def score(self, context: StrategyContext) -> StrategyResult: ...
    def score_cross_section(self, contexts: Sequence[StrategyContext]) -> tuple[StrategyResult, ...]: ...
    def explain(self, result: StrategyResult) -> Explanation: ...
```

`score()` 看单只标的，因此不给分——`rank_percentile` 必须有总体才有意义；
`score_cross_section()` 才是一次完整的横截面打分。

`StrategyResult` 至少包含：`symbol`、`strategy_id`、`strategy_version`、`as_of`、`eligible`、`score`、`rank_percentile`、`confidence`、`reasons`、`risks`、`factor_snapshot`、`lineage`。

解释链必须可达：`StrategyResult → FactorSnapshot → Normalized Data → Provider`。

## 3. 算法与参数边界

- 算法写代码；
- 权重与阈值写 YAML；
- 不设计通用复杂 YAML DSL。
- 策略的实现类写代码，**不由 YAML 推断**（见 §1）。

## 4. Market Layer 与策略的关系

- Market Regime 只有展示与研究优先级的作用，**不得改写原始 Strategy Score**；
- Market Validation 输出 `CONFIRMED`、`NEUTRAL`、`CONTRADICTED`，输入包括个股趋势、行业趋势、相对强弱、量价行为与流动性；
- Signal 只描述市场状态（`BREAKOUT`、`PULLBACK`、`TREND_CONTINUE`、`TREND_WEAKEN`、`BREAKDOWN`、`NO_SIGNAL`、`WATCH`），不负责估值与基本面，也不构成买卖结论。

## 5. Deferred

- 六个 Scanner 的权重已于 2026-09-17 评审通过（等权，含负权重的极性表达）。
- 仍待所有者决定：Growth 极值稳健化、Dividend payout shape、PEG 值域处理、
  Industry Trend 的行业打分口径，以及 Candidate Qualification 本身（见 `docs/ROADMAP.md` 第一节）。
- `confidence` 的计算方式：`Deferred`（设计要求字段但未定义算法，当前恒为 `null`）。
- 评分阈值与 `rank_percentile` 的解释口径：`Deferred`。
- `eligibility` 的最低数据覆盖要求：`Deferred`。
- 策略特征化（phenotype）测试的具体判定指标：`Deferred`。
