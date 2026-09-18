# Factor configuration

每个文件定义一个 Factor。**参数写在这里，算法写在代码里**（`docs/ARCHITECTURE.md` §8.3：算法写代码，权重与阈值写 YAML，不设计通用 YAML DSL）。

Factor 只产出客观原始值；策略解释与评分属于策略层。

## 已定义（24 个，与 `configs/factors/*.yaml` 一一对应）

这张表是配置的事实清单，不是阈值表：唯一已批准的阈值是最新流动性下限
`min_average_turnover_20d = 20,000,000` 元（金总 2026-09-16 定，写入
`configs/universe.yaml`）；其余阈值一律 `Deferred`，见下文「未批准」。

### 行情与动量（`MARKET_MOMENTUM`，日频）

| 文件 | 因子 | 输入 | 参数 | 说明 |
| --- | --- | --- | --- | --- |
| `avg_amount_20d.yaml` | `avg_amount_20d` | `amount` | `window: 20` | 日成交额的滚动均值。窗口 `20` 来自设计 spec §6 与 `docs/ARCHITECTURE.md` §6 的「20 日平均成交额」；**阈值**已批准为 20,000,000 元，写在 `configs/universe.yaml` 而不是这里。 |
| `ret_20d.yaml` | `ret_20d` | `close` | `window: 20` | 20 个交易日区间收益（窗口首尾收盘价之比减一）。窗口出自 spec §8.1 的「20/60/120-day returns」。 |
| `ret_60d.yaml` | `ret_60d` | `close` | `window: 60` | 同上，窗口为 60。同一算法、不同参数，因此与 `ret_20d` 共用同一个实现类，`ret_` 前缀就是它们的契约。 |
| `proximity_52w_high.yaml` | `proximity_52w_high` | `close`、`high` | `window: 252` | 最新收盘价 ÷ 窗口内最高价。窗口 `252` 个交易日即 52 周；「52 weeks」是设计原文（spec §8.1），把周换算成交易日这一步写在配置里，而不是藏在代码中。 |

### 成长（`GROWTH`，季频）

| 文件 | 因子 | 输入 | 参数 |
| --- | --- | --- | --- |
| `net_profit_parent_cagr_3y.yaml` | `net_profit_parent_cagr_3y` | `net_profit_parent_cagr_3y` | `stale_after_days: null` |
| `net_profit_parent_yoy.yaml` | `net_profit_parent_yoy` | `net_profit_parent_yoy` | `stale_after_days: null` |
| `revenue_cagr_3y.yaml` | `revenue_cagr_3y` | `revenue_cagr_3y` | `stale_after_days: null` |
| `revenue_yoy.yaml` | `revenue_yoy` | `revenue_yoy` | `stale_after_days: null` |

### 质量（`QUALITY`，季频）

| 文件 | 因子 | 输入 | 参数 |
| --- | --- | --- | --- |
| `debt_to_asset.yaml` | `debt_to_asset` | `debt_to_asset` | `stale_after_days: null` |
| `goodwill_to_equity.yaml` | `goodwill_to_equity` | `goodwill`、`total_equity` | `stale_after_days: null` |
| `gross_margin.yaml` | `gross_margin` | `gross_margin` | `stale_after_days: null` |
| `interest_bearing_debt_to_equity.yaml` | `interest_bearing_debt_to_equity` | `interest_bearing_debt`、`total_equity` | `stale_after_days: null` |
| `ocf_to_net_profit.yaml` | `ocf_to_net_profit` | `net_operating_cashflow_ttm`、`net_profit_parent_ttm` | `stale_after_days: null` |
| `revenue_ttm_to_inventory.yaml` | `revenue_ttm_to_inventory` | `revenue_ttm`、`inventories` | `stale_after_days: null` |
| `roe_ttm.yaml` | `roe_ttm` | `roe_ttm` | `stale_after_days: null` |

### 估值（`VALUATION`，日频，来源 neodata）

| 文件 | 因子 | 输入 | 参数 |
| --- | --- | --- | --- |
| `dividend_yield_ttm.yaml` | `dividend_yield_ttm` | `dividend_yield_ttm` | `stale_after_days: null` |
| `pb.yaml` | `pb` | `pb` | `stale_after_days: null` |
| `pcf_operating_ttm.yaml` | `pcf_operating_ttm` | `pcf_operating_ttm` | `stale_after_days: null` |
| `pe_percentile.yaml` | `pe_percentile` | `pe_percentile` | `stale_after_days: null` |
| `pe_ttm.yaml` | `pe_ttm` | `pe_ttm` | `stale_after_days: null` |
| `peg.yaml` | `peg` | `peg` | `stale_after_days: null` |
| `ps_ttm.yaml` | `ps_ttm` | `ps_ttm` | `stale_after_days: null` |

### 分红口径（`FUNDAMENTAL`，季频）

| 文件 | 因子 | 输入 | 参数 | 说明 |
| --- | --- | --- | --- | --- |
| `dividend_paid_ratio.yaml` | `dividend_paid_ratio` | `dividend_paid_ratio` | `stale_after_days: null` | 源站发布的年报分红支付率。选它而非 TTM 口径的原因写在 YAML 注释里（TTM 分母塌缩时会给出 6407% 这类值）。 |
| `dividend_payout_ttm.yaml` | `dividend_payout_ttm` | `dividend_ttm`、`net_profit_parent_ttm` | `stale_after_days: null` | 分红 TTM ÷ 归母净利 TTM；形状问题（1950%/274% 这类极值）仍是所有者待决项。 |

## 未批准（`Deferred`）

- 每个因子的 `stale_after_days` 目前**全部为 `null`**：新鲜度上限没有已评审的值，因此不触发 `STALE`。
- 因子值的合格线（例如 ROE 多少算好、PEG 多少算便宜）一概未批准；批准方式是先出全市场校准报告，再由所有者逐策略批准，见 `docs/superpowers/specs/2026-09-17-candidate-qualification-design.md` §2.4 与 §7。
- 已知待裁决的口径问题：Growth 极值、Dividend 支付率形状、PEG 值域与负值。

## 约定

- 代码不提供任何默认参数值。缺少 `params.window` 会让因子构造失败，而不是退回一个隐含窗口。
- 窗口不完整（bar 数量不足，或窗口内任一 bar 缺所需字段）时输出 `NULL`，**不会**用更短的窗口凑一个数——那等于悄悄回答了另一个问题。
- 区间收益需要 `window + 1` 根 bar：区间跨越 `window` 个交易日间隔，因此需要 `window + 1` 个观测点才有起点。
- `frequency`、`direction`、`null_policy` 是自由字符串：设计文档没有枚举这三个词表，因此它们在此处显式声明，改词只改配置、不动代码。
- 因子假定输入数据已经过 Data Quality Gate；这条边界写在代码里，不在因子内重复实现一遍质量判定。
