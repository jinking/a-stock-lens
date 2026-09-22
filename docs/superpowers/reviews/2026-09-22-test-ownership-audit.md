# 测试归属审计

## 目的与预算

本表指定规则的权威测试位置，避免相同规则在 Unit、Integration、API、Web 等层重复证明。

本任务仅建立归属记录，不增删或改写测试：

| 测试变化 | 预算 |
| --- | ---: |
| 新增 | 0 |
| 删除 | 0 |
| 净变化 | 0 |

## 权威测试归属

| 规则 / 契约 | 权威测试文件或层 | 上层测试责任 |
| --- | --- | --- |
| Trade Gate 受控词表、`TradeIntent`、`TradeRiskProposal` 不变量 | `tests/unit/test_trade_gate_models.py` | CLI/API 仅验证接线，不重复证明领域不变量 |
| Trade Profile YAML、固定阈值与权重总和 | `tests/unit/test_trade_gate_profiles.py` | Evaluation 仅消费解析后的 Profile，不重复验证配置解析 |
| Thesis Audit 阶段隔离、Adapter 输出与置信度调整 | `tests/unit/test_trade_gate_audit_adapter.py` | 更高层仅验证调用关系，不重复证明 Adapter 契约 |
| Qualification 配置校验 | `tests/unit/test_qualification_config.py` | Qualification 集成测试验证配置进入流程，不复测每种 YAML 校验失败形态 |
| Signal 检测行为 | `tests/unit/test_signal_detector.py` | Candidate/API 层只验证消费结果，不复测 Signal 分类规则 |
| Candidate 选择政策 | `tests/unit/test_candidate_selection_policy.py` | Artifact/API 层验证产物或读取边界，不重复计算选择排序规则 |
| Candidate 路由 | `tests/unit/test_candidate_routing.py` | 上层只验证路由调用接线，不重复证明策略路由规则 |
| Market Validation 规则 | `tests/unit/test_market_validator.py` | 下游验证消费状态，不复测各验证维度的规则 |
| API 路由及只读边界 | `tests/unit/test_api.py` | 不在 Web 中复制服务端领域计算规则 |
| 独立产物校验 | `tests/artifacts/` | 保持产物语义与跨快照校验，不把它们迁移为 API 测试的重复断言 |
| 公开契约 | `tests/contract/` | 保持对外签名与批准规则的契约证明，不由单元测试替代 |

## 保留项

以下测试集在本轮受保护，不作为复杂度删减目标：

- `tests/unit/test_qualification_config.py`
- `tests/unit/test_signal_detector.py`
- `tests/unit/test_candidate_selection_policy.py`
- `tests/unit/test_api.py`
- `tests/artifacts/`
- `tests/contract/`

本轮新增 Trade Gate 的三项权威测试均标记为 **KEEP**。模型不变量、Profile 配置契约、外部审计 Adapter 契约分别覆盖不同的失败类别；当前没有证据表明它们在多层之间重复证明。

## 第一轮有证据的测试收敛

| 变化 | 权威保留证明 | 收敛理由 |
| --- | --- | --- |
| Candidate policy 分数参数用例合并为一个最高分拒绝用例 | `test_score_does_not_override_a_rejecting_policy` | 原有三个用例仅改变分数；对拒绝策略而言最高分是最强反例，保留了核心不变量证明。 |
| 删除 Candidate routing 的纯函数自比较断言 | `test_a_qualified_verdict_routes_to_watch`、`test_an_unqualified_verdict_routes_to_ignore` | 同一调用结果与自身比较恒真，没有额外行为证明。 |
| Candidate routing 未使用分数的参数用例合并为一个 API 缺席断言 | `test_score_routing_api_is_absent` | 参数值没有进入被测代码；断言路由模块不存在分数决策 API 即覆盖此边界。 |
| 删除独立的缺失流动性测试 | `test_market_validator_missing_trend_or_liquidity_factors_raise`、`test_market_validator_multiple_missing_factors_reported` | 前者已逐一验证缺少 `avg_amount_20d` 时失败，后者验证错误中列出该因子。 |

当前仓库第一轮可证明的收敛为净减少 8 个 pytest 用例：计划目标写为减少 9 个，但本次核验的分数拒绝参数只有 3 项（计划预期 4 项）。不为追平计划数字删除其他仍有独立责任的测试。

## 并发功能约束

Westock bulk-bars 实现不得与本次复杂度重构并行，因为两者都会修改 CLI Provider 组合边界。CLI 拆分后，Westock 设计与实施计划必须把 `src/astock_lens/cli/runtime.py::_bulk_provider` 作为目标组合点，并单独声明 Test Delta Budget。

## 来源与限制

v2 计划要求保留“前一版计划”的所有 ownership 行，但前一版计划及既有 ownership 审计文件未出现在仓库或本次提供的下载目录中。本表不声称复原缺失内容；仅登记 v3 规格明确指定的 Trade Gate 归属、计划要求保护的测试集，以及本轮 Test Suite Audit 明确涉及的测试边界。发现前版记录后应合并其未覆盖且仍有效的行，不得据此删除本表的 **KEEP** 项。
