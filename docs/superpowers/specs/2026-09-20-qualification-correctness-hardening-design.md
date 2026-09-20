# Qualification Correctness Hardening 设计规格

**日期：** 2026-09-20
**状态：** P0 修复规格
**适用仓库：** `jinking/a-stock-lens`
**基线 HEAD（审计时）：** `44e3e15238a1bd3797210bcc256beb0a0b38da33`

## 1. 目标

修复当前 Candidate Qualification 生产规则与所有者审批记录之间的偏差，并把资格判定从“只能读取 Strategy 自己的评分因子”升级为“读取该股票完整 Factor 证据”。

本阶段只解决 Qualification 正确性，不实现：

- Market Regime；
- Market Validation；
- Signal Engine；
- Candidate Publishing；
- Today/Web。

完成后，Stock Discovery 仍可正常查询；Qualification 可以被可信地用于未来 Candidate，但 Candidate 继续 BLOCKED。

## 2. 审计确认的 P0 问题

### 2.1 Growth 生产规则与审批记录不一致

所有者审批：

```text
net_profit_parent_yoy >= 15%
revenue_yoy >= 5%
roe_ttm >= 8%
```

当前生产 YAML：

```text
net_profit_parent_yoy >= 15%
revenue_yoy >= 5%
net_profit_parent_cagr_3y >= 10%
```

`roe_ttm` 被未经审批地换成了 `net_profit_parent_cagr_3y`。

### 2.2 Dividend 同时存在“规则替换 + 单位错误”

所有者审批：

```text
dividend_yield_ttm >= 3.0%
0.10 <= dividend_payout_ttm <= 0.80
```

当前生产 YAML：

```text
0.10 <= dividend_paid_ratio <= 0.80
ocf_to_net_profit >= 0.50
```

其中 `dividend_paid_ratio` 的因子定义单位是 `%`，真实示例可为 `27.13` / `79.00`，因此当前 `0.10 ~ 0.80` 实际表示 `0.10% ~ 0.80%`，不是 `10% ~ 80%`。

### 2.3 GARP 生产规则与审批记录不一致

所有者审批：

```text
pe_ttm <= 35
net_profit_parent_yoy >= 15%
roe_ttm >= 10%
```

当前生产 YAML：

```text
pe_percentile <= 0.60
net_profit_parent_cagr_3y >= 15%
roe_ttm >= 10%
```

同时 `pe_percentile` 原始单位为 `%`，当前 `0.60` 不是 `60%`，而是 `0.60%`。

### 2.4 Qualification 架构迫使 Agent 替换业务指标

当前：

```text
AbsoluteQualificationRule.evaluate(result: StrategyResult)
```

只能从：

```text
StrategyResult.factor_snapshot
```

取值。

而 `factor_snapshot` 表达的是策略评分因子，不是资格规则全部证据。

因此必须分离：

```text
Strategy scoring evidence
Qualification evidence
```

禁止为了接口方便修改所有者批准的业务因子。

### 2.5 Qualification Loader 当前 fail-open 风险

当前实现允许：

```yaml
thresholds: {}
```

并会产生：

```text
risks = []
passed = True
```

即“空绝对规则自动通过”。

同时当前 loader 缺少以下强校验：

- 空 thresholds；
- threshold 同时无 min/max；
- min > max；
- 未知 Factor；
- YAML `strategy_id` 与目标文件策略不一致；
- 空 version；
- 非有限数值。

生产资格规则必须 fail-closed。

## 3. 所有者审批规则：唯一修复目标

### Value

```yaml
pe_ttm:
  max: 25.0
pb:
  max: 2.5
roe_ttm:
  min: 5.0
```

非正 PE/PB 已由 Factor 层判定 `NOT_APPLICABLE`，Qualification 不重复创造另一套“正数”语义。

### Growth

```yaml
net_profit_parent_yoy:
  min: 15.0
revenue_yoy:
  min: 5.0
roe_ttm:
  min: 8.0
```

### GARP

```yaml
pe_ttm:
  max: 35.0
net_profit_parent_yoy:
  min: 15.0
roe_ttm:
  min: 10.0
```

### Quality

```yaml
roe_ttm:
  min: 12.0
gross_margin:
  min: 20.0
debt_to_asset:
  max: 65.0
```

### Dividend

```yaml
dividend_yield_ttm:
  min: 3.0
dividend_payout_ttm:
  min: 0.10
  max: 0.80
```

注意：

```text
dividend_yield_ttm 单位 = %
dividend_payout_ttm 单位 = ratio
```

不得改用 `dividend_paid_ratio` 代替批准指标。

### Momentum

Qualification：

```yaml
proximity_52w_high:
  min: 0.80
```

所有者审批记录中的“流动性符合研究池要求”视为上游 Research Universe 准入条件，不在 Qualification 中临时发明第二个动态阈值。

当前 canonical Universe 已有：

```text
min_average_turnover_20d = 150,000,000
```

本轮只用测试确认 Momentum 进入 Qualification 前已经经过该 Universe Gate。

如果未来明确要求“高于研究池横截面平均成交额”，必须单独重新审批。

## 4. 新的 Qualification Evidence 边界

新增：

```python
class QualificationContext(DomainRecord):
    strategy_result: StrategyResult
    factors: tuple[FactorResult, ...]
```

语义：

```text
strategy_result = 该策略的 score / rank / eligibility
factors         = 该股票在正式 FACTOR Snapshot 中的完整 FactorResult 集合
```

新的调用链：

```text
FACTOR Snapshot
       │
       ├──────────────┐
       ▼              ▼
Strategy Scanner   QualificationContext
       │              │
       ▼              ▼
StrategyResult   AbsoluteQualificationRule
       │              │
       └──────┬───────┘
              ▼
      StrategyQualification
```

禁止把完整 Factor 集塞回 `StrategyResult.factor_snapshot`。

## 5. Fail-Closed 配置模型

新增严格配置模型，并拒绝：

```text
thresholds == {}
min is None and max is None
min > max
NaN / inf
unknown factor
strategy_id mismatch
blank version
malformed threshold mapping
```

错误类型：

```python
class QualificationConfigInvalid(ValueError):
    ...
```

文件缺失仍使用：

```python
QualificationRuleNotConfigured
```

这样 daily 可以区分：

```text
未配置 → BLOCKED
配置损坏 → FAILED loudly
```

禁止把“配置错误”降级成“未配置”。

## 6. 生产规则 Contract Test

新增：

```text
tests/contract/test_qualification_production_rules.py
```

锁死：

- 六策略都存在；
- exact factor names；
- exact threshold values；
- exact version；
- Dividend 单位语义；
- Momentum 只含 `proximity_52w_high`，流动性由 Universe Gate 提供。

## 7. 全市场 Qualification Impact Audit

新增只读审计：

```bash
astock calibrate qualification-impact   --as-of 2026-09-19   --output-dir var/calibration
```

读取：

```text
正式 FACTOR Snapshot
正式 STRATEGY Snapshot
生产 Qualification configs
```

不重算、不写 Snapshot。

每策略输出：

```text
eligible count
ranked count
Top-10% count
absolute-pass count
dual-pass count
dual-pass ratio
top failure reasons
qualified symbols
boundary samples
```

## 8. 文档修复

同步：

- `docs/ROADMAP.md`
- `docs/REMAINING_PRODUCT_BLOCKERS.md`
- `docs/REVIEW_NOTES.md`
- `.workbuddy/memory/2026-09-20.md`

正确状态：

```text
P1 valuation: COMPLETE
P2 owner approval: COMPLETE
P2 implementation: REPAIRED + AUDITED
P3 Market Regime/Validation/Signal: BLOCKED
P4 Candidate Publishing: BLOCKED
```

## 9. 完成定义

正确完成语句：

> Production Qualification now matches the owner-approved rules, reads complete per-symbol Factor evidence, fails closed on invalid configuration, and has been audited against the formal full research baseline. Candidate publishing remains blocked by Market Regime / Market Validation / Signal and Candidate Policy wiring.

不得报告：

> Candidate 推荐系统已经完成。
