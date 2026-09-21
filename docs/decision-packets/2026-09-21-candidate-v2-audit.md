# Candidate v2 全链路生产验收与独立产物审计报告（2026-09-21）

- **审计基准日期 (as_of)**: `2026-09-19T15:00:00+08:00`
- **审计执行时间**: `2026-09-21`
- **审计依据**: 
  - `docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md`
  - `docs/superpowers/plans/2026-09-21-market-evidence-completion.md` (Task 9)
  - `docs/decision-packets/2026-09-21-candidate-v2-market-evidence-decision.md` (所有者批复推荐方案)
- **独立审计器**: `tests/artifacts/validator.py`（纯标准库实现，零导入生产领域模块）
- **沙箱产物位置**: `var/acceptance/candidate-v2-20260921/`（严守历史快照不可变铁律，未改动 `data/snapshots/`）

---

## 一、审计执行结论（Executive Summary）

1. **审批决策 100% 落实与闭环**：
   - 落实项目所有者签署的 **A1 / B3 / C1 / D1 / E1 / F1** 决策矩阵；
   - 市场环境（R2 Regime）接通中证全指均线比率（`ma_20 / ma_60`）；
   - 市场验证（5D Validation）接通流动性、均线趋势、申万二级行业超额、基准超额与成交量比五维输入；
   - 候选生成（Candidate Selection）严格按各合格标的主策略（`primary_strategy_id`）独立选择，消除跨策略加权排序混淆。

2. **独立第三方产物审查全量零缺陷（0 Findings）**：
   - 单快照规范审查（`validate_snapshot`）：
     - `UNIVERSE`: **0 findings**
     - `FACTOR`: **0 findings**
     - `STRATEGY`: **0 findings**
     - `CANDIDATE`: **0 findings**（含独立复算决策 D1 否决、E1 预警与 5D 流动性底线）
   - 跨快照引用与血缘一致性（`validate_snapshot_set`）：**0 findings**（所有 50 只候选引用的策略结果、因子版本与时点在同日快照中 100% 闭环）
   - 全链路调度运行记录（`validate_job_manifest`）：**0 findings**（11 阶段均有规范记录，阻断原因显式透明）

3. **快照不可变性原则得到严谨恪守**：
   - 历史标准快照 `data/snapshots/CANDIDATE/2026-09-19.json` 保持原样，绝不重写或移动历史生产快照；
   - 本次全流程生产验收完整运行在隔离沙箱 `var/acceptance/candidate-v2-20260921/` 中，产物按 `.gitignore` 规则隔离，不污染生产代码库。

---

## 二、生产日常调度管线执行清单（Job Manifest）

沙箱执行生成的 `jobs/2026-09-19.json` 全流程 11 阶段清单如下：

| 调度阶段 (JobStage) | 执行状态 | 处理行数 (In -> Out) | 执行说明 |
| :--- | :---: | :---: | :--- |
| `SYNC_DATA` | SKIPPED | - | 规范跳过（已预先存在本地数据） |
| `NORMALIZE` | SUCCEEDED | 1,675,723 -> 1,675,723 | 涵盖日K线、财务报表、估值及分红数据 |
| `COMPUTE_FACTORS` | SUCCEEDED | 5,008 -> 120,192 | 24 个因子计算，含除权日口径真实 TTM 股息率 |
| `BUILD_UNIVERSE` | SUCCEEDED | 5,565 -> 2,303 | 2,303 只研究池标的，申万二级全覆盖 |
| `RUN_STRATEGIES` | SUCCEEDED | 2,303 -> 13,818 | 六策略计算评分与百分位横截面排名 |
| `DETECT_REGIME` | SUCCEEDED | 1,675,723 -> 1 | 判定为 `RANGE_DOWN`（均线比率 0.985，空头震荡） |
| `MARKET_VALIDATE` | SUCCEEDED | 512 -> 512 | 合格标的 5 维验证：Confirmed=150, Contradicted=23 (否决) |
| `RUN_SIGNALS` | SUCCEEDED | 512 -> 512 | 合格标的信号检测：激活 208 只 |
| `BUILD_CANDIDATES` | SUCCEEDED | 13,818 -> 50 | 经 D1 否决与代表性择优，生成 50 只 Candidate v2 |
| `UPDATE_WATCHLIST` | BLOCKED | - | 依法保持阻塞（自选股流转严格由用户主动发起） |
| `GENERATE_DAILY_SNAPSHOT` | SUCCEEDED | - -> 4 | 成功生成四大快照（FACTOR, UNIVERSE, STRATEGY, CANDIDATE） |

---

## 三、Candidate v1 对比 Candidate v2 实证研究（Research Evidence）

在完全相同的行情与财务数据切片下，对比历史 Candidate v1 与本次 Candidate v2 的实测差异：

### 3.1 标的集合置换分析

- **总候选标的数**：v1 为 50 只，v2 为 50 只（均达到政策软上限 50 只）；
- **稳定留存标的**：**42 只**（留存率 84.0%）；
- **置换变动标的**：**8 只**。

#### 被剔除标的清单（8 只）与原因分析：
| 股票代码 | 股票简称 | v1 信号 | v1 市场验证 | v2 剔除原因 |
| :--- | :--- | :---: | :---: | :--- |
| `000973.SZ` | 佛塑科技 | `BREAKDOWN` | `NEUTRAL` | **决策 D1 一票否决**（严重破位，严禁发布） |
| `300009.SZ` | 安科生物 | `BREAKDOWN` | `NEUTRAL` | **决策 D1 一票否决**（严重破位，严禁发布） |
| `300972.SZ` | 万辰集团 | `BREAKDOWN` | `NEUTRAL` | **决策 D1 一票否决**（严重破位，严禁发布） |
| `688266.SH` | 泽璟制药 | `BREAKDOWN` | `NEUTRAL` | **决策 D1 一票否决**（严重破位，严禁发布） |
| `688336.SH` | 三生国健 | `BREAKDOWN` | `NEUTRAL` | **决策 D1 一票否决**（严重破位，严禁发布） |
| `688578.SH` | 艾力斯 | `BREAKDOWN` | `NEUTRAL` | **决策 D1 一票否决**（严重破位，严禁发布） |
| `000426.SZ` | 兴业银锡 | `NO_SIGNAL` | `NEUTRAL` | 策略代表性配额优化后被同策略更高分标的替代 |
| `300191.SZ` | 潜能恒信 | `NO_SIGNAL` | `NEUTRAL` | 策略代表性配额优化后被同策略更高分标的替代 |

> **关键实证结论**：v1 中误入的 **6 只严重破位（BREAKDOWN）股票被 100% 依法拦截剔除**，彻底杜绝了将技术面严重破位的股票作为研究候选推送给用户的重大合规风险。

#### 新增入选标的清单（8 只）：
| 股票代码 | 主策略归属 | v2 信号 | v2 市场验证 | 说明 |
| :--- | :---: | :---: | :---: | :--- |
| `001309.SZ` | `growth` | `NO_SIGNAL` | `NEUTRAL` | 替代被否决标的，稳健补充成长策略代表性标的 |
| `002289.SZ` | `growth` | `NO_SIGNAL` | `NEUTRAL` | 替代被否决标的，稳健补充成长策略代表性标的 |
| `002842.SZ` | `growth` | `NO_SIGNAL` | `NEUTRAL` | 替代被否决标的，稳健补充成长策略代表性标的 |
| `300475.SZ` | `garp` | `NO_SIGNAL` | `NEUTRAL` | 补充 GARP 策略代表性底仓 |
| `301308.SZ` | `growth` | `NO_SIGNAL` | `NEUTRAL` | 替代被否决标的，稳健补充成长策略代表性标的 |
| `603986.SH` | `growth` | `NO_SIGNAL` | `NEUTRAL` | 替代被否决标的，稳健补充成长策略代表性标的 |
| `688110.SH` | `growth` | `NO_SIGNAL` | `NEUTRAL` | 替代被否决标的，稳健补充成长策略代表性标的 |
| `688525.SH` | `growth` | `NO_SIGNAL` | `NEUTRAL` | 替代被否决标的，稳健补充成长策略代表性标的 |

### 3.2 信号分布对比（决策 D1 / E1 / F1 落地情况）

| 信号类型 (Signal) | v1 标的数量 | v2 标的数量 | 落地状态与决策依据 |
| :--- | :---: | :---: | :--- |
| `BREAKDOWN` (严重破位) | 6 只 (12.0%) | **0 只 (0.0%)** | **决策 D1 一票否决**，全部拦截归零 |
| `TREND_WEAKEN` (走弱预警) | 3 只 (6.0%) | **3 只 (6.0%)** | **决策 E1 转为 WATCH**，并注入 `risks` 预警文字 |
| `NO_SIGNAL` (无特征信号) | 13 只 (26.0%) | **23 只 (46.0%)** | **决策 F1 明确允许发布**，作为稳健观察标的 |
| `BREAKOUT` (突破) | 14 只 (28.0%) | **13 只 (26.0%)** | 保持高动量特征呈现 |
| `VALUE_CONTRARIAN` (逆向) | 8 只 (16.0%) | **7 只 (14.0%)** | 保持价值低估特征呈现 |
| `TREND_CONTINUE` (延续) | 5 只 (10.0%) | **4 只 (8.0%)** | 保持趋势稳健特征呈现 |
| `DIVIDEND_SUPPORT` (红利支撑) | 1 只 (2.0%) | **0 只 (0.0%)** | 因子除权日重估后微调 |

#### TREND_WEAKEN 标的风险预警实证（决策 E1）：
- `688617.SH`: `next_action="WATCH"`, `risks=['技术信号提示走弱风险 (TREND_WEAKEN)']`
- `300832.SZ`: `next_action="WATCH"`, `risks=['技术信号提示走弱风险 (TREND_WEAKEN)']`
- `601069.SH`: `next_action="WATCH"`, `risks=['技术信号提示走弱风险 (TREND_WEAKEN)']`

### 3.3 主策略归属与跨策略排序防混淆（Plan A Task 2）

| 主策略 (`primary_strategy_id`) | v1 状态 | v2 候选数 | 说明 |
| :--- | :---: | :---: | :--- |
| `momentum` | `None` (混淆) | 17 只 | 动量策略优质入选标的 |
| `growth` | `None` (混淆) | 12 只 | 成长策略优质入选标的 |
| `value` | `None` (混淆) | 12 只 | 价值策略优质入选标的 |
| `quality` | `None` (混淆) | 8 只 | 质量策略优质入选标的 |
| `garp` | `None` (混淆) | 1 只 | GARP 策略优质入选标的 |
| **合计** | - | **50 只** | **彻底消除跨策略评分混合排序隐患** |

---

## 四、合规与验收签署

1. **数据与逻辑第一性原理验证**：Candidate v2 完全遵循“双门槛合格 -> 5维市场验证非否决 -> 策略技术信号检测 -> 审批发布策略”严格逻辑链条；
2. **零静默兜底**：无任何未审计数据被静默转化为 0、False 或 NEUTRAL；
3. **独立校验 100% 通过**：测试环境与沙箱产物经独立验证器检验 0 findings；
4. **Plan B 门禁解除**：Plan B 全部 9 项任务圆满完成，系统具备进入 **Plan C: Candidate / Today Query Experience** 的完整条件。
