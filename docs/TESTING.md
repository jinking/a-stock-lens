# 测试体系（V1）

## 1. 两条独立测试线

设计规格要求两条互不依赖的验证路径：

1. **代码测试**：验证实现本身；
2. **产物测试**：用独立 Artifact Validator 检查最终快照与 Candidate，而不是相信实现的自述。

## 2. 代码测试层次

| 层次 | 目录 | 目标 | 当前状态 |
| --- | --- | --- | --- |
| Unit | `tests/unit/` | 领域模型、时间规则、枚举，以及未来的 Factor / Universe / Strategy / Signal / 状态机 | 已建立 |
| Contract | `tests/contract/` | 扩展契约的公开签名与外部 schema 适配 | 已建立 |
| Integration | `tests/integration/` | Provider → Normalize → Factor → Strategy 链路 | 预留，尚无实现 |

## 3. 产物测试

`tests/artifacts/` 预留给独立 Artifact Validator。检查项：

- 快照完整性；
- Candidate 引用一致性；
- Factor / Strategy 版本是否齐全；
- score 范围与状态枚举合法性；
- `available_at <= as_of`；
- 因子引用是否存在。

产物测试失败要沉淀为回归用例。

## 4. Golden Dataset 与策略特征化

- `tests/fixtures/` 预留固定 30–50 只、覆盖多行业与边界情况的股票集合；策略变更必须先跑该集合。
- 策略特征化测试验证排序结果是否仍符合策略本意（例如 Quality 的头部标的在质量指标上整体更高）。具体判定指标 `Deferred`。

## 5. 怎么跑

```bash
uv run pytest                                                  # 全量
uv run pytest --cov=astock_lens --cov-report=term-missing      # 带覆盖率
uv run pytest tests/unit/test_domain_models.py -q              # 单文件
```

V1 没有设定覆盖率门限；bootstrap 阶段的覆盖以关键不变量（时间规则、缺失状态、契约签名）为准。

## 6. Deferred

- 集成测试与产物测试的具体样例：`Deferred`。
- Golden Dataset 清单：`Deferred`。
- 覆盖率门限：`Deferred`。
