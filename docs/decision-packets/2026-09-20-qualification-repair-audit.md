# 六策略资格规则全研究池修复审计（Qualification Repair Audit）

**日期：** 2026-09-20
**状态：** 修复完成并审计（REPAIRED + AUDITED）
**审计时点：** `as_of = 2026-09-19`（`2026-09-19T15:00:00+08:00`）
**权威依据：**
- `docs/superpowers/specs/2026-09-20-qualification-correctness-hardening-design.md`
- `docs/superpowers/plans/2026-09-20-qualification-correctness-hardening-implementation-plan.md`

> **结论：** 生产资格规则已与所有者批准口径逐字一致；资格判定改为读取该股票**完整 Factor 证据**；非法配置**失败关闭**；并已在正式全研究池基线上审计。**正式 Candidate 发布仍被后续 Market/Signal/Candidate 门禁阻断。**

---

## 1. 审计基线（读实际存储记录，未套用旧数字）

| 项目 | 实际值 | 说明 |
| --- | --- | --- |
| Research Universe | **2,303** | 研究池口径 |
| FactorResult（FACTOR 快照） | **120,192** | **全市场**口径 `5,008 × 24`（旧计划文本中的 `55,272` 为研究池投影 `2,303 × 24`，正式快照实为全市场） |
| StrategyResult（STRATEGY 快照） | **13,818** | 研究池口径 `2,303 × 6` |
| 正式快照 | `data/snapshots/{FACTOR,UNIVERSE,STRATEGY}/2026-09-19.json` | mtime `09:49:45 / 09:49:46 / 09:49:58` |
| CANDIDATE 快照 | **不存在**（`data/snapshots/CANDIDATE/` 目录缺失） | 无候选被发布 |

---

## 2. 旧缺陷（修复前生产 YAML 与所有者批准口径的偏差）

| 策略 | 旧生产 YAML | 批准口径 | 缺陷类型 |
| --- | --- | --- | --- |
| Value | `pe_ttm {min:0.0001,max:25}`、`pb {min:0.0001,max:2.5}`、`roe_ttm min5` | `pe_ttm max25`、`pb max2.5`、`roe_ttm min5` | 未经审批的额外正数下限 |
| Growth | `net_profit_parent_yoy min15`、`revenue_yoy min5`、**`net_profit_parent_cagr_3y min10`** | `net_profit_parent_yoy min15`、`revenue_yoy min5`、**`roe_ttm min8`** | 指标替换（`roe_ttm` 被换成 `net_profit_parent_cagr_3y`） |
| GARP | **`pe_percentile max0.6`**、**`net_profit_parent_cagr_3y min15`**、`roe_ttm min10` | **`pe_ttm max35`**、**`net_profit_parent_yoy min15`**、`roe_ttm min10` | 指标替换 + 单位错误（`pe_percentile` 单位 `%`，`0.60` 实为 `0.60%` 而非 `60%`） |
| Dividend | **`dividend_paid_ratio {min:0.10,max:0.80}`**、**`ocf_to_net_profit min0.50`** | **`dividend_yield_ttm min3.0`**、**`dividend_payout_ttm {min:0.10,max:0.80}`** | 指标替换 + 单位错误（`dividend_paid_ratio` 单位 `%`，真实值可为 `27.13`/`79.00`，`0.10~0.80` 实为 `0.10%~0.80%`） |
| Quality | `roe_ttm min12`、`gross_margin min20`、`debt_to_asset max65` | 同 | 无（一致） |
| Momentum | `proximity_52w_high min0.80` | 同 | 无（一致）；流动性由上游 Universe `min_average_turnover_20d=150,000,000` 承担 |

架构性缺陷：`AbsoluteQualificationRule.evaluate(result: StrategyResult)` 只能读 `StrategyResult.factor_snapshot`（策略评分因子），无法读取获批但非评分用途的因子（如 Growth 的 `roe_ttm`），从而**迫使**实现者替换业务指标。

---

## 3. 修正后的规则（当前生产 YAML，逐字）

```yaml
# value.yaml
thresholds: {pe_ttm: {max: 25.0}, pb: {max: 2.5}, roe_ttm: {min: 5.0}}
# growth.yaml
thresholds: {net_profit_parent_yoy: {min: 15.0}, revenue_yoy: {min: 5.0}, roe_ttm: {min: 8.0}}
# garp.yaml
thresholds: {pe_ttm: {max: 35.0}, net_profit_parent_yoy: {min: 15.0}, roe_ttm: {min: 10.0}}
# quality.yaml
thresholds: {roe_ttm: {min: 12.0}, gross_margin: {min: 20.0}, debt_to_asset: {max: 65.0}}
# dividend.yaml
thresholds: {dividend_yield_ttm: {min: 3.0}, dividend_payout_ttm: {min: 0.10, max: 0.80}}
# momentum.yaml
thresholds: {proximity_52w_high: {min: 0.80}}
```

契约测试 `tests/contract/test_qualification_production_rules.py`：**8 passed**（修复前 RED 为 5 failed / 3 passed）。

---

## 4. 全研究池实际通过数（`astock calibrate qualification-impact --as-of 2026-09-19`）

| strategy | eligible | ranked | top10 | absolute-pass | dual-pass | dual-pass ÷ ranked | top5 失败原因（因子=计数） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| value | 1578 | 1578 | 158 | 320 | 132 | 0.0837 | pb=926, pe_ttm=854, roe_ttm=652 |
| growth | 2302 | 2302 | 231 | 445 | 151 | 0.0656 | roe_ttm=1459, net_profit_parent_yoy=1182, revenue_yoy=901 |
| garp | 849 | 849 | 85 | 196 | 61 | 0.0718 | roe_ttm=428, pe_ttm=385, net_profit_parent_yoy=345 |
| quality | 1697 | 1697 | 170 | 324 | 111 | 0.0654 | roe_ttm=1245, gross_margin=532, debt_to_asset=235 |
| dividend | 1612 | 1612 | 162 | **0** | **0** | **0.0000** | dividend_yield_ttm=1612, dividend_payout_ttm=318 |
| momentum | 2281 | 2281 | 229 | 303 | 166 | 0.0728 | proximity_52w_high=1978 |

---

## 5. 安全复核（触发 `dual_pass_count == 0`）

**触发项：** `dividend` 的 `dual_pass_count == 0`（触发计划 Task 7 Step 4 的 `dual_pass_count == 0` 触发器）。

### 5.1 根因：上游股息率数据缺口（**不是阈值错误、不是单位错配**）

1. **FACTOR 快照**中 `dividend_yield_ttm` 的 DataStatus 分布：`VALUE=0`、`NULL=2241`、`NOT_APPLICABLE=2767`（合计 5008）。因子 `unit = "%"`。
   对照 `dividend_payout_ttm`：`VALUE=1622`、`NULL=415`、`NOT_APPLICABLE=2971`；其中 `VALUE` 落在 `[0.10, 0.80]` 的有 **1309** 只。
2. **原始来源** `data/raw/neodata/valuation/2026-09-19.csv`（neodata「统一估值查询」，**2241** 只标的）的 markdown 时序表里**存在**「静态股息率（%）」「滚动股息率（%）」两列，但：
   - 总时间序列单元格 **24,619** 个；
   - 两列**非空值均为 0 个**（全部 `--`）。
3. 因此 `dividend` 的 1612 只 ranked 全部栽在 `dividend_yield_ttm` 缺失上 → `absolute_pass=0` → `dual_pass=0`。

**口径裁定：** 批准阈值 `dividend_yield_ttm >= 3.0`（单位 `%`，与因子定义 `description: Trailing dividend yield, in percent.` 及 `unit=%` 一致）被**正确地**应用了。这是**上游数据缺口**，不是本次修复的缺陷。**严禁修改已批准阈值**（计划 Mandatory STOP Gate）。

### 5.2 边界样本（≥20 只，读 FACTOR 快照的 status + raw_value）

抽样 = 审计 `closest_absolute_fail_symbols`（5）+ dividend-eligible 前若干，共 22 只：

| symbol | dividend_yield_ttm | raw | dividend_payout_ttm | raw |
| --- | --- | --- | --- | --- |
| 300042.SZ | NULL | None | VALUE | 0.1001 |
| 600519.SH | NULL | None | VALUE | 0.7986 |
| 000801.SZ | NULL | None | VALUE | 0.0997 |
| 688516.SH | NULL | None | VALUE | 0.7971 |
| 600508.SH | NULL | None | VALUE | 0.7965 |
| 000001.SZ | NULL | None | VALUE | 0.2719 |
| 000019.SZ | NULL | None | VALUE | 0.7724 |
| 000021.SZ | NULL | None | VALUE | 0.2822 |
| 000025.SZ | NULL | None | VALUE | 0.3303 |
| 000026.SZ | NULL | None | VALUE | 0.4621 |
| 000027.SZ | NULL | None | VALUE | 0.3308 |
| 000034.SZ | NULL | None | VALUE | 0.0895 |
| 000037.SZ | NULL | None | VALUE | 0.0952 |
| 000060.SZ | NULL | None | VALUE | 0.1764 |
| 000061.SZ | NULL | None | VALUE | 0.2735 |
| 000062.SZ | NULL | None | VALUE | 0.5071 |
| 000063.SZ | NULL | None | VALUE | 0.5899 |
| 000065.SZ | NULL | None | VALUE | 0.2149 |
| 000100.SZ | NULL | None | VALUE | 0.2906 |
| 000155.SZ | NULL | None | VALUE | 0.5318 |
| 000157.SZ | NULL | None | VALUE | 0.4122 |
| 000158.SZ | NULL | None | VALUE | 3.3089 |

统计：抽样 22 只中 `dividend_yield_ttm` 的 `VALUE=0`；`dividend_payout_ttm` 落在 `[0.10, 0.80]` 的有 **18** 只。即分红支付率这一路数据可用，唯一致命缺口是股息率。

### 5.3 单位 / DataStatus 核实

- `configs/factors/dividend_yield_ttm.yaml`：`description: Trailing dividend yield, in percent.`、`null_policy: NULL_UNLESS_THE_METRIC_HAS_A_PUBLISHED_VALUE`。
- FACTOR 快照中 `dividend_yield_ttm` 的 `unit = "%"`（5008/5008）；`dividend_payout_ttm` 的 `unit = "x"`（ratio 值域）。
- 结论：`dividend_yield_ttm >= 3.0` 的 `%` 语义与来源一致；数据缺失被如实记为 `NULL`（未静默填 0）。

### 5.4 结案

**规则正确、数据缺失。** 需所有者决定：补数据源（neodata 股息率链路）或重新审批 Dividend 门槛。本审计**不改任何阈值**。

---

## 6. 三个被修策略的直接验证

### 6.1 Growth（`net_profit_parent_yoy>=15`、`revenue_yoy>=5`、`roe_ttm>=8`）

抽取 `qualified_symbols` 前 5 只（读 FACTOR 快照 raw_value）：

| symbol | net_profit_parent_yoy | revenue_yoy | roe_ttm | 满足 |
| --- | --- | --- | --- | --- |
| 000426.SZ | 184.4196 | 73.1308 | 27.486 | ✅ |
| 000506.SZ | 407.4399 | 85.1313 | 37.803 | ✅ |
| 000567.SZ | 815.7659 | 452.3419 | 22.7988 | ✅ |
| 000657.SZ | 280.5341 | 108.5139 | 24.923 | ✅ |
| 000688.SZ | 16.1259 | 55.718 | 35.52 | ✅ |

证明 Growth 资格**确实使用了 `roe_ttm`**（该因子不在 Growth 策略评分快照内，只能来自完整 Factor 证据）。

### 6.2 GARP（`pe_ttm<=35`、`net_profit_parent_yoy>=15`、`roe_ttm>=10`）

| symbol | pe_ttm | net_profit_parent_yoy | roe_ttm | 满足 |
| --- | --- | --- | --- | --- |
| 000426.SZ | 19.86 | 184.4196 | 27.486 | ✅ |
| 000526.SZ | 16.14 | 30.8503 | 21.4963 | ✅ |
| 000567.SZ | 7.54 | 815.7659 | 22.7988 | ✅ |
| 000612.SZ | 7.7 | 129.5793 | 21.8075 | ✅ |
| 000680.SZ | 10.66 | 19.0293 | 19.7874 | ✅ |

GARP 的绝对判定阈值键 `= {pe_ttm, net_profit_parent_yoy, roe_ttm}`，**不含 `pe_percentile`** → `pe_percentile` 不参与绝对判定。

### 6.3 Dividend（合格样本为空）

- `qualified_symbols = []`、`absolute_pass_count = 0`、`dual_pass_count = 0`。原因见第 5 节（上游股息率缺失）。
- 未合格样本中 `dividend_payout_ttm` 达标（`[0.10,0.80]`）的有 **1309/1622**，但 `dividend_yield_ttm` 缺失 → 无法通过。
- Dividend 的绝对判定阈值键 `= {dividend_yield_ttm, dividend_payout_ttm}`，**不含 `dividend_paid_ratio`** → 旧单位错误因子**不再**参与判定。

---

## 7. 无 Candidate 被发布的证明

1. `astock calibrate qualification-impact` 命令**只读**：只 `read` FACTOR/STRATEGY 快照、只写 `--output-dir` 下的两个报告文件；不调用 Provider、不重算、不写 Snapshot/Watchlist/Job/Candidate（`tests/integration/test_qualification_impact_cli.py::test_qualification_impact_cli_is_read_only` 以执行前后 Snapshot/Watchlist/Job 指纹逐字节相等证明）。
2. `data/snapshots/CANDIDATE/` 目录**不存在** → 2026-09-19 无任何 CANDIDATE 快照。
3. `astock daily --as-of 2026-09-19 --allow-incomplete`：`BUILD_CANDIDATES` 仍 `BLOCKED`（真实下游：DETECT_REGIME / MARKET_VALIDATE / RUN_SIGNALS 未实现 + Candidate Policy Deferred），`candidates: 0`，`5 blocked, 0 failed`。

---

## 8. "不改策略权重 / 不改 FACTOR·STRATEGY 产出"的独立佐证

`SnapshotStore.write` 的语义是"内容一致则**幂等不写**、内容不同则抛 `SnapshotConflictError`"。本次修复后重跑 `astock daily --as-of 2026-09-19` 时，FACTOR / UNIVERSE / STRATEGY 三个正式快照**没有冲突、也没有被重写**——`data/snapshots/{FACTOR,UNIVERSE,STRATEGY}/2026-09-19.json` 的 mtime 仍停留在 `09:49:45 / 09:49:46 / 09:49:58`。这说明重跑产出与正式快照**逐字节一致**，即本次资格规则修复**没有改变 FACTOR / STRATEGY 产出**（不改策略权重的独立佐证）。

---

## 9. 修复涉及的关键提交

| 提交 | 说明 |
| --- | --- |
| `0686d31` | 测试：锁定所有者批准的六策略资格规则 |
| `540ec0b` | 资格：分离策略评分证据与绝对资格证据 |
| `de3f18b` | 资格：生产规则配置改为严格失败关闭 |
| `3b28a6e` | 修复：恢复所有者批准的六策略资格门槛 |
| `674baef` | 修复：堵住资格配置空值与未知阈值键的失败关闭绕过 |
| `5182673` | 管线：资格判定改用完整股票因子证据 |
| `ba0430d` | 校准：增加六策略资格规则只读影响审计 |

产物：
- `var/calibration/qualification-repair/qualification-impact-2026-09-19.json`
- `var/calibration/qualification-repair/qualification-impact-2026-09-19.md`

---

## 10. 剩余阻塞（本审计不解除）

本次修复只解决 Qualification 正确性。正式 Candidate 发布仍被以下门禁阻断：

- **P3** Market Regime / Market Validation / Signal 未实现（阈值未批准）；
- **P4** `RepresentativeCandidatePolicy` 生产接线与 CANDIDATE 发布未授权；
- **新增（上游数据）** Dividend `dividend_yield_ttm` 全池缺失，需所有者决定补数据源或重新审批 Dividend 门槛（见 `docs/REMAINING_PRODUCT_BLOCKERS.md`）。
