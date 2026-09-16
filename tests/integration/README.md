# tests/integration

预留目录：用于 Provider → Normalize → Factor → Strategy 的链路级测试。

当前没有任何测试。原因是没有可测的实现：Provider、Normalizer、Factor 与 Strategy 都还只有契约，没有算法。

该层次建立后应覆盖：

- 单次批量同步到可计算状态的完整链路；
- 时点正确性：`available_at <= as_of` 在链路中不被绕过；
- 数据质量失败时链路显式失败或降级，而不是静默产出结果。

不允许为了填充目录而写假的集成测试。
