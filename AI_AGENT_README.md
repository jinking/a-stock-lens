# AI Agent 执行入口

仓库：`jinking/a-stock-lens`
基线：`main @ fcaaa5d`

推荐执行方式：

```text
superpowers:subagent-driven-development
```

## 执行顺序

### 1. 先执行 Plan A

`docs/superpowers/plans/2026-09-20-qualified-stock-discovery-implementation-plan.md`

目标：

```text
让用户直接查询 Top10% + Absolute Qualification 双门槛通过的股票
```

这是当前最短的产品价值路径，可以直接实施并上线。

### 2. 再执行 Plan B

`docs/superpowers/plans/2026-09-20-dividend-data-readiness-implementation-plan.md`

目标：

```text
把 neodata “分红派息详细”落成规范事件数据，并生成覆盖/口径决策包
```

强制 STOP：

```text
禁止在本计划内计算新的 dividend_yield_ttm
禁止修改 Dividend Qualification
```

### 3. 最后执行 Plan C

`docs/superpowers/plans/2026-09-20-market-signal-readiness-implementation-plan.md`

目标：

```text
为 Market Regime / Market Validation / Signal 生成可审批证据
```

强制 STOP：

```text
禁止自行决定阈值
禁止输出真实 MarketValidation/Signal verdict
禁止 Candidate Publishing
```

## 每个 Task 的执行纪律

```text
RED test
→ minimal implementation
→ focused tests
→ reviewer
→ commit
→ push
```

不要把三个计划合成一个大提交。

## 本轮绝对禁止

- `RepresentativeCandidatePolicy` 生产接线
- CANDIDATE Snapshot
- `astock today`
- Web UI
- 跨策略 global score
- 把 `qualified` 写成“推荐/买入”
- 修改所有者批准的六策略资格阈值

## 最终交付

依次返回：

```text
Plan A Completion Report
Plan B Completion Report
Plan C Completion Report
```

然后停止，等待 Owner 对 Dividend TTM 定义、Market/Signal 规则和 Candidate readiness Mode A/B 做明确决策。
