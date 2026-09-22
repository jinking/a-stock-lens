# AI Agent 执行入口 — Production Candidate v2 + Web MVP

仓库：

```text
jinking/a-stock-lens
```

审计基线：

```text
main @ 794e8226d7c4bcdb9245fa1ff558b93e40198ac9
```

## 推荐 Superpowers 执行方式

```text
superpowers:using-git-worktrees
→ superpowers:subagent-driven-development
```

每个 Task：

```text
RED test
→ minimal GREEN
→ focused verification
→ fresh code review
→ commit
→ push
```

## 严格执行顺序

```text
Plan A — Production Candidate v2 Closure
↓
标准 astock daily 与 v2 沙箱语义一致
↓
新的 canonical Candidate v2 正式生产日
↓
MARKET_REGIME 正式 Snapshot
↓
独立产物审计 0 findings
↓
Plan A STOP GATE
↓
Plan B — Web MVP
↓
Today / Candidates / Stock Profile / Strategy Screener
↓
Web + Backend CI green
```

## 当前必须修的 P0

```text
1. CLI _run_daily() 未向 run_daily() 传 benchmark_bars / industry_by_symbol
2. MarketValidator 仍允许 industry / relative strength / volume ratio 缺失后继续判定
3. relative_strength 缺失时仍回退到股票自身 ret_60d
4. R2 Regime 仍允许只有 breadth 没有 000985.CSI trend
5. MARKET_REGIME 枚举存在，但 daily 不写正式 MARKET_REGIME Snapshot
6. Candidate v2 当前是 var/acceptance 沙箱验收，不应伪装成已经覆盖历史 canonical 2026-09-19
```

## 本轮绝对禁止

```text
禁止覆盖/移动历史 snapshot
禁止调整 Qualification 阈值
禁止调整 Strategy 权重
禁止新建跨策略综合分
禁止缺证据时填 0 / False / NEUTRAL
禁止 Web 直接读取 DuckDB/JSON
禁止把 Candidate 写成“买入推荐”
禁止做券商交易/自动下单
```

## 文件

总规格：

```text
docs/superpowers/specs/2026-09-21-production-candidate-v2-web-mvp-design.md
```

先执行：

```text
docs/superpowers/plans/2026-09-21-production-candidate-v2-closure.md
```

Plan A 全绿以后再执行：

```text
docs/superpowers/plans/2026-09-21-web-mvp.md
```

## 最终产品目标

浏览器：

```text
Today
→ 看今天市场状态和核心候选

Candidates
→ 看正式 20~50 只研究候选以及风险/信号

Stock Profile
→ 看某只股票为什么进入或没进入候选池

Strategy
→ 看单策略 Ranking 与 Qualified
```

CLI 继续保留并与 Web 并列：

```bash
astock today --as-of YYYY-MM-DD
astock candidates --as-of YYYY-MM-DD --top 20
astock stock SYMBOL --as-of YYYY-MM-DD
astock screen growth --as-of YYYY-MM-DD --top 20
astock qualified growth --as-of YYYY-MM-DD --top 20
```
