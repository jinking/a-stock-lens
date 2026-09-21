# 2026-09-19 首期候选快照发布与独立产物审计决策包

- **审计基准日期 (as_of)**: `2026-09-19T15:00:00+08:00`
- **审计执行时间**: `2026-09-21`
- **生成命令**: `uv run astock daily --as-of 2026-09-19 --allow-incomplete`
- **独立审计器**: `tests/artifacts/validator.py`
- **产物文件**: `data/snapshots/CANDIDATE/2026-09-19.json`

---

## 1. 审计结论（Executive Summary）

1. **快照完整发布**: 2026-09-19 生产日常调度管线全链路跑通，历史首份 `CANDIDATE` 生产快照成功生成并安全存盘（`data/snapshots/CANDIDATE/2026-09-19.json`）。
2. **独立产物审查**: 经不共享任何业务代码的独立校验器全面审计：
   - 单快照规范（`validate_snapshot("CANDIDATE")`）：**0 Findings**
   - 跨快照血缘一致性（`validate_snapshot_set()`）：**0 Findings**
   - 全部 50 只候选标的所引用的策略结果、因子版本与时点在同日快照中 100% 存在且完全对齐。
3. **安全与语义红线**:
   - 严格落实项目所有者批准的 Mode B 全局阻塞语义与 RepresentativeCandidatePolicy 横截面选择；
   - 候选股票仅代表通过“双门槛合格 + 5维市场验证非否决 + 策略交易特征信号”的研究对象，不构成买入建议；
   - CLI 与 API 的单股研究画像全面接入，状态无缝跃迁。

---

## 2. 生产调度管线执行清单（Job Manifest）

`var/jobs/2026-09-19.json` 记录的全流程阶段状态如下：

| 调度阶段 (JobStage) | 执行状态 | 处理行数 (In -> Out) | 结果与备注 |
| :--- | :---: | :---: | :--- |
| `SYNC_DATA` | SKIPPED | - | 规范跳过（生产数据已预先落地） |
| `NORMALIZE` | SUCCEEDED | 1,675,723 -> 1,675,723 | 包含全量日线、三大报表、估值及分红事件数据 |
| `COMPUTE_FACTORS` | SUCCEEDED | 5,008 -> 120,192 | 全市场 24 个因子，含除权日口径真实 TTM 股息率 |
| `BUILD_UNIVERSE` | SUCCEEDED | 5,565 -> 2,303 | 2,303 只研究池标的，100% 申万二级行业覆盖 |
| `RUN_STRATEGIES` | SUCCEEDED | 2,303 -> 13,818 | 六策略完整评分与横截面百分位排名 |
| `DETECT_REGIME` | SUCCEEDED | 1,675,723 -> 1 | 判定市场环境为 `RANGE_DOWN` (市场宽度 27.9%) |
| `MARKET_VALIDATE` | SUCCEEDED | 2,303 -> 2,303 | Confirmed=106, Neutral=1515, Contradicted=682 (否决) |
| `RUN_SIGNALS` | SUCCEEDED | 2,303 -> 2,303 | 2,303 只全池检测，特征信号激活标的 978 只 |
| `BUILD_CANDIDATES` | SUCCEEDED | 13,818 -> 50 | 经一票否决剔除与代表性政策择优，生成 50 只候选 |
| `UPDATE_WATCHLIST` | BLOCKED | - | 依法保持阻塞（自选股变更严格由用户主动发起） |
| `GENERATE_DAILY_SNAPSHOT` | SUCCEEDED | - -> 4 | 成功写出 `FACTOR`, `UNIVERSE`, `STRATEGY`, `CANDIDATE` |

---

## 3. 候选股票集合特征与结构分布

候选入选总数：**50 只**（达到 RepresentativeCandidatePolicy 的 `max_candidates=50` 软上限）。

### 3.1 市场验证状态分布

| 市场验证状态 | 标的数量 | 占比 | 说明 |
| :--- | :---: | :---: | :--- |
| `CONFIRMED` | 19 只 | 38.0% | 量价齐升、均线多头、相对大盘强劲 |
| `NEUTRAL` | 31 只 | 62.0% | 技术面与行业处于中性观察期，无硬伤 |
| `CONTRADICTED` | 0 只 | 0.0% | **0 容忍**：682 只否决标的 100% 被拦截，无一漏入 |

### 3.2 策略交易信号分布

| 激活交易信号 (Signal) | 标的数量 | 代表标的示例 |
| :--- | :---: | :--- |
| `BREAKOUT` (突破) | 14 只 | 300741.SZ (华宝新能), 688137.SH (近岸蛋白), 000993.SZ (闽东电力) |
| `VALUE_CONTRARIAN` (价值逆向) | 8 只 | 601336.SH (新华保险), 601628.SH (中国人寿) |
| `TREND_CONTINUE` (趋势延续) | 5 只 | 002158.SZ (汉钟精机), 600011.SH (华能国际) |
| `DIVIDEND_SUPPORT` (股息支撑) | 1 只 | 600519.SH (贵州茅台) |
| `TREND_WEAKEN` (高位震荡) | 3 只 | 300438.SZ (鹏辉能源) |
| `BREAKDOWN` (破位观察) | 6 只 | 688578.SH (艾力斯), 688336.SH (三生国健) |
| `NO_SIGNAL` (无特征信号) | 13 只 | 601319.SH (中国人保) |

### 3.3 策略代表性分布（去重后多策略共振）

- `momentum`: 18 只
- `quality`: 16 只
- `growth`: 13 只
- `value`: 12 只
- `garp`: 7 只

*注：部分标的由多策略共同推荐，如 601336.SH 同时入选 `garp` 与 `value`，601628.SH 同时入选 `garp`、`growth` 与 `value`。*

---

## 4. API 与 CLI 端到端证据

1. **候选列表 API (`GET /candidates?as_of=2026-09-19`)**
   - 响应状态码：`200 OK`
   - 返回记录数：`50` 条完整候选记录，字段涵盖 `strategy_results`, `strategy_qualifications`, `market_validation`, `signal`, `lineage`。
2. **单股研究画像 API (`GET /stocks/{symbol}?as_of=2026-09-19`)**
   - 候选标的（以 `600519.SH` 贵州茅台为例）：
     `candidate_status="published"`，`candidate` 对象完整呈现 `quality` 策略评分 85.56、市场验证 `NEUTRAL`、交易信号 `DIVIDEND_SUPPORT`。
   - 非候选合格标的（以 `000001.SZ` 平安银行为例）：
     `candidate_status="not_selected"`，真实反映未进入最终 50 只代表性清单的现状，杜绝虚假披露。
3. **CLI 命令行画像 (`astock stock 600519.SH --as-of 2026-09-19`)**
   - 显式输出：`candidate: WATCH`，血缘信息完整输出。

---

## 5. 归档记录

在生成本期新快照前，已安全备份历史 09:49 版本的快照文件至：
- `data/snapshots_legacy_pre_candidate/2026-09-19/FACTOR.json`
- `data/snapshots_legacy_pre_candidate/2026-09-19/STRATEGY.json`
- `data/snapshots_legacy_pre_candidate/2026-09-19/UNIVERSE.json`
- `var/jobs_legacy_pre_candidate/2026-09-19.json`
零文件物理丢失，随时可查证历史对比证据。
