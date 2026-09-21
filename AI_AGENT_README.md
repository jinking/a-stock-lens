# AI Agent 执行入口 — Candidate Correctness Upgrade

仓库：`jinking/a-stock-lens`  
审计基线：`main @ e47fe65250f5adb05cac694ef8247ccdd1c5209c`

## 推荐执行方式

```text
superpowers:using-git-worktrees
→ superpowers:subagent-driven-development
```

每个 Task：

```text
RED
→ GREEN
→ fresh reviewer
→ commit
→ push
```

## 执行顺序

```text
Plan A — Candidate Correctness Safety Gate
↓
Plan B — Market Evidence Completion
↓
OWNER DECISION GATE
↓
Plan B 后半段生产接线 + 独立复算验收
↓
Plan C — Candidate / Today Query Experience
```

## 当前 P0

```text
1. 非 Momentum 策略被 production Market Validation 按 momentum 默认上下文处理
2. 5D Validation 实际缺行业、真实相对强弱、量价输入
3. R2 Regime 只接入 breadth，且缺失时伪造 0.50
4. Signal strategy_id=None 会跨 Momentum 与 Value/Dividend 规则混合命中
5. BREAKDOWN / TREND_WEAKEN / NO_SIGNAL 对 Candidate 发布语义未审批
```

## 强制禁止

```text
禁止修改 Qualification 阈值
禁止跨策略 weighted score
禁止移动旧 snapshot 绕过 SnapshotConflictError
禁止在 Owner Gate 前发布 Candidate v2
禁止为了让测试绿把缺失 evidence 变成 0 / False / NEUTRAL
```

## 文件

1. `docs/superpowers/plans/2026-09-21-candidate-correctness-safety-gate.md`
2. `docs/superpowers/plans/2026-09-21-market-evidence-completion.md`
3. `docs/superpowers/plans/2026-09-21-candidate-today-query-experience.md`
4. `docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md`
