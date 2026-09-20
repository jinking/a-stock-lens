# Qualified → Candidate Upgrade 设计规格

**日期：** 2026-09-20  
**仓库：** `jinking/a-stock-lens`  
**审计基线 HEAD：** `fcaaa5d250ce5941726f433c006edaaf191adcf1`

## 当前状态

项目已具备：

```text
全市场 Raw
→ Research Universe（2,303）
→ FACTOR Snapshot
→ 6 StrategyResult
→ Strategy Screener
→ Qualification（Top10% + Absolute Rule）
```

2026-09-19 正式基线：

```text
Research Universe = 2,303
FACTOR Snapshot    = 120,192（5,008 × 24）
STRATEGY Snapshot  = 13,818（2,303 × 6）
```

资格审计：

| Strategy | Ranked | Top10 | Absolute Pass | Dual Pass |
| --- | ---: | ---: | ---: | ---: |
| Value | 1,578 | 158 | 320 | 132 |
| Growth | 2,302 | 231 | 445 | 151 |
| GARP | 849 | 85 | 196 | 61 |
| Quality | 1,697 | 170 | 324 | 111 |
| Dividend | 1,612 | 162 | 0 | 0 |
| Momentum | 2,281 | 229 | 303 | 166 |

Qualification 生产规则已恢复为所有者批准口径，配置非法时 fail-closed。

## 三层产品语义

```text
screen
= 策略排名

qualified
= 策略排名 + 已批准绝对质量门槛

candidate
= qualified + market validation + signal + CandidatePolicy
```

禁止把 `screen` 或 `qualified` 称为 Candidate、买入推荐或投资建议。

## 当前缺口

### 1. Qualified Stock 查询面缺失

资格结果已经能算，但只通过 `calibrate qualification-impact` 暴露。应新增日常查询：

```bash
astock qualified growth --as-of 2026-09-19 --top 20
```

以及：

```text
GET /qualifications/{strategy_id}/results
```

### 2. Dividend 数据缺口

`dividend_yield_ttm` 当前全池无 VALUE。已验证 neodata “统一估值查询”的股息率字段为空，但“分红派息详细”可返回每 10 股派息、状态、登记/除权日期。

本阶段只允许落地并规范化分红事件，禁止自算新 TTM 股息率，因为以下口径未获批：

```text
TTM 窗口
预案是否计入
按除权日/登记日/实施日归属
价格分母时点
特殊分红/送转处理
```

### 3. Market / Signal 尚未批准

Vocabulary 已存在：

```text
MarketRegime:
BULL / RANGE_UP / RANGE / RANGE_DOWN / BEAR

MarketValidation:
CONFIRMED / NEUTRAL / CONTRADICTED

Signal:
BREAKOUT / PULLBACK / TREND_CONTINUE /
TREND_WEAKEN / BREAKDOWN / NO_SIGNAL
```

但没有批准的输入和阈值。Agent 只能生成校准证据与决策包，不得实现 verdict。

### 4. Candidate 全局健康语义未决

Dividend 当前 dual-pass=0，而 `RepresentativeCandidatePolicy` 的代码只要求单只股票至少一个策略 qualified，并不要求六策略全部健康。

需要所有者以后选择：

```text
Mode A — Per-Strategy Degraded
某策略 unhealthy，只停该策略来源，其他策略仍可产生 Candidate。

Mode B — Global Readiness Gate
任一核心策略 unhealthy，整个 Candidate Publishing BLOCKED。
```

本升级包不替所有者选择。

## 本轮拆成三个独立计划

```text
Plan A — Qualified Stock Discovery
Plan B — Dividend Data Readiness
Plan C — Market & Signal Decision Readiness
```

Plan A 可直接上线。

Plan B 到“分红事件 + 覆盖审计 + 决策包”停止。

Plan C 到“Market/Signal 决策包”停止。

完成后必须 Owner STOP，不得顺手开启 Candidate Publishing。

## 工程治理

当前审计 HEAD 在 GitHub 上没有 CI workflow/status。本轮 Plan A 补最低限度 CI：

```text
pytest
ruff check
ruff format --check
mypy
```

## 最短产品路径

```text
Qualified 查询面
→ Dividend 数据准备
→ Market/Signal 决策证据
→ Owner Approval
→ Market/Signal Implementation（新计划）
→ Candidate Publishing（新计划）
→ Today/Web
```
