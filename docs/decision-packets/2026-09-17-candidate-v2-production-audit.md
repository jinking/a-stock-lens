# Candidate v2 全链路生产验收与独立产物审计报告（2026-09-17）

- **审计基准日期 (as_of)**: `2026-09-17T15:00:00+08:00`
- **审计执行时间**: `2026-09-22`
- **执行方式**: 标准生产命令行 `PYTHONPATH= uv run --no-sync astock daily --as-of 2026-09-17`（非沙箱，标准管线正式发布）
- **审计依据**: 
  - `docs/superpowers/specs/2026-09-21-production-candidate-v2-web-mvp-design.md`
  - `docs/superpowers/plans/2026-09-21-production-candidate-v2-closure.md` (Task 7)
  - `docs/decision-packets/2026-09-21-candidate-v2-market-evidence-decision.md`
- **独立审计器**: `tests/artifacts/validator.py`（纯标准库实现，零导入生产领域模块）
- **快照不可变性**: 严格保持历史快照 `data/snapshots/CANDIDATE/2026-09-19.json` 原样不变，新发布 `2026-09-17.json` 零覆盖、零命名冲突。

---

## 一、审计执行结论（Executive Summary）

1. **标准生产 Daily 管线全链路闭环**：
   - 标准 `astock daily --as-of 2026-09-17` 一键执行完成，11 阶段全量调度；
   - 正式持久化五大权威快照：`UNIVERSE`、`FACTOR`、`STRATEGY`、`MARKET_REGIME`、`CANDIDATE`；
   - 彻底摆脱沙箱测试依赖，Candidate v2 在标准生产路径上正式落地。

2. **独立第三方产物审查全量零缺陷（0 Findings）**：
   - 单快照规范审查（`validate_snapshot`）：
     - `UNIVERSE`: **0 findings**
     - `FACTOR`: **0 findings**
     - `STRATEGY`: **0 findings**
     - `MARKET_REGIME`: **0 findings**（单记录、词表合法、血缘非空）
     - `CANDIDATE`: **0 findings**（50 只上限合规、D1 否决与 E1 预警独立复算 100% 吻合）
   - 跨快照引用与血缘一致性（`validate_snapshot_set`）：**0 findings**（50 只候选引用的因子、策略、时点在同日快照中 100% 闭环）
   - 调度运行记录（`validate_job_manifest`）：**0 findings**（11 阶段清单完整，阻断显式透明）

3. **用户端日常查询验证完全可用**：
   - `astock today --as-of 2026-09-17`：秒级输出当日市场环境（BEAR）、策略分布、验证状态、信号分布及 Top 10 核心候选；
   - `astock candidates --as-of 2026-09-17 --top 20`：清晰呈现 20 只候选股票的主策略、合格策略集、验证结论与交易信号；
   - `astock stock 000001.SZ --as-of 2026-09-17`：单股画像清晰呈现各维度因子、策略资格、主策略价值（value）、验证中性（NEUTRAL）与价值企稳信号（VALUE_CONTRARIAN）。

---

## 二、生产日常调度管线执行清单（Job Manifest）

本次标准执行生成的 `var/jobs/2026-09-17.json` 全流程 11 阶段记录如下：

| 调度阶段 (JobStage) | 执行状态 | 处理行数 (In -> Out) | 执行说明 |
| :--- | :---: | :---: | :--- |
| `SYNC_DATA` | SKIPPED | - | 规范跳过（已预先存在本地数据） |
| `NORMALIZE` | SUCCEEDED | 1,675,723 -> 1,675,723 | 涵盖日K线、财务报表、估值及分红数据 |
| `COMPUTE_FACTORS` | SUCCEEDED | 5,008 -> 120,192 | 24 个因子计算，含除权日口径真实 TTM 股息率 |
| `BUILD_UNIVERSE` | SUCCEEDED | 5,565 -> 2,303 | 2,303 只研究池标的，申万二级全覆盖 |
| `RUN_STRATEGIES` | SUCCEEDED | 2,303 -> 13,818 | 六策略计算评分与百分位横截面排名 |
| `DETECT_REGIME` | SUCCEEDED | 1,675,723 -> 1 | 判定为 `BEAR`（宽度与中证全指均线趋势双重判定） |
| `MARKET_VALIDATE` | SUCCEEDED | 388 -> 388 | 合格标的 5 维验证：Confirmed=0, Contradicted=143, Neutral=245 |
| `RUN_SIGNALS` | SUCCEEDED | 388 -> 388 | 合格标的信号检测：激活 142 只 |
| `BUILD_CANDIDATES` | SUCCEEDED | 13,818 -> 50 | 经 D1 否决与代表性择优，生成 50 只 Candidate v2 |
| `UPDATE_WATCHLIST` | BLOCKED | - | 依法保持阻塞（自选股流转严格由用户主动发起，spec §13） |
| `GENERATE_DAILY_SNAPSHOT` | SUCCEEDED | - -> 5 | 成功生成五大快照（FACTOR, UNIVERSE, STRATEGY, MARKET_REGIME, CANDIDATE） |

---

## 三、生产统计指标与候选分布（Production Counts）

### 3.1 总体统计
- **Research Universe**: 2,303 只
- **Strategy 评分记录**: 13,818 条
- **合格策略标的 (Qualified Unique Symbols)**: 388 只
- **市场环境 (Market Regime)**: `BEAR`（R2 生产判定结合市场宽度与中证全指 000985.CSI 趋势）
- **最终候选标的数 (Candidate Count)**: 50 只（达到政策上限 50 只）

### 3.2 候选主策略分布 (`primary_strategy_id`)
| 主策略 | 候选标的数量 | 占比 |
| :--- | :---: | :---: |
| `momentum` | 32 只 | 64.0% |
| `quality` | 10 只 | 20.0% |
| `growth` | 7 只 | 14.0% |
| `value` | 1 只 | 2.0% |
| **合计** | **50 只** | **100.0%** |

### 3.3 市场验证状态分布 (`market_validation`)
| 状态 | 数量 | 占比 | 说明 |
| :--- | :---: | :---: | :--- |
| `NEUTRAL` | 50 只 | 100.0% | 市场行为处于蓄势或弱平衡状态，无冲突项 |
| `CONTRADICTED` | 0 只 | 0.0% | 143 只冲突/破位标的已被 100% 依法否决剔除 |
| `CONFIRMED` | 0 只 | 0.0% | 在 BEAR 空头市场环境下严格防守，无盲目激进通过 |

### 3.4 交易特征信号分布 (`signal`)
| 信号类型 | 标的数量 | 占比 | 业务含义 |
| :--- | :---: | :---: | :--- |
| `BREAKOUT` (突破) | 19 只 | 38.0% | 强势突破新高标的 |
| `NO_SIGNAL` (无特征信号) | 15 只 | 30.0% | 常规观察候选，决策 F1 明确允许发布 |
| `TREND_CONTINUE` (延续) | 12 只 | 24.0% | 强趋势稳步上行中 |
| `TREND_WEAKEN` (走弱预警) | 3 只 | 6.0% | 决策 E1 落实：动作均为 WATCH，注入走弱风险预警 |
| `VALUE_CONTRARIAN` (价值企稳) | 1 只 | 2.0% | 深度低估值区间筑底企稳标的（000001.SZ 平安银行） |
| `BREAKDOWN` (严重破位) | 0 只 | 0.0% | **决策 D1 一票否决**：破位标的彻底拦截归零 |

---

## 四、合规与验收签署

1. **输入数据无未来函数**：
   - 股票日K线截至 `2026-09-17`；
   - 基准指数中证全指（`000985.CSI`）截至 `2026-09-17` 共 3,471 根日线（远超 60 根门槛）；
   - 申万二级行业分类读取 `2026-09-17.csv`；
   - 财务与估值数据严格保证 `available_at <= as_of`。
2. **零静默兜底与 Fail-Closed 原则**：
   - 绝无任何未知数据回退至 0 或 False；
   - 次新股与单样本边界在策略层与验证层均保持严谨语义。
3. **独立第三方审计 0 Findings**：
   - `tests/artifacts/validator.py` 审查五大快照与 Job Manifest，零发现。
4. **Task 7 生产验收完全通过**，正式解除 Candidate v2 生产阻塞。
