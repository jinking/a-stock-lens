# Candidate Correctness & Product Query Upgrade 设计规格

**日期：** 2026-09-21  
**仓库：** `jinking/a-stock-lens`  
**审计基线 HEAD：** `e47fe65250f5adb05cac694ef8247ccdd1c5209c`

## 1. 目标

把当前已经“能生成 50 只 Candidate”的系统，升级为：

```text
生产 Candidate
= 资格正确
+ 策略上下文正确
+ Market Validation 输入完整
+ Signal 与策略一致
+ R2 Market Regime 证据完整
+ 血缘可复算
+ 独立产物测试能复核业务 verdict
```

正确性闭环前，`screen / qualified / stock` 继续可用；Candidate Publishing 必须 fail-closed。正确性闭环后，再开放 `astock candidates`、`astock today` 和 `GET /today`。

## 2. 当前已确认 P0/P1

### P0-1：Market Validation 丢失策略身份

当前生产调用没有传 `strategy_id`，而 `market_validation_stage()` 默认 `strategy_id="momentum"`，导致 Value / Growth / Quality / Dividend / GARP 也按 Momentum 趋势规则验证。

### P0-2：5 维验证没有完整输入

批准的五维：个股趋势、行业趋势、相对强弱、量价配合、流动性。当前生产实际只有个股趋势和流动性；行业超额、真实 benchmark 相对强弱、量价比没有完整接入。

### P0-3：R2 Market Regime 未完整落地

批准 R2 = Index Trend + Market Breadth + Extreme Volatility Check。当前 production 只算 `breadth_ratio`；宽度算不出时还用 `0.50` 兜底，违反 fail-closed。

### P0-4：Signal 丢失策略身份

`signal_stage()` 生产调用没有传 `strategy_id` / `strategy_by_symbol`，导致 `SignalContext.strategy_id=None`，同一标的先走 Momentum 规则，再走 Value/Dividend 规则。

### P0-5：风险 Signal 的 Candidate 语义未批准

CandidatePolicy 目前只 veto `MarketValidation.CONTRADICTED`。因此 `BREAKDOWN / TREND_WEAKEN / NO_SIGNAL` 都可能进入 Candidate。2026-09-19 审计材料中 50 只 Candidate 有 6 只 `BREAKDOWN`。

### P1-1：Candidate 血缘缺 Market/Signal 版本

`SnapshotLineage` 已有 `regime_version / signal_version`，但 `lineage_for()` 没完整装配；`MarketValidationResult` 还错误复用 `regime_version` 表达自己的版本。

### P1-2：独立产物测试没有复算业务 verdict

当前 artifact validator 能验证结构、引用、时点和基本 veto，但不能证明 `CONFIRMED / Signal / Regime` 真按批准规则产生。

### P1-3：历史快照重发绕开不可变约束

2026-09-19 首期 Candidate 发布通过移动旧 canonical snapshot 再重算同日 snapshot。以后不得再通过移动/删除旧 canonical 文件绕过 `SnapshotConflictError`。

## 3. 升级拆分

```text
Plan A — Candidate Correctness Safety Gate
Plan B — Market Evidence Completion
Plan C — Candidate / Today Query Experience
```

严格顺序：A 完成后先让 Candidate 进入 fail-closed 安全状态；B 完成并通过 Owner Gate 后再恢复 Candidate v2；最后执行 C。

## 4. 主策略上下文

V1 不新增跨策略综合分。对一只股票多个 qualified strategy，定义：

```text
primary_strategy_id
= qualified StrategyQualification 中 rank_percentile 最大者
  tie -> strategy_id 字典序升序
```

理由：当前 CandidatePolicy 第一排序键已经是 `best qualified rank_percentile`；不新增权重；不新增跨策略 score；Market Validation / Signal 获得确定上下文。Candidate 仍保留全部 qualified strategy evidence。

## 5. Market Evidence 完整性

Candidate v2 的 Market Validation 必需输入：

```text
ret_20d
proximity_52w_high
industry_excess_return_20d
relative_strength_60d
volume_ratio_5_20
avg_amount_20d
```

R2 Regime 必需：

```text
market_breadth_above_ma20
benchmark_trend
extreme_volatility
```

任一批准必需输入无法产生时，不得伪造 NEUTRAL / RANGE，Candidate Publishing BLOCKED。

当前批准材料仍没有精确定义：benchmark trend 的指数合成方法、extreme volatility 的数值阈值、如果现有 canonical industry 只提供二级行业时如何得到一级行业。Plan B 必须先生成真实数据决策包，Owner 明确批准后才能接 production。

## 6. Signal → Candidate 语义

当前不替 Owner 选择：

```text
BREAKDOWN 是否硬 veto
TREND_WEAKEN 是否降级或保留
NO_SIGNAL 是否允许进入 Candidate
```

Plan A 先保证这些状态不会被隐藏或静默变成 WATCH；Plan B 用真实数量形成影响报告。Owner 决策前 Candidate v2 Publishing = BLOCKED。

## 7. 历史快照不可变

同一 `(SnapshotKind, as_of)` 已存在不同内容时，继续抛 `SnapshotConflictError`。修正版不得移动旧 canonical snapshot 再重发。历史回放只写 `var/acceptance/` 或专用 review output；生产验收使用新的真实交易日。

## 8. 产品语义

```text
screen     = 策略评分排序
qualified  = Top10% + Absolute Qualification 双门槛
candidate  = 完整 Market/Signal 证据 + CandidatePolicy 后的研究候选
today      = 对正式 Candidate Snapshot 的只读摘要
```

禁止把 Candidate/Today 写成买入、强烈推荐、必涨或目标价。
