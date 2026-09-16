# Factor configuration

每个文件定义一个 Factor。**参数写在这里，算法写在代码里**（`docs/ARCHITECTURE.md` §8.3：算法写代码，权重与阈值写 YAML，不设计通用 YAML DSL）。

Factor 只产出客观原始值；策略解释与评分属于策略层。

## 已定义

| 文件 | 因子 | 说明 |
| --- | --- | --- |
| `avg_amount_20d.yaml` | `avg_amount_20d` | 日成交额的滚动均值。窗口 `20` 不是此处新定的——设计 spec §6 与 `docs/ARCHITECTURE.md` §6 都把「20 日平均成交额」写为 Universe 的流动性口径。该值的**阈值**仍然 deferred：`configs/universe.yaml` 的 `min_average_turnover_20d` 保持 `null`。 |

## 约定

- 代码不提供任何默认参数值。缺少 `params.window` 会让因子构造失败，而不是退回一个隐含窗口。
- 窗口不完整（bar 数量不足，或窗口内任一 bar 缺 `amount`）时输出 `NULL`，**不会**用更短的窗口凑一个数——那等于悄悄回答了另一个问题。
- `frequency`、`direction`、`null_policy` 是自由字符串：设计文档没有枚举这三个词表，因此它们在此处显式声明，改词只改配置、不动代码。
- 因子假定输入数据已经过 Data Quality Gate；这条边界写在代码里，不在因子内重复实现一遍质量判定。
