# Factor configuration

每个文件定义一个 Factor。**参数写在这里，算法写在代码里**（`docs/ARCHITECTURE.md` §8.3：算法写代码，权重与阈值写 YAML，不设计通用 YAML DSL）。

Factor 只产出客观原始值；策略解释与评分属于策略层。

## 已定义

| 文件 | 因子 | 说明 |
| --- | --- | --- |
| `avg_amount_20d.yaml` | `avg_amount_20d` | 日成交额的滚动均值。窗口 `20` 来自设计 spec §6 与 `docs/ARCHITECTURE.md` §6 的「20 日平均成交额」。该值的**阈值**已由金总于 2026-09-16 定为 20,000,000 元，写入 `configs/universe.yaml`。 |
| `ret_20d.yaml` | `ret_20d` | 20 个交易日区间收益（窗口首尾收盘价之比减一）。窗口出自 spec §8.1 的「20/60/120-day returns」。 |
| `ret_60d.yaml` | `ret_60d` | 同上，窗口为 60。同一算法、不同参数，因此与 `ret_20d` 共用同一个实现类，`ret_` 前缀就是它们的契约。 |
| `proximity_52w_high.yaml` | `proximity_52w_high` | 最新收盘价 ÷ 窗口内最高价。窗口 `252` 个交易日即 52 周；「52 weeks」是设计原文（spec §8.1），把周换算成交易日这一步写在配置里，而不是藏在代码中。 |

## 约定

- 代码不提供任何默认参数值。缺少 `params.window` 会让因子构造失败，而不是退回一个隐含窗口。
- 窗口不完整（bar 数量不足，或窗口内任一 bar 缺所需字段）时输出 `NULL`，**不会**用更短的窗口凑一个数——那等于悄悄回答了另一个问题。
- 区间收益需要 `window + 1` 根 bar：区间跨越 `window` 个交易日间隔，因此需要 `window + 1` 个观测点才有起点。
- `frequency`、`direction`、`null_policy` 是自由字符串：设计文档没有枚举这三个词表，因此它们在此处显式声明，改词只改配置、不动代码。
- 因子假定输入数据已经过 Data Quality Gate；这条边界写在代码里，不在因子内重复实现一遍质量判定。
