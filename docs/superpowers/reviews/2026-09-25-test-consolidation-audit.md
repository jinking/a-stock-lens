# 测试用例精简：批次 0 基线与逐条复核台账

- 任务：实施计划 Task 0「冻结基线」（`docs/superpowers/plans/2026-09-25-test-suite-consolidation-implementation-plan.md`）
- 规格：`docs/superpowers/specs/2026-09-25-test-suite-consolidation-design.md`
- 工作树：`/Users/huangjinjin/Documents/ChatGPT/a-stock-lens/.worktrees/test-consolidation`
- 日期：2026-09-25

本文件同时承担两个角色：批次 0 的基线证据，以及后续批次（尤其 Task 10 跨层去重）
「指名权威替代」的**唯一台账**。行号一律是基线位置（改动后会漂移），引用一律用
`文件::测试名`。

**台账优于计划：** 本文件 5.1/5.2 的逐条复核结论与附录 A / 计划 Task 10 的原始判断
不一致时，以本文件为准（差异清单见 5.4）。

---

## 1. 工作区状态与 HEAD

| 项 | 值 |
| --- | --- |
| 分支/工作树 HEAD | `276f1ae994355335dab526a0f30740a059425bf7`（`文档：定稿测试用例精简实施计划`） |
| 工作树清洁度 | 除本地证据目录 `var/test-consolidation/`（未跟踪、不提交）外全净 |
| 生产代码改动 | 无（`src/**`、`configs/**` 零改动；本轮不修改任何测试文件） |
| 冻结 5 文件 | 已提交、无未提交改动 → **冻结口径 = 「文件当前内容」** |

冻结文件在本基线的实测用例数（规格 §3.1 表 vs 实测）：

| 文件 | 规格 §3.1 | 实测 |
| --- | --- | --- |
| `tests/unit/test_cli_lifecycle.py` | 42 | 42 |
| `tests/unit/test_raw_sync.py` | 19 | 19 |
| `tests/unit/test_akshare_provider.py` | 18 | 18 |
| `tests/contract/test_extension_contracts.py` | **16** | **8** |
| `tests/unit/test_bootstrap_sync.py` | 15 | 15 |
| 合计 | 110 | **102** |

**口径修正：** `test_extension_contracts.py` 实测仅 8 例（直接 collect 复核），冻结总数
102，本轮可动集合 **1298 − 102 = 1196 例**（规格 §3.1 的 1188 与 −21.7% 需按此修正为
−21.6%）。此差异已在本文件留痕，供 Task 14 验收引用。

**环境口径（所有命令沿用）：**

```bash
UV_PROJECT_ENVIRONMENT=/Users/huangjinjin/Documents/ChatGPT/a-stock-lens/.venv UV_OFFLINE=1 PYTHONPATH= uv run --no-sync <cmd>
```

共享主仓 venv，不新建环境；`--no-sync` 与空 `PYTHONPATH=` 必须保留。

---

## 2. 基线 collect

```bash
UV_PROJECT_ENVIRONMENT=/Users/huangjinjin/Documents/ChatGPT/a-stock-lens/.venv UV_OFFLINE=1 PYTHONPATH= \
  uv run --no-sync pytest --collect-only -q
# → 1298 tests collected in 6.05s        （与控制器给定基线 1298 一致）
```

逐文件计数（`--collect-only -q` 输出按 `::` 前缀归并）：

```bash
UV_PROJECT_ENVIRONMENT=/Users/huangjinjin/Documents/ChatGPT/a-stock-lens/.venv UV_OFFLINE=1 PYTHONPATH= \
  uv run --no-sync pytest --collect-only -q 2>/dev/null \
  | grep "::" | cut -d: -f1 | sort | uniq -c | sort -rn
```

分层核对（与规格 §2 完全一致）：unit **1060** / integration **158** / artifacts **60** /
contract **16** / stress **4** = **1298**，共 **136** 个文件。

### 2.1 逐文件基线表（136 行，合计 1298）

| cases | 文件 |
| --- | --- |
| 63 | tests/unit/test_financial_normalizer.py |
| 47 | tests/unit/test_api.py |
| 42 | tests/unit/test_cli_lifecycle.py |
| 33 | tests/unit/test_duckdb_snapshot_store.py |
| 31 | tests/unit/test_westock_provider.py |
| 30 | tests/unit/test_strategy_scanners.py |
| 25 | tests/artifacts/test_snapshot_validator.py |
| 23 | tests/unit/test_strategy_scoring.py |
| 21 | tests/unit/test_universe_builder.py |
| 21 | tests/unit/test_trailing_return_factor.py |
| 21 | tests/unit/test_research_baseline_audit.py |
| 19 | tests/unit/test_raw_sync.py |
| 19 | tests/unit/test_proximity_high_factor.py |
| 18 | tests/unit/test_qualification_config.py |
| 18 | tests/unit/test_akshare_provider.py |
| 18 | tests/integration/test_daily_pipeline.py |
| 17 | tests/unit/test_neodata_provider.py |
| 17 | tests/unit/test_lake_provider.py |
| 17 | tests/unit/test_fundamental_factors.py |
| 16 | tests/unit/test_storage_paths.py |
| 16 | tests/unit/test_bootstrap_batch_fallback.py |
| 15 | tests/unit/test_bootstrap_sync.py |
| 15 | tests/unit/test_benchmark_landing_reader.py |
| 14 | tests/unit/test_bootstrap_checkpoint.py |
| 14 | tests/artifacts/test_validator.py |
| 13 | tests/unit/test_watchlist_store.py |
| 13 | tests/unit/test_watchlist_state_machine.py |
| 13 | tests/unit/test_strategy_qualification.py |
| 13 | tests/unit/test_eligibility_scanner.py |
| 13 | tests/unit/test_candidate_selection_policy.py |
| 12 | tests/unit/test_westock_bars.py |
| 12 | tests/unit/test_valuation_factors.py |
| 12 | tests/unit/test_strategy_registry.py |
| 12 | tests/unit/test_normalized_repository.py |
| 12 | tests/unit/test_market_regime.py |
| 12 | tests/unit/test_job_store.py |
| 12 | tests/unit/test_industry_membership.py |
| 12 | tests/unit/test_industry_evidence.py |
| 11 | tests/unit/test_snapshot_store.py |
| 11 | tests/unit/test_neodata_landing.py |
| 11 | tests/unit/test_market_validator.py |
| 11 | tests/unit/test_csv_security_normalizer.py |
| 11 | tests/unit/test_bootstrap_progress.py |
| 11 | tests/integration/test_research_baseline_capture.py |
| 11 | tests/artifacts/test_job_manifest_validator.py |
| 10 | tests/unit/test_universe_prefilter.py |
| 10 | tests/unit/test_percentile_scorer.py |
| 10 | tests/unit/test_local_csv_provider.py |
| 10 | tests/unit/test_csv_daily_bar_normalizer.py |
| 10 | tests/unit/test_avg_amount_factor.py |
| 9 | tests/unit/test_momentum_scanner.py |
| 9 | tests/unit/test_cli_research_adapter.py |
| 9 | tests/unit/test_cli.py |
| 9 | tests/integration/test_screen_cli.py |
| 9 | tests/integration/test_qualified_cli.py |
| 9 | tests/integration/test_calibration_readiness_cli.py |
| 9 | tests/integration/test_analysis_pipeline.py |
| 9 | tests/artifacts/test_candidate_semantic_validator.py |
| 8 | tests/unit/test_valuation_normalizer.py |
| 8 | tests/unit/test_valuation_coverage.py |
| 8 | tests/unit/test_signal_detector.py |
| 8 | tests/unit/test_financial_quality_gate.py |
| 8 | tests/unit/test_discovery_service.py |
| 8 | tests/unit/test_candidate_evidence.py |
| 8 | tests/unit/test_candidate_builder.py |
| 8 | tests/integration/test_research_universe_flow.py |
| 8 | tests/contract/test_qualification_production_rules.py |
| 8 | tests/contract/test_extension_contracts.py |
| 7 | tests/unit/test_universe_config.py |
| 7 | tests/unit/test_strategy_parity.py |
| 7 | tests/unit/test_market_evidence.py |
| 7 | tests/unit/test_dividend_yield_factor.py |
| 7 | tests/unit/test_cli_industry_loader.py |
| 7 | tests/unit/test_calibration_factor_distribution.py |
| 7 | tests/integration/test_valuation_backfill_cli.py |
| 7 | tests/integration/test_financial_pipeline.py |
| 6 | tests/unit/test_trading_calendar.py |
| 6 | tests/unit/test_qualified_discovery.py |
| 6 | tests/unit/test_daily_bar_quality_gate.py |
| 6 | tests/unit/test_candidate_policy.py |
| 6 | tests/integration/test_valuation_pipeline.py |
| 6 | tests/integration/test_command_snapshot_ownership.py |
| 6 | tests/integration/test_candidate_qualification_pipeline.py |
| 6 | tests/integration/test_candidate_correctness_gate.py |
| 6 | tests/integration/test_candidate_calibration_cli.py |
| 5 | tests/unit/test_qualification_impact.py |
| 5 | tests/unit/test_market_signal_readiness.py |
| 5 | tests/unit/test_jev_triage.py |
| 5 | tests/unit/test_industry_market_evidence.py |
| 5 | tests/unit/test_domain_models.py |
| 5 | tests/unit/test_candidate_routing.py |
| 5 | tests/unit/test_candidate_primary_strategy.py |
| 5 | tests/unit/test_candidate_discovery.py |
| 5 | tests/unit/test_candidate_calibration.py |
| 5 | tests/integration/test_market_regime_snapshot.py |
| 5 | tests/integration/test_daily_production_evidence.py |
| 4 | tests/unit/test_strategy_factor_index.py |
| 4 | tests/unit/test_qualification_context.py |
| 4 | tests/unit/test_factor_registry.py |
| 4 | tests/unit/test_dividend_event_normalizer.py |
| 4 | tests/unit/test_dividend_coverage.py |
| 4 | tests/unit/test_bootstrap_scheduler.py |
| 4 | tests/unit/test_bootstrap_scan_cost.py |
| 4 | tests/unit/test_benchmark_evidence.py |
| 4 | tests/stress/test_bootstrap_scale_properties.py |
| 4 | tests/integration/test_today_cli.py |
| 4 | tests/integration/test_qualification_pipeline.py |
| 4 | tests/integration/test_candidates_cli.py |
| 3 | tests/unit/test_trade_gate_veto.py |
| 3 | tests/unit/test_trade_gate_scoring.py |
| 3 | tests/unit/test_trade_gate_models.py |
| 3 | tests/unit/test_trade_gate_context.py |
| 3 | tests/unit/test_trade_gate_audit_adapter.py |
| 3 | tests/unit/test_docs_consistency.py |
| 3 | tests/unit/test_candidate_v2_impact.py |
| 3 | tests/integration/test_stock_discovery_workflow.py |
| 3 | tests/integration/test_market_signal_readiness_cli.py |
| 3 | tests/integration/test_dividend_sync_cli.py |
| 2 | tests/unit/test_trade_gate_store.py |
| 2 | tests/unit/test_trade_gate_profiles.py |
| 2 | tests/unit/test_trade_gate_engine.py |
| 2 | tests/unit/test_trade_gate_duckdb_store.py |
| 2 | tests/integration/test_qualification_impact_cli.py |
| 2 | tests/integration/test_post_valuation_analysis_flow.py |
| 2 | tests/integration/test_dividend_qualified_discovery.py |
| 1 | tests/unit/test_trade_gate_service.py |
| 1 | tests/unit/test_trade_gate_replay.py |
| 1 | tests/unit/test_trade_gate_metrics.py |
| 1 | tests/unit/test_settings.py |
| 1 | tests/unit/test_normalized_dataset_dividends.py |
| 1 | tests/unit/test_import.py |
| 1 | tests/integration/test_trade_gate_cli.py |
| 1 | tests/integration/test_market_signal_pipeline.py |
| 1 | tests/integration/test_dividend_factor_pipeline.py |
| 1 | tests/integration/test_daily_candidate_pipeline.py |
| 1 | tests/artifacts/test_trade_gate_validator.py |

**文件数分布（Task 12 用）：** ≤9 例的文件 **86** 个，≥10 例的文件 **50** 个。

---

## 3. 覆盖率基线

```bash
UV_PROJECT_ENVIRONMENT=/Users/huangjinjin/Documents/ChatGPT/a-stock-lens/.venv UV_OFFLINE=1 PYTHONPATH= \
  uv run --no-sync pytest -q --cov=astock_lens --cov-report=term
# → 1298 passed, 7 warnings in 443.68s (0:07:23)
```

TOTAL 行原样：

```text
TOTAL                                                                                                       8703    734    92%
```

**这 92% 是规格 §7.1「覆盖率不低于基线」的唯一比较基准。**

**口径说明（必须与数字一起引用）：** 本工作树与主仓**共享同一个 venv**，其 editable
install 把 `astock_lens` 解析到主仓
`/Users/huangjinjin/Documents/ChatGPT/a-stock-lens/src/astock_lens/`。因此覆盖率必须按
**模块名**（`--cov=astock_lens`）测量——量的就是实际被导入的那份代码。审计已 `diff -r`
证实主仓与工作树的 `src/astock_lens` 内容一致（仅 `__pycache__` 不同）；主仓 HEAD 与本
worktree HEAD 相同（`276f1ae`），其未提交改动只涉及 `.env.example / AGENTS.md /
README.md`，`src/**`、`configs/**` 无改动。

**已废弃口径（留档，不得用于比较）：** `--cov=src/astock_lens` 在批次 0 曾量出
`TOTAL 8703 8703 0%`。该 0% 是**测量口径失效**：它量的是**本 worktree**路径，而该路径的
模块被导入时解析到的是**主仓**同名模块，于是全部语句被判「未覆盖」——不是真实覆盖为零。
原始输出留在 `var/test-consolidation/coverage-baseline.txt`（不提交），不再作任何基准。

**约定：**

1. Task 14 验收比较覆盖率时，必须运行**本节完全相同的命令**
   （`--cov=astock_lens --cov-report=term`），与本节的 92% 对同口径；
2. 原始输出留档 `var/test-consolidation/coverage-baseline-module.txt`（不提交）。
3. 一旦有任务改动 `src/**` 或 `configs/**`（违反 Global Constraints），本节的 92% 基准
   立即作废、必须重测（本轮全程禁止改动生产代码与配置，正常情况下不会触发）。
4. 留档文件 `var/test-consolidation/coverage-baseline-module.txt` 是**两次运行的合并输出**
   （文件内两个 TOTAL 都是 `8703 734 92%`）；Task 14 追加时须标明运行序号/时间，
   以免把两次输出误读为单次证据。

---

## 4. 红项分类

- 基线**全绿**：`1298 passed, 7 warnings`，`0 failed` / `0 error` / `0 skipped`。
- 控制器预告的红项 `tests/unit/test_akshare_provider.py::test_the_batch_contract_still_fails_as_a_whole`
  **在本基线不存在**：该文件实测 18 例、逐例列出无此名；名字相近的是冻结文件
  `tests/unit/test_bootstrap_sync.py::test_the_batch_contract_lands_partial_and_names_the_failures`，
  且它通过。
- 分类结论：**无红项**（无 out of scope 项、无「非冻结文件失败」项）→ 不触发
  STOP/BLOCKED，任务继续到 Step 5/6。
- 7 条 warning 均为第三方弃用告警（starlette `anyio.abc.BlockingPortal`、
  multiprocessing `fork()`），与本轮无关，不列入红项。
- **format 门禁事实（本轮执行口径）**：基线 `59119d2` 上 `ruff format --check .`
  **本就不是全绿**——`src/astock_lens/data/providers/akshare_provider.py` 与冻结文件
  `tests/unit/test_akshare_provider.py` 需重排，属既有漂移且本轮禁止改动；因此
  **format 检查只对本任务改动过的文件执行**（全仓检查必然报红，不是新问题）。
  `ruff check .` 基线是全绿的。

---

## 5. Step 5 复核台账

### 5.0 口径

- 「权威替代」列：DELETE 行 = 承接其**每一条**断言的其他测试 `文件::测试名`；MERGE 行 =
  合并后的用例本身（写「合并后自身 + `文件::测试名`」）；KEEP 行 = 写「—（无删除）」
  并说明权威缺失/不足的具体断言，**不留空**。
- `for ...: assert` 短路的写法禁止：表驱动必须「先收集后断言」且失败消息点名参数。
- 冻结文件（102 例）不进入任何删除/合并；假重复清单（5.3）不得删。
- 本节结论**优先于**附录 A 与计划 Task 10 的原始判断（差异见 5.4）。

### 5.1 附录 A 候选逐条复核

| 位置 | 现状 case 数 | 决策 | 权威替代（文件::测试名） | 复核结论 |
| --- | --- | --- | --- | --- |
| `tests/unit/test_financial_normalizer.py::test_every_metric_declares_a_unit`（:289） | 49 | MERGE → 1 | 合并后自身：`tests/unit/test_financial_normalizer.py::test_every_metric_declares_a_unit` | 实测 `len(FINANCIAL_METRICS)==49`，断言仅 `assert metric.unit`。合并成单条遍历/参数化，断言逐项保留；失败消息必须点名 `metric.metric`；先收集再断言。 |
| `tests/unit/test_strategy_scanners.py`（6 个参数化函数 × 5 SCANNERS，:67–141） | 30 | MERGE → 6 | 合并后自身（6 条函数各自保留） | 逐函数核对断言集：类名；`required_factors` 与配置一致；单标的 `score is None` + `eligible is True` + `strategy_id`；缺因子 ineligible + 点名 reason；explain 到因子层；横截面排名只含 eligible。合并只摊平 ×5 的重复，6 条语义各留一条。 |
| `tests/unit/test_eligibility_scanner.py::test_any_status_other_than_value_is_not_eligible`（:94–104） | 5 | MERGE → 1 | 合并后自身 | 参数块 = 5 个 `DataStatus`（NULL/STALE/INVALID/SOURCE_ERROR/NOT_APPLICABLE）；断言 `eligible is False` + `f"gross_margin is {status}, not VALUE" in result.risks`。表化后逐行携带 status 与消息点名。 |
| `tests/unit/test_api.py::test_strategy_results_invalid_query_returns_422`（:411–431） | 5 | MERGE → 1 | 合并后自身 | 参数块 = 5 组 `(param, value)`（limit 0/-1/501，min_percentile -0.1/1.1）；断言仅 422。表化后逐行携带参数与值，失败消息点名。 |
| `tests/unit/test_qualification_config.py`（15 条「写 YAML → raises」，:24–208） | 15 | MERGE → 3 | 合并后自身 | 15 组非法 YAML 的具体 payload 与 match 文案必须逐行进表（不许抽象成一类）；特殊 kwargs 必须保留：`growth.yaml` 的 `expected_strategy_id`、`known_factor_names=frozenset({"pb"})`；`missing strategy_id` 键这一**无 match** 的裸 raises 形态必须独立保留；另 3 条与本族无关（合法加载 / `FileNotFoundError` 语义 / allowed root keys）不动。控制器裁决以 **1 张表**为目标，无 match 的裸 raises 形态用 `expected=None` 的行承接；做不到再退 ≤3 张表。 |
| `tests/unit/test_snapshot_store.py`（:36–146） | 11 | **DELETE 4 / KEEP 7**（附录写 DELETE 6，改正） | 见 5.1.1 明细 | 逐条断言对照 `test_duckdb_snapshot_store.py` 的 `store` fixture 套件（json+duckdb × 11 共享例）。仅 4 例可证被覆盖；其余 7 例各含套件无法承接的断言（见明细）。 |
| `tests/unit/test_trailing_return_factor.py`（RANKED 6 标的，:85） | 6 | MERGE → 1 | 合并后自身 | 断言 = `status is VALUE` + `approx(closes[-1]/closes[-21]-1)`。表化后逐行携带 symbol 与收盘序列，失败消息点名 symbol。 |
| `tests/unit/test_proximity_high_factor.py`（:62、:73 两个参数块 6+4） | 10 | MERGE → 2 | 合并后自身 | 两块断言不同：6 例族保 `raw_value` 语义；SPIKED 4 例保 `raw_value < 1/1.01`。各自合并为一张表，两表断言逐行保留。 |
| `tests/unit/test_valuation_factors.py`（5 因子，:73） | 5 | MERGE → 1 | 合并后自身 | 断言 = `NOT_APPLICABLE` + `raw_value is None`；逐行携带因子名。 |
| `tests/unit/test_watchlist_state_machine.py`（RESERVED_STATES 4 态，:83） | 4 | MERGE → 1 | 合并后自身 | 断言 = `target.value in str(raised.value)`；逐行携带 reserved state。 |
| `tests/contract/test_qualification_production_rules.py`（6 策略，:69） | 6 | MERGE → 1 | 合并后自身（文件不合并，§3.4） | 断言 = `strategy_id` 对应 + `version == "v1"` + `thresholds == EXPECTED`；逐行携带策略与期望阈值字典。 |
| `tests/artifacts/test_snapshot_validator.py`（finding 报出族） | 15 | MERGE（断言不删） | 合并后自身（同族单表） | 族实为 **15** 条，不是附录写的 13：`:112/:118/:136/:144/:155/:166/:176/:186/:193`（9）+ `:279/:289/:300`（available_at 3）+ `:368/:380/:392`（cross_snapshot 3）。负例 5 条不得删或并入：`:126`（缺失 score 不是范围错）、`:271`、`:311`、`:357`、`:411`；定位断言 `:242 test_findings_name_the_symbol_and_the_observation` 不得删。每行必须携带 finding code 与关键文案。 |
| `tests/artifacts/test_job_manifest_validator.py`（「X is reported」族） | 9 | MERGE（断言不删） | 合并后自身（同族单表） | 9 条 = `:86/:90/:99/:105/:113/:119/:125/:138/:146`；每行携带 code + 观察值断言（含 `RUN_SIGNALS` 的 observed 断言）；干净负例 `:82 test_a_clean_manifest_produces_no_findings` 与往返例 `:154 test_the_manifest_a_daily_run_writes_validates_cleanly` 保持不动。 |
| `tests/unit/test_signal_detector.py`（8 条因子→signal，:28–134） | 8 | MERGE → ≤2 | 合并后自身 | 逐条核对：每条都断言 `signal` + `strategy_id` + score/lineage 类信息；`test_signal_breakout`（:28）另有 `isinstance`/lineage 断言，能入表则一条表驱动，否则独立保留一条 → 8 → ≤2。 |
| `tests/unit/test_market_regime.py`（判定族，:36–134 区间外还含 :160） | 12 | **MERGE → ≤5**（附录写 9→3，改正） | 合并后自身 | 12 = 8 条判定（:20/:36/:48/:60/:72/:84/:110/:123）+ 3 条 fail-closed（:98 无数据 / :136 宽度不可用 / :148 基准仅 59 根，**假重复，必须保持 3 条独立**）+ 1 条 `:160 test_r2_b3_volatility_deferred_reason`（第三个观察点，保留）。判定表逐行携带 breadth/index_trend 输入与期望 regime。 |
| 4 处源码文本扫描（`test_financial_normalizer` / `test_fundamental_factors` / `test_api` / `test_bootstrap_progress`） | 4 | MERGE → 1 张表 | 合并后自身（单表 `模块 × 禁用词`） | 词表**按文件原样分列，不许取并集**：`financials.py` 5 词（subprocess/urlopen/Runner/.fetch(/requests）、`fundamental.py` 4 词（无 Runner）、`api/app.py` **12 词**（含 factors.builtin、strategies.momentum、AverageAmountFactor、MomentumScanner、build_scanner、trade_gate.engine、TradeGateEngine、ThesisAuditAdapter）、`scripts/watch-bootstrap.sh` 3 个禁用词 + **1 个必须词**（`"manifest" in script`，正向断言必须活下来，可在表里加 required 列）。 |
| `tests/unit/test_api.py::test_api_module_imports_strictly_bounded`（:1015，4 词 AST） | 1 | **DELETE（方向修正）** | 表化后的 `api/app.py` 12 词文本扫描（12 词清单即 `test_api_never_imports_the_computation_engines` 的清单，进 A16 表） | 计划 Task 11 Step 2 让「保留 AST、删 12 词扫描」并自称保留者是超集——实测**反向**：AST 的 4 词（astock_lens.pipelines/run_analysis/factor_stage/strategy_stage）是 12 词的**子集**，且 import 命中必然意味着源文本命中，故 AST 的检测集 ⊆ 文本扫描；按计划自订判据必须反方向执行，否则丢 8 个词。 |
| `tests/unit/test_docs_consistency.py`（3 条过期文案，:10/:21/:33） | 3 | MERGE → 1 | 合并后自身（单表 `文件 × 过期文案`） | 3 条共 11 条文案（README 4 + ROADMAP 3 + REMAINING_PRODUCT_BLOCKERS 4）逐条进表；失败消息点名 path + phrase。 |
| 恒真断言 3 处（`:16` / `:196` / `:258`） | ±0（断言行，不是用例） | 删断言行、**用例保留**（KEEP） | —（无删除用例；权威=用例自身其余断言） | 逐处核实恒真：`test_normalized_dataset_dividends.py::test_normalized_dataset_supports_dividend_events` 的 `assert hasattr(ds_empty, "dividend_events")` 被下一行 `ds_empty.dividend_events == ()` 蕴含；`test_market_signal_readiness.py::test_representative_sampling_deterministic_with_tie_breaking` 的 `assert hasattr(strat, "samples")` 被其下 `strat.samples` 迭代蕴含；`test_westock_bars.py::test_bulk_provider_logs_download_progress_to_the_console` 的 `assert callable(progress_callback)` 被其下 `progress_callback(100, 5568, 97)` 调用蕴含。不计入减量。 |

#### 5.1.1 `test_snapshot_store.py` 明细（A6 / Task 10 组 1）

共享套件 = `tests/unit/test_duckdb_snapshot_store.py` 的 `store` fixture
（`params=["json","duckdb"]`，11 条共享用例 × 2 后端）。

| 位置（用例） | 决策 | 权威替代 | 复核结论 |
| --- | --- | --- | --- |
| `test_snapshot_store.py::test_unwritten_date_reads_empty` | DELETE | `test_duckdb_snapshot_store.py::test_an_absent_snapshot_reads_as_empty` | 断言 `read(CANDIDATE) == ()` 逐字覆盖；json 后端本就是该套件的一个参数。 |
| `test_snapshot_store.py::test_kinds_do_not_collide` | DELETE | `test_duckdb_snapshot_store.py::test_kinds_are_kept_apart` + `test_candidate_snapshot_conflict_refused_across_both_stores` + `test_a_written_snapshot_reads_back`（后两条承接「恰好一条记录」的等值断言） | 同断言（FACTOR/CANDIDATE 同日期互不串）。 |
| `test_snapshot_store.py::test_different_payload_for_the_same_kind_and_date_is_rejected` | DELETE | `test_duckdb_snapshot_store.py::test_rewriting_the_same_key_with_different_content_is_refused` | 抛 `SnapshotConflictError` + 「被拒写入无痕（原记录仍在）」两条断言逐字覆盖。 |
| `test_snapshot_store.py::test_candidate_snapshot_conflict_cannot_be_overwritten_or_bypassed` | DELETE | 组合：`test_duckdb_snapshot_store.py::test_candidate_snapshot_conflict_refused_across_both_stores`（抛错 + 无痕）+ `test_snapshot_store.py::test_a_conflict_names_the_kind_and_the_date`（消息点名 CANDIDATE 与日期） | 逐条断言清点：抛错✓、消息含 `CANDIDATE`✓、消息含 `2026-09-04`✓、无痕✓——四条全部被他处承接，可删。执行约束：其组合权威里的 `test_a_conflict_names_the_kind_and_the_date` 与被删者同文件，**不得**随其他同族合并被改写。 |
| `test_snapshot_store.py::test_write_then_read_round_trips` | KEEP | —（套件的 `test_a_written_snapshot_reads_back` 只断言 len+symbol；`test_serialised_values_survive_the_round_trip` 只断言 date/float） | 独有断言 `status == "VALUE"`（枚举→字符串不得降级）与 `raw_value == 1_014_500.0` 不被套件承接。 |
| `test_snapshot_store.py::test_snapshot_path_is_kind_and_date_named` | KEEP | —（套件 `test_write_reports_where_the_snapshot_landed` 只断言 `path.exists()`） | JSON 落盘布局 `FACTOR/2026-09-04.json` 是 JSON 后端独有契约。 |
| `test_snapshot_store.py::test_snapshot_records_the_as_of_it_was_written_for` | KEEP | — | 「as-of 写进文件内容」是 JSON 落盘文本断言，套件无对应。 |
| `test_snapshot_store.py::test_same_snapshot_payload_is_idempotent` | KEEP | —（套件同名意图用例只断言读回 len/symbol） | 独有断言：二次写返回同一路径 + 文件字节不变。 |
| `test_snapshot_store.py::test_a_conflict_names_the_kind_and_the_date` | KEEP | — | 冲突消息点名是 Job Manifest 可读性的唯一覆盖（`test_job_manifest_validator.py` 不查快照冲突消息）。 |
| `test_snapshot_store.py::test_the_comparison_is_by_content_not_by_file_layout` | KEEP | — | 「键序/空白不是内容差异」只在 JSON 布局下可测。 |
| `test_snapshot_store.py::test_an_empty_snapshot_conflicts_with_a_measured_one` | KEEP | —（套件 `test_a_date_is_not_confused_with_an_empty_snapshot` 只断言读回空，不覆盖「空 vs 实测」冲突） | 空结果是结果、不得被后来数据替换——独有。 |

**组 1 净减量：−4（计划预算按 −6 计，缺口 −2 交 Task 15）。**

### 5.2 Task 10 十二组附加复核

台账是 Task 10 的唯一依据，故十二组逐组复核如下（计划行号均按测试名归位后核对）。

| 组 | 被删候选 | 现状 case 数 | 决策 | 权威替代（文件::测试名） | 复核结论 |
| --- | --- | --- | --- | --- | --- |
| T1 | `tests/unit/test_snapshot_store.py` JSON 专属重复 6 例 | 11 | DELETE 4 / KEEP 7 | 见 5.1.1 | 计划预估 6 例，逐条断言后仅 4 例可证被覆盖。 |
| T2 | `tests/unit/test_qualification_context.py::test_missing_approved_qualification_factor_fails_closed` | 1 | DELETE | `tests/integration/test_qualification_pipeline.py::test_growth_qualification_fails_closed_when_roe_evidence_is_missing` | 被删断言 {`absolute_pass is False`、`"roe_ttm" in risks`} ⊆ 保留者 {同上 + `qualified is False`}；保留者走生产 YAML 装配（`QUALIFIERS`），更靠近失败原因。 |
| T2b | `tests/unit/test_qualification_context.py::test_strategy_scoring_snapshot_is_not_used_as_qualification_evidence` | 1 | KEEP | —（集成例 `test_growth_qualification_uses_full_factor_evidence_beyond_scoring_snapshot` 只覆盖正向「能读到评分快照之外的 roe_ttm」，不覆盖反向分离规则） | 该例独有场景：`roe_ttm` 在评分快照里、不在 `context.factors` 里 → 必须 fail-closed；删了这条分离规则就没人守。 |
| T3 | `tests/unit/test_candidate_builder.py::test_candidate_builder_trend_weaken_under_approved_decision_e1`、`::test_candidate_builder_no_signal_under_approved_decision_f1` | 2 | KEEP | —（计划的权威 `tests/unit/test_candidate_selection_policy.py` 无任何 `next_action` 断言；`grep -rn "next_action.*==" tests/ src/` 全仓命中 5 处：`test_candidate_builder.py:186`、`test_candidate_builder.py:221`（即 T3 第二条 f1 例）、`test_candidate_discovery.py:124`、`test_api.py:189`、`test_api.py:601`——其中 builder 的决策→`next_action` 映射只由 builder 这两条钉住，`test_api.py` 的命中是字典键比较/读取，不构成该映射的权威） | builder 的决策→next_action 映射只被这两条钉住，删除即失守；无权威可指 → KEEP。 |
| T4 | `tests/integration/test_daily_pipeline.py::test_the_blocked_candidate_stage_names_the_deferred_policy` | 1 | MERGE（两状态表驱动） | 合并后 `test_daily_pipeline.py::test_the_candidate_stage_is_blocked_while_its_layers_are_missing`（表内两行：`qualifiers=None` / canonical 已装配） | 两行 scenario 不同：:147 是两层齐缺（两条 error 文案 + `candidates == ()`），:164 是「生产资格规则已装配、仅 policy Deferred」。两行断言逐行保留，不许纯 DELETE。 |
| T5 | `tests/integration/test_candidate_qualification_pipeline.py::test_no_approved_absolute_rules_blocks_build_candidates` | 1 | DELETE | `tests/integration/test_daily_pipeline.py::test_the_candidate_stage_is_blocked_while_its_layers_are_missing`（**修正**：计划写的 `test_candidate_policy.py:135` 是另一条规则——policy 缺失抛 `CandidatePolicyNotConfigured`） | 被删者白盒直调私有 `_blocked_reasons`（`src/astock_lens/pipelines/daily.py:286`，由 `:352` 真实路径调用），断言串 `"strategy qualification rules are not configured"` 在保留者 `run.error` 中逐字出现。**依赖 T4 保留 `qualifiers=None` 行**。 |
| T6 | `tests/integration/test_daily_pipeline.py::test_a_snapshot_conflict_is_recorded_in_the_job_manifest` | 1 | KEEP | —（无替代：观察点是「持久化后的 Job Store 读回」） | 全仓唯一断言**持久化** FAILED + error 的用例（`test_job_store.py:98` 是构造 helper；`test_daily_production_evidence.py:231/284/353` 断言的是内存 `result`）。计划自订「不同观察点 → KEEP」。 |
| T7 | `tests/integration/test_market_signal_pipeline.py` 流动性例 | 1 | KEEP | —（权威 `tests/unit/test_market_validator.py::test_market_validator_liquidity_veto_contradicted` 只覆盖单维规则） | 该文件仅 1 例：端到端三阶段装配 + lineage 版本断言；删「流动性例」= 删掉整条装配。 |
| T8 | `tests/unit/test_qualified_discovery.py::test_screen_qualified_returns_only_dual_pass` | 1 | KEEP | —（权威 `tests/unit/test_strategy_qualification.py::test_percentile_and_absolute_gate_must_both_pass` 在资格规则层） | 被删者守的是**发现层**「查询只返回双门槛通过项」的过滤规则；跨层去重应删规则层重复，而非发现层。 |
| T9 | `tests/integration/test_dividend_qualified_discovery.py::test_dividend_qualified_discovery_blocks_when_yield_falls_below_threshold` | 1 | KEEP | —（权威 `tests/unit/test_qualified_discovery.py::test_screen_qualified_zero_qualified_warns` 只覆盖「零通过 → 告警非空/确定性/无推荐词」） | 被删者独有断言：`coverage.percentile_pass_count == 1`、`absolute_pass_count == 0`、告警文案 `"无任何双门槛通过标的"`、dividend 门槛语义。 |
| T10 | `tests/unit/test_bootstrap_batch_fallback.py::test_a_batch_size_must_be_a_real_batch_size` | 1 | KEEP | —（冻结侧 `tests/unit/test_bootstrap_sync.py::test_a_batch_size_must_be_a_real_batch_size` 直测 `land_bar_chunks`，不是同一入口） | 被删者断言的是**公共入口** `bootstrap_liquidity_history` 对 `batch_size=0` 的拦截（wrapper 透传 batch_size 的唯一覆盖，见 `_run_flow`）；冻结文件的直测替代不了这个观察点。 |
| T11 | `tests/unit/test_cli_industry_loader.py::test_ambiguous_membership_fails_closed`；另一支 `tests/integration/test_candidate_calibration_cli.py::test_calibrate_candidates_fails_on_duplicate_symbol_in_industry_csv` | 1+1 | KEEP（两支都留） | —（权威 `tests/unit/test_industry_membership.py::test_two_industries_for_one_symbol_is_refused_not_resolved` 一个都替代不了） | 三者是**三条不同规则**：`_production_industry_map` 抛 `IndustryMembershipAmbiguous`（`src/astock_lens/cli/runtime.py:438`）vs 显式 `--industry-map` 解析的 `"duplicate symbol in industry map at row N"`（`runtime.py:616`）vs 纯规则 `build_industry_map`。「择一」的前提不成立。 |
| T12 | `tests/integration/test_daily_production_evidence.py::test_step5_qualified_symbol_insufficient_volume_bars_fails_closed` | 1 | MERGE（与 step4 合表） | 合并后 `test_daily_production_evidence.py::test_step4_qualified_symbol_missing_industry_evidence_fails_closed`（表内两行：缺失行业证据 / 有效量不足） | 两行是同一 fail-closed 规则的两个**缺失维度**输入；逐行保留 FAILED + 具体文案 + 下游未跑断言。纯 DELETE 会丢掉「有效量」维度 → 不采用。 |

**Task 10 净减量小计（按上表可达）：** T1 −4、T2 −1、T4 −1、T5 −1、T12 −1 = **−8**；
计划预算 −20，缺口 **−12** 须由 Task 15 备用池补足（不自凑数、不删未登记断言）。

### 5.3 假重复（明确 KEEP，不得以精简为名删除）

1. `tests/artifacts/validator.py` 的独立复算（不 import 生产代码，无可替代）；
2. `tests/stress/test_bootstrap_scale_properties.py` 的规模性质（4 例）；
3. `market regime` 三处 fail-closed 分别对应「无数据（`test_regime_detector_raises_when_no_data`）/
   宽度不可用（`test_r2_requires_breadth_and_index_trend`）/ 基准仅 59 根
   （`test_r2_requires_breadth_when_index_trend_present`）」三种不同上游状态——必须保持 3 条；
4. `@pytest.fixture(params=["json", "duckdb"])` 后端维度（`tests/unit/test_duckdb_snapshot_store.py`
   的 `store` fixture）——是真实的双实现覆盖，不是重复。

### 5.4 与附录 A / 计划 Task 10 的差异清单（以本文件为准）

1. **A6/组 1**：DELETE 6 → **DELETE 4**（未覆盖的 7 例各含独有断言）。
2. **A15**：7 条判定「MERGE → 3」→ **MERGE → ≤5**（3 条 fail-closed 必须独立、`:160` 保留）。
3. **A16/计划 Task 11 Step 2**：API 两条边界检查的保留方向**反转**——留 12 词文本扫描（进表），
   删 4 词 AST 测试；计划自称的「保留者是超集」实测为反向。
4. **T5**：权威从 `test_candidate_policy.py:135` 修正为
   `tests/integration/test_daily_pipeline.py::test_the_candidate_stage_is_blocked_while_its_layers_are_missing`
   （前者是另一条规则）。
5. **T3、T8、T9、T10、T11**：计划给不出覆盖全部断言的权威 → 一律 KEEP（合计 8 例不删）。
6. **T4、T12**：DELETE → **MERGE（两行表驱动）**，断言零丢失，减量不变。
7. **T11 文件不存在问题**：计划写的 `tests/unit/test_candidate_calibration_cli.py:154` 无此文件；
   同名的集成文件（`tests/integration/test_candidate_calibration_cli.py`）里也不是同一条规则。
8. **规格 §3.1 例数**：`test_extension_contracts.py` 16 → 实测 **8**；冻结总数 110 → **102**。

### 5.5 台账汇总

| 类别 | 行数 | 明细 |
| --- | --- | --- |
| MERGE | 16（附录 A）+ 2（Task 10） | A1–A5、A7–A17（含 A16 四扫描表化、A17 docs、A12/A13 artifacts 族）；T4、T12 |
| DELETE（可执行，含分属批次） | 7 | DELETE 用例 **7** = A6 的 4 + T2 1 + T5 1 + A16 的 1；按批次归属：Task 10 ×6、Task 11 ×1 |
| KEEP | 7 例（A6 内）+ 8 项（Task 10） | A6 未覆盖的 7 例；T2b、T3、T6、T7、T8、T9、T10、T11 |
| ±0 断言清理 | 3 处 | A18（用例保留） |

（MERGE 行不减少覆盖：每条断言都要求逐行保留；DELETE 行的权威替代均已给出。
按批次的可达减量：Task 10 = −8（见 5.2 小计），Task 11 = −1（4 词 AST）+ 表化收益，
其余批次按 5.1 的行内决策执行。）

---

## 6. 后续批次使用的基线数字

| 数字 | 值 | 用途 |
| --- | --- | --- |
| 基线 collected | **1298** | 所有减量口径的分子分母 |
| 基线文件数 | **136**（≤9 例 86 个） | Task 12 的合并目标 ~65 |
| 冻结用例 | **102**（5 个文件，只读） | 不参与任何删除/合并 |
| 可动用例 | **1196** | 减量分母（−20% ≈ −239，验收线 1040 = −258） |
| 覆盖率 TOTAL 行 | `TOTAL 8703 734 92%`（口径 `--cov=astock_lens --cov-report=term`，见 §3） | Task 14 用完全相同的命令对账 |
| 红项 | 无（1298 passed, 7 warnings） | 出口条件「基线全绿」达成 |

---

## 7. 减量对账与检查点修正

本节的对账框架（即「本文件修复轮」）实际落点为提交 `59119d2`（`文档：修正覆盖率测量口径并建立减量对账检查点`）；复核方式：`git show --stat 59119d2`。

### 7.1 每批可达减量与偏差

计划文字里的四批细目（−114 / −107 / −20 / −6）未计入本文件的复核结论。按 5.1/5.2/5.4
重算，逐批列出「计划预算 / 复核后可达 / 差异原因」：

| 批次 | 任务 | 计划 | 复核后可达 | 差异原因（引用本文件已有条目） |
| --- | --- | --- | --- | --- |
| 1 | Task 1–4 | −114 | −114 | 四条与附录 A 一致（5.1 无改判） |
| 2 | Task 5–9 | −107 | **−105** | Task 5：15 例按 5.1 判「拆表」为 −12；控制器裁决仍以 1 张表为目标，做到即回到 −14。Task 6：5.1 判 regime 12→≤5（8 判定收表 + 3 条 fail-closed 独立 + `:160` 保留），可多省 1（−25 而非 −24）。Task 8：5.1 实测族 15 条（复核范围 21/25 例），snapshot_validator 25→11、只省 −14 而非 −15 |
| 3 | Task 10 | −20 | **−8** | 5.2 小计：T1 −4、T2 −1、T4 −1、T5 −1、T12 −1；T3/T8/T9/T10/T11/T2b 改判 KEEP（各有独有断言、指不出权威替代） |
| 4 | Task 11 | −6 | −6 | 减量不变，方向修正：删 4 词 AST 例、保留并表化 12 词文本扫描（见 7.3） |

**复算明细（逐项可复核）：**

- 批次 1 = 72 + 17 + 11 + 14 = 114（Task 1 / 2 / 3 / 4）；
- 批次 2 = 12 + 25 + 29 + 22 + 17 = **105**（Task 5 审计侧 / 6 / 7 / 8 / 9）；
  Task 5 若达成单表（−14），批次回到 **107**（与计划数字相同，属巧合）；
- 批次 3 = 4 + 1 + 1 + 1 + 1 = 8（T1 / T2 / T4 / T5 / T12）；
- 批次 4 = 3（4 处扫描 → 1 张表）+ 1（4 词 AST）+ 2（docs 3→1）= 6；
- 四批合计：计划 −247，复核后可达 **−233**；终值预期 1298 − 233 = **1065**。

**注（残余风险）：** Task 7（−29）与 Task 9（−17）的家族未进入 5.1/5.2 台账逐条复核，
其「复核后可达」暂按计划值计（占比不小，合计 −46）；若实测与之不符，按 7.2 的判定方式
记录偏差，不得回退已完成的合并。

### 7.2 检查点数字修正（计划文字里的 1077 / 1051 作废）

| 检查点 | 计划数字 | 修正后 | 依据 |
| --- | --- | --- | --- |
| 基线 collected | 1298 | **1298** | §2 实测（`1298 tests collected`） |
| 批次 1 末（Task 4 收口） | 1184 | **1184** | 1298 − 114 |
| 批次 2 末（Task 9 收口） | 1077 | **≈1079** | 1298 − 114 − 105（Task 5 若达成单表则为 1077） |
| 批次 1–4 末（Task 11 收口） | 1051 | **≈1065** | 1298 − 114 − 105 − 8 − 6 |
| 验收线（Task 14 判定） | ≤1040 | **≤1040** | 规格 §7.1，不变 |
| Task 15 缺口 | 约 −11 | **约 −25** | 1065 − 1040；**Task 15 因此必须执行** |

**判定方式：** 每个收口点用完全相同环境运行下面这条命令，以实测数与本节数字对账，
把偏差记进本节（含方向与原因）：

```bash
UV_PROJECT_ENVIRONMENT=/Users/huangjinjin/Documents/ChatGPT/a-stock-lens/.venv UV_OFFLINE=1 PYTHONPATH= \
  uv run --no-sync pytest --collect-only -q 2>/dev/null | tail -1
```

**数字对不上时，不许为追平数字
回退已完成的合并，也不许删除未登记的断言**；某批比预期多省（例如 Task 6 的 −25）照实记录
即可，多省部分可用于抵扣 Task 15 缺口。

### 7.3 Task 11 的方向修正落到哪一行

Task 11 的两条 API 边界检查里：

- **保留** `tests/unit/test_api.py::test_api_never_imports_the_computation_engines`
  （12 词文本扫描，词表逐词抄进新的「模块 × 禁用词」总表的 `api/app.py` 行）；
- **删除** `tests/unit/test_api.py::test_api_module_imports_strictly_bounded`
  （4 词 AST：`astock_lens.pipelines` / `run_analysis` / `factor_stage` / `strategy_stage`，
  全部是上述 12 词的子集，且 import 命中必然意味着源文本命中）。

此方向与计划 Task 11 Step 2 的字面表述（「保留 AST、删文本扫描」）相反，以本文件 5.4
第 3 条为准。

---

## 8. 执行记录（每个任务完成后追加一行）

每个任务在收口时把 `pytest --collect-only -q` 的**实测**总例数、本任务实测减量与 §7.2 的
预期对账后追加一行。数字对不上时写清方向与原因；**不许为追平数字回退已完成的合并，也不许
删除未登记的断言**（见 §7.2）。

| 任务 | commit | 本任务实测减量 | 收口实测 collected | 与 §7.2 预期 | 备注 |
| --- | --- | --- | --- | --- | --- |
| Task 0 | `872e99b` + `59119d2`（本文件修复轮的落点） | 0 | 1298 | 1298 ✓ | 基线全绿；覆盖率口径修正为 `--cov=astock_lens` = 92% |
| Task 1 | `b466794` | −72 | 1226 | 1298−72=1226 ✓ | 实测与预期一致：两文件 93→21（63→15、30→6）；全量 1226 全绿 |
| Task 2 | `95032f7` | −17 | 1209 | 1226−17=1209 ✓ | 三文件 52→35（21→16、19→11、12→8），逐条断言零丢失；全量 1209 全绿 |
| Task 3 | `50a8ca9` | −11 | 1198 | 1209−11=1198 ✓ | 三文件 57→46（13→9、13→10、31→27），4 处合并逐条断言零丢失；全量 1198 全绿 |
| Task 4 | `c3957b3` | −14 | 1184 | 1198−14=1184 ✓ | 三文件 62→48（api 47→43、contract 8→3、parity 7→2），三处合并逐条断言零丢失；全量 1184 全绿。**批次 1 收口 = 1184**（1298−114），与 §7.2 检查点数字一致 |
| Task 5 | `ae5bb62` | −14 | 1170 | 1184−14=1170 ✓ | 单文件 18→4：15 条「非法 YAML 必须被拒」用例合并为表驱动 `test_invalid_rules_are_refused`；15 行的 YAML 文本、文件名与 match 片段逐字保存在文件内 `INVALID_RULE_CASES` 表（含 `growth.yaml` 身份不符行、`expected_strategy_id` / `known_factor_names` 两条带参行、一条无 match 的缺 `strategy_id` 行；原 `maximum` / `descripton` / `version:` 空值 / `version: 1` 强转 / `weight` 多余根键的 docstring 理由折进 label）；`test_missing_file_keeps_not_configured_semantics`、`test_valid_rule_loads_with_expected_fields`、`test_allowed_root_keys_still_load` 三条成功/缺文件语义用例保持独立、逐字节未改；全量 1170 全绿，Task 5 单表裁决达成（§7.2 批次 2 按单表口径计） |
| Task 6 | `bd285ba` | −25 | 1145 | 1170−25=1145 ✓ | 五文件 85→60（api 43→38 −5、csv 11→8 −3、regime 12→5 −7、validator 11→8 −3、signal 8→1 −7），逐条断言零丢失，全量 1145 全绿。**regime 12→5**：8 条判定（:20/:36/:48/:60/:72/:84/:110/:123）收 1 张表，3 条 fail-closed（`test_regime_detector_raises_when_no_data` / `test_r2_requires_breadth_and_index_trend` / `test_r2_requires_breadth_when_index_trend_present`，即 §5.3 假重复清单的三种不同上游状态）+ `:160 test_r2_b3_volatility_deferred_reason` 保持独立——前者各守一种上游状态、后者是第三观察点，均不得并表。signal 8→1：`test_signal_breakout` 的 `isinstance` + lineage 断言以行内 `signal_version` 列逐字承接，无需退化或独立保留。api 缺快照 404 族 6→1（合并名 `test_missing_snapshot_is_a_404`）：6 条均断言 404 + detail 点名，`/today` 行携带其完整消息 `no CANDIDATE snapshot for 2026-09-04`；同文件相邻的 `test_candidate_route_404s_when_nothing_was_scanned`（只断言 404）与 `test_universe_route_404s_when_no_universe_was_built`（不属于「点名快照」族的 6 条清单）保持独立未动。validator 4→1 不含 `test_market_validator_liquidity_veto_contradicted`（另一处权威，未动）。**负控证据**：5 张表共 30 行逐行单独变异，30/30 被检出且失败消息点名对应 label（详见 task-6-report.md） |
| Task 7 | `889c652` | −29 | 1116 | 1145−29=1116 ✓ | 七文件 101→72（benchmark 15→11 −4、research_audit 21→17 −4、universe 21→16 −5、dividend_yield 7→2 −5、avg_amount 10→7 −3、trailing 16→11 −5、proximity 11→8 −3），逐条断言零丢失，全量 1116 全绿。**族口径与偏差**：计划按行号预算 benchmark 15→10、research_audit 21→16、universe 21→17，但实测行号区间分别只有 5 / 5 / 6 名成员（与「省 5 / 5 / 4」隐含的 6 / 6 / 5 差 1）；按「区间内成员全部成行」执行：benchmark/audit 各少省 1（−4），universe 多省 1（−5），trailing 的 NULL 族实为 6 名（计划记省 4），多省 1；总账仍为 −29，收口 1116 与预期一致。dividend_yield 计划记「6→1 省 5」，实测该 compute 骨架共 7 名，且断言形状分两类（4 名取值/单位、3 名状态边界），拆为两张表 `test_dividend_yield_ttm_value_cases` / `test_dividend_yield_ttm_status_boundaries`（7→2），净减仍是 5。**保留格式差异而非抹平**：universe 前 4 行保原 `rules == (...)` 全等、后 2 行保原 `rule in rules` 特判；audit 4 行保 `re.search`（原 `match=`，片段含 `empty.csv` 的 `.`）、1 行保字面 `in`；dividend 4 行保 `round(..., 4)` 口径、第 7 行保精确 `== 0.0`。Task 2 已合并的 `test_return_equals_the_ratio_of_the_window_ends`（trailing）与 `test_proximity_equals_the_latest_close_over_the_window_peak` / `test_a_planted_high_pulls_proximity_below_a_flat_ratio`（proximity）本轮零改动，AST 逐字节相同。**负控证据**：7 张表共 43 行逐行单独变异，43/43 被检出且失败消息点名对应 label（详见 task-7-report.md） |
| Task 8 | `0c6426b` | −22 | 1094 | 1116−22=1094 ✓ | 两文件 36→14（snapshot 25→11 −14、job_manifest 11→3 −8），逐行谓词零丢失，全量 1094 全绿。**族口径修正**：计划按 −23 预算（snapshot 25→10、即省 15），实测并复核本族实为 **15** 名成员（`:112/:118/:136/:144/:155/:166/:176/:186/:193` 9 条 + `:279/:289/:300` 3 条 + `:368/:380/:392` 3 条），15→1 因此只省 −14，snapshot 收在 25→11；job_manifest 族 9 名（`:86/:90/:99/:105/:113/:119/:125/:138/:146`）→ 1 张表，11→3（−8）。两张表共 24 行，输入与期望逐字保留（第 10 行的 `del ref["available_at"]` 与第 15 行的 v1/v2 就地构造由命名函数承载，函数体即原语句）；**负控证据**：逐行「抹掉该 finding 代码」变异 15/15 被检出且失败消息点名行 label，另 observed 擦除变异 2/2（snapshot 10/10+1、job_manifest 5/5+1；24 行 payload 各自驱动出不同 observed，详见 task-8-report.md）。负例 6 条（snapshot `:126`/`:210`/`:271`/`:311`/`:357`/`:411`，其中 `:210` 是审计漏列的负例）、定位断言 `:242`、真实数据三例 `:431/:471/:511`，以及 job_manifest 的 `:82`/`:154` 均未动：全部非族函数 AST 逐字节相同，15+9 个被删成员与族清单完全吻合 |
| Task 9 | `8b5cb8c` | −17 | 1077 | 1094−17=1077 ✓ | 八文件 71→54（candidate_evidence 8→6、industry_market_evidence 5→2、percentile_scorer 10→8、strategy_scoring 23→20、universe_config 7→5、market_evidence 7→6、candidate_primary_strategy 5→3、command_snapshot_ownership 6→4），八族 25 名成员→8 张表各 1 条合并用例（candidate_evidence `:71/:82/:93`、industry_market_evidence `:37/:89/:105/:120`、percentile_scorer `:183/:188/:194`、strategy_scoring `:235/:240/:252/:257`、universe_config `:49/:58/:66`、market_evidence `:166/:180`、candidate_primary_strategy `:38/:47/:57`、command_snapshot_ownership `:114/:127/:170`），与任务书的 25→8 完全吻合、**无偏差**（实测 −17 = 计划 −17；收口 1077 = §7.2 修正口径 1298−114−107，Task 5 单表已回补）。**逐条谓词零丢失**：25 名成员的断言逐行落为表内期望列——`re.search` 四族（candidate_evidence / percentile_scorer / strategy_scoring / universe_config）逐字取原 `match=` 片段，industry_market_evidence 保字面 `in`，market_evidence 保 `is None`，candidate_primary_strategy 保 `==`，command_snapshot_ownership 保 `exit_code == 0` 与 `_written_snapshots(root) == ()`；99 个字面量按值/按文本全部保留，9 处 docstring（percentile ×1、universe ×2、primary_strategy ×3、command_ownership ×3）与 industry 1 处行内注释逐字折为行上注释；非族顶层函数 71 个源码段逐字节相同、基线顶层非 def 行全部仍在（`task-9-preservation-check.txt`）。command_snapshot_ownership 三行各用 `local_tmp/<label>` 子目录作快照根（原用例各拿一份新 `local_tmp`），行间不共享现场。**负控证据**：8 张表 25 行逐行单独变异期望/输入，25/25 被检出且失败消息只点名对应行 label（各文件基线自检先 PASS），另 25 行原始输入逐行 dump 出互不相同的真实信号（详见 task-9-report.md） |
| Task 10 | `55398f3` | −8 | 1069 | 1077−8=1069 ✓ | 五文件 5 处改动 = 4 条纯 DELETE + 2 组两行表驱动合并（−8），全量 1069 全绿。**6 条 DELETE 的权威替代**（`文件::测试名`，逐条断言对照见 task-10-report.md）：`tests/unit/test_snapshot_store.py::test_unwritten_date_reads_empty` → `tests/unit/test_duckdb_snapshot_store.py::test_an_absent_snapshot_reads_as_empty`；`test_snapshot_store.py::test_kinds_do_not_collide` → `test_duckdb_snapshot_store.py::test_kinds_are_kept_apart` + `::test_candidate_snapshot_conflict_refused_across_both_stores` + `::test_a_written_snapshot_reads_back`（后两条承接「恰好一条记录」的列表等值断言）；`test_snapshot_store.py::test_different_payload_for_the_same_kind_and_date_is_rejected` → `test_duckdb_snapshot_store.py::test_rewriting_the_same_key_with_different_content_is_refused`；`test_snapshot_store.py::test_candidate_snapshot_conflict_cannot_be_overwritten_or_bypassed` → 组合 `test_duckdb_snapshot_store.py::test_candidate_snapshot_conflict_refused_across_both_stores` + 同文件 `test_snapshot_store.py::test_a_conflict_names_the_kind_and_the_date`（后者按台账约束未随族改写；该文件本轮只删 4 个函数、其余 7 例逐字节未动）；`tests/unit/test_qualification_context.py::test_missing_approved_qualification_factor_fails_closed` → `tests/integration/test_qualification_pipeline.py::test_growth_qualification_fails_closed_when_roe_evidence_is_missing`（`:118`/`:120` 逐条承接，另多一条 `qualified is False`）；`tests/integration/test_candidate_qualification_pipeline.py::test_no_approved_absolute_rules_blocks_build_candidates` → `tests/integration/test_daily_pipeline.py::test_the_candidate_stage_is_blocked_while_its_layers_are_missing`（T4 合并后 `qualifiers=None` 行的 `run.error` 断言逐字含 `"strategy qualification rules are not configured"`）。**2 组合并（两行表驱动，断言行逐行保留）**：T4 `tests/integration/test_daily_pipeline.py` 的 `test_the_blocked_candidate_stage_names_the_deferred_policy` 并入 `test_the_candidate_stage_is_blocked_while_its_layers_are_missing`——`layers-missing`（两层齐缺：两条 error 文案 + `candidates == ()`）与 `policy-deferred`（生产资格规则已装配、仅候选政策 Deferred；该行原本只断言阻断 + 文案，故不额外加强 `candidates`）两行各用 `local_tmp/<label>` 作运行根、行间不共享现场；T12 `tests/integration/test_daily_production_evidence.py` 的 step5（有效量不足）并入 step4（缺失行业证据）——同一 fail-closed 规则的两个缺失维度，两行 setUp 语句由具名准备函数 `_missing_industry_evidence_case` / `_insufficient_volume_bars_case` 逐字承载，公共 `run_daily` 参数与逐条断言（DETECT_REGIME SUCCEEDED、MARKET_VALIDATE FAILED、具体文案、下游 BUILD_CANDIDATES 未跑、`candidates == 0`、无候选快照）按行保留。**KEEP 的 8 项未被碰**：T1 余 7 例、T2b、T3、T6、T7、T8、T9、T10、T11（`tests/unit/test_bootstrap_batch_fallback.py` 本轮零改动，任务书关于冻结文件的注意不适用）；5 个被改文件里未登记的顶层函数 45/45 源码段 AST 逐字节相同，未列入改动集的文件全部零 diff（`task-10-preservation-check.txt`）。**负控**：两张表 11 项变异（逐行文案改写 + 6 个谓词取反）11/11 被检出且失败消息只点名被变异那一行的 label（`task-10-negative-control.txt`）。**偏差**：计划 −20 → 实测 −8（= §5.2 小计），缺口 **−12** 记入 Task 15；差异原因见 §5.4（T3/T8/T9/T10/T11/T2b 改判 KEEP、T1 只删 4 而非 6、T4/T12 由 DELETE 改 MERGE 且减量不变） |
| Task 11 | `20baf65` | −6 | 1063 | 1069−6=1063 ✓ | 四行扫描表化 + 边界检查方向反转 + docs 3→1 + 三处恒真断言，全量 1063 全绿。**①「模块 × 禁用词」总表**落在 `tests/unit/test_financial_normalizer.py`（原 `test_the_normalizer_never_reaches_for_a_provider` 改名 `test_architecture_boundaries_hold_for_modules_and_the_watcher_script`），路径一律 `ROOT` 锚定、词表**按文件原样分列、未取并集**：`src/astock_lens/data/normalize/financials.py` 5 词（subprocess/urlopen/Runner/.fetch(/requests）、`src/astock_lens/factors/fundamental.py` 4 词（同上但无 `Runner`）、`src/astock_lens/api/app.py` 12 词（factors.builtin/strategies.momentum/AverageAmountFactor/MomentumScanner/astock_lens.pipelines/build_scanner/strategy_stage/factor_stage/run_analysis/trade_gate.engine/TradeGateEngine/ThesisAuditAdapter）、`scripts/watch-bootstrap.sh` 3 个禁用词（5301/REQUIRED=/2026-09-17）；`required` 列由第 4 行携带 1 个必须词 `manifest`（正向断言「watcher 的进度必须从本次运行的清单推导」保留）。循环遍历所有行、循环体内无 `assert`，先收集后一次性断言，失败消息点名路径与词；原四条用例的 docstring（`ARCHITECTURE.md` §4.3 两处、§2 一处）与逐行中文说明逐字折为行上注释。**②API 边界检查保留方向反转**（§5.4 第 3 条）：保留并表化 12 词文本扫描 `test_api_never_imports_the_computation_engines`，删除 4 词 AST `test_api_module_imports_strictly_bounded`（−1）。逐词核对 **4 ⊆ 12**：`astock_lens.pipelines`/`run_analysis`/`factor_stage`/`strategy_stage` 全部在 12 词内；两侧解析方式下「import 命中 ⟹ 源文本命中」成立（AST 侧取 `ast.Import.alias.name` 与 `ast.ImportFrom.module`/`alias.name`，都是源码中逐字出现的标识符文本，文本扫描是严格超集，反向不成立——注释与字符串也会命中文本扫描）→ 检测集 4 ⊊ 12，反转避免丢 8 词。另核对 `Path(api_module.__file__)` 与 `ROOT/src/astock_lens/api/app.py`：前者经共享 venv 的 editable 安装解析到主仓 `/Users/huangjinjin/Documents/ChatGPT/a-stock-lens/src/astock_lens/api/app.py`（绝对路径不同），两者 sha256 同为 `735d1b3f1edabba44e3c09bf3ab124d1bf86988cd614a4934036871fa41ff58a`、逐字节相同，换 `ROOT` 锚定后检测内容不变；`api_module` 随之成为未用导入，为过 `ruff check` 一并删除（test_api.py 中唯一超出删除函数范围的一行）。**③docs 3→1**：`tests/unit/test_docs_consistency.py` 三条用例合并为 `test_documentation_does_not_claim_stale_status`（−2），11 条过期文案逐字进表（README 4 + `docs/ROADMAP.md` 3 + `docs/REMAINING_PRODUCT_BLOCKERS.md` 4），失败消息点名 `path` 与 `phrase`，文件头中文注释与 `_repo_root()` 保留。**④三处恒真断言删除**（A18：删断言行、用例保留、±0）：`tests/unit/test_normalized_dataset_dividends.py:16`（被下一行 `ds_empty.dividend_events == ()` 蕴含）、`tests/unit/test_market_signal_readiness.py:196`（被其下 `strat.samples` 迭代蕴含）、`tests/unit/test_westock_bars.py:258`（被其下 `progress_callback(100, 5568, 97)` 调用蕴含）——逐处打开核实蕴含者仍在、用例与其余断言一字未动。**⑤批次 1–4 收口**：1298 → **1063 collected**（实测 −235），距验收线 ≤1040 尚差 **23**；收口数字与 §7.2 四批细目（−114/−107/−20/−6 = −247）相距 −12，加上验收所需 −258 的差 11，共 23，须由 Task 15 备用池补足（不自凑数、不删未登记断言）。**证据**：8 个改动文件 96 collected / 96 passed（基线 102）；四行表 24 个禁用词 + 1 个必须词逐词变异 25/25 被检出、docs 11 条文案逐条变异 11/11 被检出；`ruff check tests/` 通过、8 文件 `ruff format --check` 通过、`mypy` 167 源码文件零问题；未列入改动集的文件零 diff，`tests/unit/test_bootstrap_progress.py` 的 `ROOT` 常量按「其余用例零改动」保留（该文件因此不再引用它，无 lint 影响） |
| Task 12 | `a9ec8f7` | 0 | 1063 | 1063−0=1063 ✓ | 文件合并（净 0）：136 → 66 个含用例文件。90 个 ≤9 例源文件合并为 20 个域文件（14 计划桶 + 6 个同域长尾桶）；8 个 ≤9 例文件按 no-merge 名单保留（`test_signal_detector.py`、`test_qualification_config.py`、`tests/artifacts/*`×3、`tests/contract/*`×2、`tests/stress/*`×1）。口径说明：规格 §6 的「86 个 ≤9 例文件」为 Task-0 基线；合并时点（`20baf65`）实际 ≤9 例文件为 98 个（38 个 ≥10 例）；90 源 + 8 保留 = 98，136 − 90 + 20 = 66。文件数 66 而非 65，系 R9 裁决下保留 `test_qualification_config.py` 所致（修复轮 R1 从误合并状态还原；还原后长尾文件 12 例，全量 collect 仍 1063）。**零丢失证据（R1 前 @`a9ec8f7`）**：433/433 用例体逐字节一致、433/433 词法一致、非测试顶层定义 0 未落点、0 问题（`task-12-verify.py`，可用 `git archive 20baf65` 基线复跑，复跑结果一致）；R1 还原后 `tests/unit/test_qualification_config.py` 与 `20baf65` 逐字节一致（`git diff --no-index`），其余 90 源未触碰。case 数零变化（1063 → 1063）；全量 1063 passed 全绿；`ruff check tests/` 通过；本次触碰的 18 个测试文件 `ruff format --check` 通过（全目录检查红：`tests/unit/test_akshare_provider.py:356` 为既有未格式化文件，`20baf65` 上同样红，属冻结文件的既有漂移，非本任务引入，转 Task 14 处置）；`mypy` 通过（形式门禁：其 `files` 仅含 `src/astock_lens`，对 `tests/` 不生效）。同名 helper / 常量按域前缀重命名并同步引用点（`task-12-rename-manifest.json`），未删除任何 helper；冻结 5 文件、`tests/artifacts/*`、`tests/contract/*`、`tests/stress/*`、`test_signal_detector.py`、`conftest.py`、`support.py` 零改动。**与任务书偏差**：合并源 90 个（R1 前 91 个；任务书字面 84 个）、目标文件 20 个（计划 14 桶 + 授权长尾 6 桶）——14 桶表为推荐值，任务书明示「未能归入上表的按同域就近归并」；最终 66 个文件与任务书「约 65」差 1，系 R9 裁决保留 no-merge 权威文件所致。**执行说明**：合并由被轮次上限中断的执行代理完成，由后续会话独立复核全部证据后落账提交；修复轮 R1 还原被误合并的 `test_qualification_config.py`，长尾文件回到 12 例，并同步订正本表与 §9 |

---

## 9. Task 12 文件合并映射表

**范围**：136 → 66 个含用例文件；90 个 ≤9 例源文件（合计 429 个 `def test_*`）整体搬入 20 个域文件
（R1 前为 91 源 / 433 个定义 / 65 个文件，修复轮还原 `test_qualification_config.py` 后订正）。
搬移后 case 数零变化（1063 → 1063）；每个源文件的每个测试函数与每个非测试顶层定义均有唯一落点
（`task-12-verify.py` 复核：433/433 逐字节一致、0 未落点；该证据为 R1 前状态，R1 只还原
`test_qualification_config.py` 的 4 例、其余 90 源零改动）。

### 9.1 归属摘要表

| 目标文件 | 来源数 | 例数 | 归属理由 |
| --- | --- | --- | --- |
| `tests/unit/test_candidate_stage.py` | 8 | 41 | Candidate 阶段：构建 / 校准 / 发现 / 证据 / 政策 / 主策略 / 路由 / v2 影响 |
| `tests/unit/test_bootstrap_stage.py` | 2 | 8 | Bootstrap 阶段：扫描成本 / 调度器 |
| `tests/unit/test_quality_gates.py` | 2 | 14 | 数据质量门：日线 / 财务 |
| `tests/unit/test_dividends.py` | 4 | 11 | 分红域：覆盖 / 事件规范化 / 收益率因子 / 规范化数据集 |
| `tests/unit/test_market_stage.py` | 4 | 17 | 市场阶段：市场证据 / 行业证据 / 信号就绪 / 基准证据 |
| `tests/unit/test_cli_surface.py` | 3 | 25 | CLI 表面：cli / 行业加载 / 研究适配 |
| `tests/unit/test_valuation_stage.py` | 2 | 16 | 估值阶段：覆盖 / 规范化 |
| `tests/unit/test_calibration_stage.py` | 2 | 12 | 校准阶段：因子分布 / 资格影响 |
| `tests/unit/test_platform_basics.py` | 4 | 9 | 平台基础：settings / import / 交易日历 / 文档一致性 |
| `tests/unit/test_universe_stage.py` | 3 | 19 | Universe 阶段：配置 / 合格发现 / 发现服务 |
| `tests/unit/test_trade_gate_contracts.py` | 3 | 8 | Trade Gate 契约域唯一权威（模型 / Profile / 审计 Adapter）——任务书指定例外 |
| `tests/unit/test_trade_gate_evaluation.py` | 9 | 18 | Trade Gate 评估：context / engine / scoring / veto / store / duckdb_store / metrics / replay / service |
| `tests/unit/test_factor_long_tail.py` | 4 | 27 | 因子域长尾（均额 / 距高点 / 估值因子 / 注册表）——同域就近归并 |
| `tests/unit/test_strategy_long_tail.py` | 5 | 29 | 策略域长尾（动量扫描 / 扫描器 / 因子索引 / 平价 / 百分位）——同域就近归并 |
| `tests/unit/test_qualification_long_tail.py` | 2 | 12 | 资格域长尾（上下文 / 资格扫描）——同域就近归并 |
| `tests/unit/test_market_long_tail.py` | 2 | 13 | 市场域长尾（regime / validator）——同域就近归并 |
| `tests/unit/test_data_long_tail.py` | 2 | 15 | 数据域长尾（CSV 安全规范化 / 快照存储）——同域就近归并 |
| `tests/unit/test_platform_long_tail.py` | 2 | 10 | 平台 / 工具域长尾（领域模型 / Jev 分诊）——同域就近归并 |
| `tests/integration/test_cli_entry_flows.py` | 12 | 61 | 集成层 CLI 入口流程 |
| `tests/integration/test_pipeline_flows.py` | 15 | 64 | 集成层 pipeline / workflow 流程 |

合计 90 个来源、429 例；其中 6 个长尾桶为任务书授权的「同域就近归并」落点。

> 注：`test_qualification_config.py`（4 例）为 no-merge 权威文件，修复轮 R1 已从 `test_qualification_long_tail.py` 中还原；`tests/unit/test_qualification_config.py` 保持独立存在。

### 9.2 逐源映射（源文件 → 目标文件 → 用例名；RENAME 行为同名 helper / 常量 / 夹具的域前缀改名）

```text
# 源文件 -> 目标文件（Task 12）

tests/unit/test_candidate_builder.py -> tests/unit/test_candidate_stage.py  (8)
    test_next_action_defaults_to_the_inert_choice
    test_signal_and_market_validation_stay_unset
    test_lineage_mismatch_is_refused
    test_reasons_and_risks_are_aggregated_from_evidence
    test_candidate_is_a_research_object_not_a_recommendation
    test_candidate_lineage_carries_complete_stage_versions
    test_candidate_builder_trend_weaken_under_approved_decision_e1
    test_candidate_builder_no_signal_under_approved_decision_f1
    RENAME LINEAGE -> BLD_LINEAGE
tests/unit/test_candidate_calibration.py -> tests/unit/test_candidate_stage.py  (5)
    test_empty_industry_map_raises_value_error
    test_calibration_report_statistics_and_warning
    test_deterministic_rendering_byte_for_byte
    test_the_report_still_builds_without_the_new_evidence_fields
    test_the_denominator_is_the_scored_population_not_the_industry_map
    RENAME AS_OF -> CALIBRATION_AS_OF
    RENAME LINEAGE -> CALIBRATION_LINEAGE
tests/unit/test_candidate_discovery.py -> tests/unit/test_candidate_stage.py  (5)
    test_screen_candidates_preserves_stored_authoritative_order
    test_screen_candidates_extracts_primary_and_all_qualified_strategies
    test_screen_candidates_keeps_signal_risks_visible
    test_screen_candidates_respects_limit_and_tracks_total_count
    test_screen_candidates_empty_records
    RENAME AS_OF -> DISCOVERY_AS_OF
tests/unit/test_candidate_evidence.py -> tests/unit/test_candidate_stage.py  (6)
    test_candidate_evidence_valid_construction
    test_candidate_evidence_rejects_invalid_constructions
    test_candidate_evidence_allows_none_for_market_and_signal_representation
    test_candidate_selection_immutability_and_fields
    test_candidate_builder_assembles_from_selection_and_evidence
    test_candidate_builder_rejects_symbol_mismatch
    RENAME AS_OF -> EVIDENCE_AS_OF
tests/unit/test_candidate_policy.py -> tests/unit/test_candidate_stage.py  (6)
    test_cross_sectional_policy_protocol_conformance
    test_no_reviewed_policy_is_an_error_not_an_empty_scan
    test_the_policy_is_what_makes_a_candidate
    test_score_does_not_override_a_rejecting_policy
    test_the_builder_does_not_derive_next_action_from_a_score
    test_a_policy_verdict_is_ineligible_without_eligible_evidence
    RENAME AS_OF -> POLICY_AS_OF
    RENAME _qualification -> _policy_qualification
    RENAME _result -> _policy_result
tests/unit/test_candidate_primary_strategy.py -> tests/unit/test_candidate_stage.py  (3)
    test_primary_qualified_strategy_selection_rules
    test_no_qualified_strategy_raises_explicit_value_error
    test_candidate_model_carries_primary_strategy_id
    RENAME AS_OF -> PRIMARY_STRATEGY_AS_OF
tests/unit/test_candidate_routing.py -> tests/unit/test_candidate_stage.py  (5)
    test_a_qualified_verdict_routes_to_watch
    test_an_unqualified_verdict_routes_to_ignore
    test_only_two_of_the_four_actions_are_reachable
    test_the_routed_action_reaches_a_candidate
    test_score_routing_api_is_absent
    RENAME AS_OF -> ROUTING_AS_OF
    RENAME _result -> _routing_result
tests/unit/test_candidate_v2_impact.py -> tests/unit/test_candidate_stage.py  (3)
    test_compute_candidate_v2_impact_explicit_counts
    test_candidate_v2_impact_markdown_render
    test_candidate_v2_impact_cli_execution_and_read_only
    RENAME AS_OF -> V2_IMPACT_AS_OF
    RENAME _factor -> _v2_impact_factor
    RENAME _qual -> _v2_impact_qual
tests/unit/test_bootstrap_scan_cost.py -> tests/unit/test_bootstrap_stage.py  (4)
    test_the_flow_reads_the_landed_file_a_constant_number_of_times
    test_the_first_window_is_wide_enough_to_finish_in_one_round
    test_one_hung_symbol_must_not_block_the_whole_chunk
    test_a_symbol_that_already_has_enough_bars_is_not_fetched_again
    RENAME END_DATE -> SCAN_COST_END_DATE
tests/unit/test_bootstrap_scheduler.py -> tests/unit/test_bootstrap_stage.py  (4)
    test_fast_later_symbol_is_checkpointed_before_slow_first_symbol
    test_max_inflight_is_bounded_for_5300_fake_symbols
    test_all_hanging_akshare_workers_are_terminated_without_serial_timeouts
    test_all_success_requests_do_not_exceed_symbol_count
    RENAME AS_OF -> SCHEDULER_AS_OF
    RENAME BAR_COLUMNS -> SCHEDULER_BAR_COLUMNS
tests/unit/test_daily_bar_quality_gate.py -> tests/unit/test_quality_gates.py  (6)
    test_clean_dataset_passes_with_no_issues
    test_each_documented_rule_fires_on_the_dirty_fixture
    test_invalid_findings_are_p2_and_do_not_block_a_scan
    test_empty_dataset_is_a_blocking_p1
    test_valid_bars_excludes_only_the_flagged_ones
    test_gate_does_not_mutate_its_input
tests/unit/test_financial_quality_gate.py -> tests/unit/test_quality_gates.py  (8)
    test_a_clean_observation_produces_no_findings
    test_a_missing_value_is_null_not_a_defect
    test_an_unreadable_cell_makes_the_key_invalid
    test_a_duplicated_key_is_invalid_and_dropped_together
    test_different_periods_are_not_duplicates
    test_an_empty_statement_is_a_blocking_p1_finding
    test_a_single_bad_measurement_does_not_block_a_whole_market_scan
    test_findings_carry_the_key_a_reader_needs
    RENAME AS_OF -> FIN_AS_OF
tests/unit/test_dividend_coverage.py -> tests/unit/test_dividends.py  (4)
    test_explicit_universe_denominator_required
    test_status_split_and_coverage_metrics
    test_deterministic_report_rendering
    test_dividend_coverage_cli_read_only
    RENAME SHANGHAI -> COVERAGE_SHANGHAI
    RENAME AS_OF -> COV_AS_OF
tests/unit/test_dividend_event_normalizer.py -> tests/unit/test_dividends.py  (4)
    test_parse_implemented_dividend_event
    test_parse_proposal_event_preserves_source_status
    test_missing_dates_remain_none
    test_source_evidence_preservation
tests/unit/test_dividend_yield_factor.py -> tests/unit/test_dividends.py  (2)
    test_dividend_yield_ttm_value_cases
    test_dividend_yield_ttm_status_boundaries
    RENAME SHANGHAI -> YIELD_FACTOR_SHANGHAI
    RENAME AS_OF -> YIELD_FACTOR_AS_OF
tests/unit/test_normalized_dataset_dividends.py -> tests/unit/test_dividends.py  (1)
    test_normalized_dataset_supports_dividend_events
    RENAME SHANGHAI -> ND_SHANGHAI
    RENAME AS_OF -> NORMALIZED_DATASET_AS_OF
tests/unit/test_market_evidence.py -> tests/unit/test_market_stage.py  (6)
    test_build_stock_market_evidence_computes_exact_volume_ratio
    test_fewer_than_20_bars_returns_none_volume_ratio
    test_future_bars_are_strictly_excluded
    test_missing_or_error_factors_become_none
    test_relative_strength_60d_exact_calculation
    test_missing_relative_strength_inputs_result_in_none
    RENAME AS_OF -> MARKET_EVIDENCE_AS_OF
tests/unit/test_industry_market_evidence.py -> tests/unit/test_market_stage.py  (2)
    test_industry_evidence_unavailable_rejections
    test_exact_industry_excess_calculation
    RENAME AS_OF -> INDUSTRY_EVIDENCE_AS_OF
tests/unit/test_market_signal_readiness.py -> tests/unit/test_market_stage.py  (5)
    test_deterministic_quantiles_under_different_input_orders
    test_missing_values_never_become_zero
    test_scope_strictly_restricted_to_qualified_stocks
    test_representative_sampling_deterministic_with_tie_breaking
    test_assert_vocabulary_boundary_no_verdict_fields
    RENAME AS_OF -> SIGNAL_READINESS_AS_OF
tests/unit/test_benchmark_evidence.py -> tests/unit/test_market_stage.py  (4)
    test_compute_benchmark_evidence_exact_calculation
    test_insufficient_bars_raises_benchmark_evidence_unavailable
    test_empty_bars_raises_benchmark_evidence_unavailable
    test_future_bars_strictly_excluded
tests/unit/test_cli.py -> tests/unit/test_cli_surface.py  (9)
    test_cli_help
    test_doctor_reports_the_factor_set_and_its_weights
    test_factors_compute_prints_one_document_per_symbol_and_factor
    test_scan_reports_a_ranking_and_writes_no_snapshot
    test_scan_reports_every_candidate_with_a_score
    test_universe_build_reports_the_verdicts_without_writing
    test_scan_rejects_a_malformed_date
    test_calendar_commands_report_trading_status
    test_sync_research_on_non_trading_day_skips_market_sync
tests/unit/test_cli_industry_loader.py -> tests/unit/test_cli_surface.py  (7)
    test_step1_exact_date
    test_step2_latest_prior_date
    test_step3_future_date_exclusion
    test_step4_no_data_raises_file_not_found
    test_ambiguous_membership_fails_closed
    test_ignores_non_iso_date_csv
    test_includes_supplemental_industry_memberships
tests/unit/test_cli_research_adapter.py -> tests/unit/test_cli_surface.py  (9)
    test_submit_returns_the_job_the_command_reported
    test_the_request_travels_to_the_command_unchanged
    test_status_passes_the_state_through_unchanged
    test_result_returns_the_summary_and_the_artifact_reference
    test_an_unconfigured_command_is_refused_by_name
    test_the_command_is_read_from_the_environment
    test_a_failing_command_reports_the_failure_instead_of_a_result
    test_unreadable_output_is_refused_instead_of_guessed
    test_an_incomplete_payload_is_refused
tests/unit/test_valuation_coverage.py -> tests/unit/test_valuation_stage.py  (8)
    test_an_uncollected_symbol_is_uncovered_not_zero
    test_a_strategy_needs_every_valuation_factor_it_declares
    test_a_future_observation_does_not_count_at_this_point_in_time
    test_a_non_positive_multiple_is_not_scoreable
    test_a_strategy_without_factor_configs_fails_instead_of_approximating
    test_an_empty_universe_is_refused
    test_a_strategy_without_valuation_factors_is_not_reported_as_covered
    test_the_report_serializes_to_json_shape
    RENAME ROOT -> COVERAGE_ROOT
    RENAME AS_OF -> COVERAGE_AS_OF
tests/unit/test_valuation_normalizer.py -> tests/unit/test_valuation_stage.py  (8)
    test_the_daily_series_becomes_dated_observations
    test_the_header_metrics_borrow_the_newest_series_date
    test_a_categorical_label_is_evidence_not_a_number
    test_missing_markers_never_become_zero
    test_every_metric_declares_a_unit_or_is_a_label
    test_a_sector_block_without_a_series_is_dated_at_the_query_day
    test_an_empty_source_reports_its_status_instead_of_inventing_rows
    test_a_block_without_an_instrument_is_reported_not_guessed
tests/unit/test_calibration_factor_distribution.py -> tests/unit/test_calibration_stage.py  (7)
    test_quantiles_come_from_value_observations_only
    test_a_factor_with_no_values_reports_no_quantiles
    test_samples_carry_score_percentile_and_factor_evidence
    test_the_report_records_the_population_it_was_computed_on
    test_the_boundary_reports_rank_and_score_as_two_separate_numbers
    test_a_decision_grade_report_refuses_incomplete_industry_coverage
    test_rendering_is_byte_stable_under_shuffled_input
tests/unit/test_qualification_impact.py -> tests/unit/test_calibration_stage.py  (5)
    test_counts_are_computed_independently
    test_failure_reasons_aggregate_by_factor
    test_boundary_samples_are_deterministic
    test_qualifier_without_absolute_rule_fails_loudly
    test_unrecognized_risk_text_is_not_dropped
    RENAME AS_OF -> QUALIFICATION_IMPACT_AS_OF
    RENAME _factor -> _qi_factor
    RENAME _result -> _qi_result
tests/unit/test_settings.py -> tests/unit/test_platform_basics.py  (1)
    test_load_app_config_reads_local_storage_paths
tests/unit/test_import.py -> tests/unit/test_platform_basics.py  (1)
    test_package_imports
tests/unit/test_trading_calendar.py -> tests/unit/test_platform_basics.py  (6)
    test_regular_weekday_is_trade_date
    test_weekend_is_not_trade_date
    test_statutory_holiday_is_not_trade_date
    test_latest_trade_date_on_trade_date_returns_self
    test_latest_trade_date_on_weekend_returns_previous_friday
    test_custom_dates_override
tests/unit/test_docs_consistency.py -> tests/unit/test_platform_basics.py  (1)
    test_documentation_does_not_claim_stale_status
tests/unit/test_universe_config.py -> tests/unit/test_universe_stage.py  (5)
    test_repository_config_loads
    test_liquidity_floor_carries_the_owner_supplied_value
    test_long_suspension_is_deferred_not_defaulted
    test_broken_configurations_are_refused
    test_digest_is_stable_and_content_sensitive
tests/unit/test_qualified_discovery.py -> tests/unit/test_universe_stage.py  (6)
    test_screen_qualified_returns_only_dual_pass
    test_screen_qualified_deterministic_order
    test_screen_qualified_coverage_before_limit
    test_screen_qualified_zero_qualified_warns
    test_screen_qualified_missing_qualifier_fails_loudly
    test_qualified_screen_query_rejects_non_positive_limit
    RENAME _strategy_result -> _qualified_strategy_result
tests/unit/test_discovery_service.py -> tests/unit/test_universe_stage.py  (8)
    test_screen_strategy_orders_ranked_results_best_first
    test_screen_strategy_tie_breaking_order
    test_screen_strategy_missing_values_order_and_preservation
    test_screen_strategy_filters
    test_screen_strategy_query_validation
    test_screen_strategy_coverage_calculated_before_filters
    test_summarize_strategies
    test_summarize_strategies_empty
    RENAME AS_OF -> DISCOVERY_AS_OF
tests/unit/test_trade_gate_models.py -> tests/unit/test_trade_gate_contracts.py  (3)
    test_trade_gate_vocab_is_exact
    test_trade_intent_rejects_naive_time
    test_risk_proposal_computes_loss_without_inventing_account_limit
tests/unit/test_trade_gate_profiles.py -> tests/unit/test_trade_gate_contracts.py  (2)
    test_profiles_sum_to_100_and_use_fixed_thresholds
    test_invalid_weight_total_is_rejected
tests/unit/test_trade_gate_audit_adapter.py -> tests/unit/test_trade_gate_contracts.py  (3)
    test_phase_one_does_not_receive_thesis
    test_confidence_adjustment_is_exact
    test_adapter_rejects_invalid_output
tests/unit/test_trade_gate_context.py -> tests/unit/test_trade_gate_evaluation.py  (3)
    test_eod_snapshot_does_not_invent_intraday_facts
    test_overlay_facts_are_explicitly_carried
    test_missing_all_snapshots_is_distinguished
    RENAME NOW -> CTX_NOW
tests/unit/test_trade_gate_engine.py -> tests/unit/test_trade_gate_evaluation.py  (2)
    test_event_without_intraday_evidence_waits
    test_hard_veto_overrides_high_weighted_score
    RENAME _intent -> _engine_intent
tests/unit/test_trade_gate_scoring.py -> tests/unit/test_trade_gate_evaluation.py  (3)
    test_event_sector_and_relative_strength_mapping
    test_swing_rr_is_reward_risk_transform
    test_position_reuses_strategy_percentiles
    RENAME NOW -> SCORING_NOW
tests/unit/test_trade_gate_veto.py -> tests/unit/test_trade_gate_evaluation.py  (3)
    test_vetoes_include_upstream_hard_blocks_and_missing_confirmation
    test_losing_add_without_independent_confirmation_is_hard_veto
    test_absent_invalidation_is_recorded_as_hard_veto
tests/unit/test_trade_gate_store.py -> tests/unit/test_trade_gate_evaluation.py  (2)
    test_same_day_multiple_evaluations_are_append_only
    test_same_id_is_idempotent_only_for_identical_content
    RENAME NOW -> STORE_NOW
    RENAME _intent -> _store_intent
tests/unit/test_trade_gate_duckdb_store.py -> tests/unit/test_trade_gate_evaluation.py  (2)
    test_duckdb_store_round_trips_intent_and_read_does_not_create
    test_duckdb_reads_missing_trade_table_as_empty
tests/unit/test_trade_gate_metrics.py -> tests/unit/test_trade_gate_evaluation.py  (1)
    test_metrics_report_override_rate_and_group_results
tests/unit/test_trade_gate_replay.py -> tests/unit/test_trade_gate_evaluation.py  (1)
    test_replay_uses_stored_context_and_assigns_new_versions
tests/unit/test_trade_gate_service.py -> tests/unit/test_trade_gate_evaluation.py  (1)
    test_override_requires_smaller_size_evidence_ack_and_stop
    RENAME NOW -> SERVICE_NOW
tests/unit/test_avg_amount_factor.py -> tests/unit/test_factor_long_tail.py  (7)
    test_metadata_comes_from_the_config_file
    test_window_completeness_decides_value_or_null
    test_bars_after_as_of_are_excluded
    test_result_carries_its_version_and_lineage
    test_config_without_a_window_is_rejected
    test_config_for_another_factor_is_rejected
    test_unknown_symbol_is_null
    RENAME CSV_ROOT -> AVG_AMOUNT_CSV_ROOT
tests/unit/test_proximity_high_factor.py -> tests/unit/test_factor_long_tail.py  (8)
    test_proximity_equals_the_latest_close_over_the_window_peak
    test_a_planted_high_pulls_proximity_below_a_flat_ratio
    test_proximity_never_exceeds_one
    test_a_falling_symbol_sits_far_below_its_peak
    test_missing_high_or_insufficient_window_is_null
    test_metadata_and_window_come_from_the_configuration
    test_a_configuration_without_a_window_is_an_error
    test_a_configuration_for_another_factor_is_rejected
    RENAME _config -> _proximity_config
tests/unit/test_valuation_factors.py -> tests/unit/test_factor_long_tail.py  (8)
    test_a_positive_multiple_is_a_value
    test_a_non_positive_multiple_is_not_applicable
    test_a_zero_percentile_is_still_a_value
    test_a_symbol_that_never_reports_the_metric_is_not_applicable
    test_a_metric_reported_only_after_the_point_in_time_is_null
    test_the_newest_available_day_wins
    test_a_reviewed_freshness_bound_switches_stale_on
    test_the_freshness_key_must_be_declared
    RENAME _context -> _valuation_context
    RENAME ROOT -> VALUATION_ROOT
    RENAME AS_OF -> VALUATION_AS_OF
tests/unit/test_factor_registry.py -> tests/unit/test_factor_long_tail.py  (4)
    test_registration_preserves_order
    test_duplicate_registration_is_rejected
    test_unknown_lookup_is_rejected
    test_registered_factor_is_returned_by_name
    RENAME CONFIG_PATH -> REGISTRY_CONFIG_PATH
    RENAME _factor -> _registry_factor
tests/unit/test_momentum_scanner.py -> tests/unit/test_strategy_long_tail.py  (9)
    test_required_factors_come_from_the_config_file
    test_eligible_when_every_required_factor_has_a_value
    test_missing_factor_makes_the_symbol_ineligible
    test_null_factor_makes_the_symbol_ineligible
    test_scoring_is_explicitly_absent_for_a_lone_symbol
    test_score_result_keeps_its_evidence
    test_ineligible_context_is_carried_into_risks
    test_explain_reports_per_factor_notes
    test_explain_reports_a_missing_value_as_missing
    RENAME AS_OF -> MOMENTUM_AS_OF
    RENAME _scanner -> _momentum_scanner
    RENAME _context -> _momentum_context
tests/unit/test_strategy_scanners.py -> tests/unit/test_strategy_long_tail.py  (6)
    test_the_class_is_its_own
    test_the_required_factors_match_the_configuration
    test_scoring_one_symbol_alone_reports_no_score
    test_a_missing_factor_makes_the_symbol_ineligible_with_a_reason
    test_the_explanation_reaches_factor_level
    test_the_cross_section_ranks_exactly_the_eligible_population
    RENAME AS_OF -> SCANNERS_AS_OF
    RENAME _context -> _scanners_context
    RENAME ROOT -> SCANNERS_ROOT
    RENAME CONFIGS -> SCANNERS_CONFIGS
tests/unit/test_strategy_factor_index.py -> tests/unit/test_strategy_long_tail.py  (4)
    test_the_index_answers_exactly_like_a_naive_scan
    test_the_index_separates_symbols_and_keeps_input_order
    test_strategy_stage_hands_each_symbol_its_own_factor_results
    test_factor_results_are_walked_once_per_stage_not_once_per_scanner
tests/unit/test_strategy_parity.py -> tests/unit/test_strategy_long_tail.py  (2)
    test_the_refactored_scanner_reproduces_the_recorded_output
    test_the_fixture_was_recorded_before_this_refactor
    RENAME AS_OF -> PARITY_AS_OF
    RENAME _factor_result -> _parity_factor_result
    RENAME SYMBOLS -> PARITY_SYMBOLS
tests/unit/test_percentile_scorer.py -> tests/unit/test_strategy_long_tail.py  (8)
    test_a_negative_weight_orients_a_factor_where_lower_is_better
    test_the_orientation_is_visible_in_the_contribution
    test_an_ineligible_symbol_shifts_nobody_else
    test_a_single_symbol_population_gets_a_score_but_no_rank
    test_no_contexts_means_no_results
    test_the_caller_supplies_the_eligibility_rule
    test_the_explanation_shows_each_factor_and_its_weight
    test_invalid_weight_sets_are_refused
    RENAME AS_OF -> PERCENTILE_AS_OF
tests/unit/test_qualification_context.py -> tests/unit/test_qualification_long_tail.py  (3)
    test_growth_qualification_can_read_non_scoring_roe_factor
    test_strategy_scoring_snapshot_is_not_used_as_qualification_evidence
    test_qualification_context_defaults_to_no_factors
    RENAME AS_OF -> QUALIFICATION_CONTEXT_AS_OF
tests/unit/test_eligibility_scanner.py -> tests/unit/test_qualification_long_tail.py  (9)
    test_a_symbol_with_every_required_factor_is_eligible
    test_the_verdict_never_carries_a_score
    test_a_missing_factor_makes_the_symbol_ineligible_and_says_which
    test_any_status_other_than_value_is_not_eligible
    test_a_population_gets_one_verdict_each_and_no_ranking
    test_the_explanation_states_that_scoring_is_deferred
    test_a_scanner_must_declare_what_it_requires
    test_a_configured_scanner_with_weights_is_refused_here
    test_the_result_carries_the_configured_identity
tests/unit/test_market_regime.py -> tests/unit/test_market_long_tail.py  (5)
    test_regime_detector_judgements
    test_regime_detector_raises_when_no_data
    test_r2_requires_breadth_and_index_trend
    test_r2_requires_breadth_when_index_trend_present
    test_r2_b3_volatility_deferred_reason
tests/unit/test_market_validator.py -> tests/unit/test_market_long_tail.py  (8)
    test_market_validator_liquidity_veto_contradicted
    test_market_validator_status_matrix
    test_market_validator_lineage_contains_market_validation_version
    test_market_validator_relative_strength_negative_adds_risk
    test_market_validator_missing_context_dimensions_raise
    test_market_validator_missing_trend_or_liquidity_factors_raise
    test_market_validator_non_momentum_allows_missing_proximity_52w_high
    test_market_validator_multiple_missing_factors_reported
    RENAME SHANGHAI -> MARKET_VALIDATOR_SHANGHAI
    RENAME AS_OF -> MARKET_VALIDATOR_AS_OF
tests/unit/test_csv_security_normalizer.py -> tests/unit/test_data_long_tail.py  (8)
    test_every_row_of_the_fixture_becomes_a_profile
    test_flags_are_parsed_as_booleans
    test_listing_date_and_suspension_count_are_typed
    test_unreadable_identity_cells_reject_the_row
    test_an_absent_suspension_count_is_missing_not_rejected
    test_a_rejected_row_does_not_discard_its_neighbours
    test_a_naive_as_of_is_rejected
    test_an_empty_payload_yields_no_profiles_and_no_failures
    RENAME AS_OF -> CSV_SECURITY_AS_OF
tests/unit/test_snapshot_store.py -> tests/unit/test_data_long_tail.py  (7)
    test_write_then_read_round_trips
    test_snapshot_path_is_kind_and_date_named
    test_snapshot_records_the_as_of_it_was_written_for
    test_same_snapshot_payload_is_idempotent
    test_a_conflict_names_the_kind_and_the_date
    test_the_comparison_is_by_content_not_by_file_layout
    test_an_empty_snapshot_conflicts_with_a_measured_one
tests/unit/test_domain_models.py -> tests/unit/test_platform_long_tail.py  (5)
    test_financial_observation_rejects_future_availability
    test_architecture_enums_are_explicit
    test_missing_financial_value_stays_none
    test_naive_timestamps_are_rejected
    test_watchlist_states_keep_active_and_reserved_apart
tests/unit/test_jev_triage.py -> tests/unit/test_platform_long_tail.py  (5)
    test_classify_test_failure_returns_choice_and_metadata
    test_missing_api_key_fails_gracefully
    test_sdk_error_fails_gracefully
    test_unknown_choice_is_not_silently_accepted
    test_to_dict_has_stable_json_shape
tests/integration/test_calibration_readiness_cli.py -> tests/integration/test_cli_entry_flows.py  (9)
    test_the_canonical_research_analysis_never_scores_an_excluded_symbol
    test_the_calibration_command_reports_the_population_it_used
    test_an_external_map_missing_one_symbol_still_produces_the_diagnostic
    test_the_canonical_map_missing_one_symbol_is_still_refused
    test_a_complete_canonical_map_records_its_own_date_and_origin
    test_future_membership_records_never_enter_the_historical_canonical_map
    test_a_declared_mapping_date_is_recorded_verbatim
    test_a_mapping_date_without_a_timezone_is_refused
    test_a_mapping_date_without_an_external_map_is_refused
    RENAME AS_OF -> READINESS_CLI_AS_OF
tests/integration/test_candidate_calibration_cli.py -> tests/integration/test_cli_entry_flows.py  (6)
    test_calibrate_cli_help
    test_calibrate_candidates_generates_reports_without_production_mutation
    test_calibrate_candidates_fails_on_missing_industry_file
    test_calibrate_candidates_fails_on_duplicate_symbol_in_industry_csv
    test_calibrate_candidates_fails_on_missing_header_in_industry_csv
    test_calibrate_candidates_canonical_merges_supplement
    RENAME ROOT -> CALIBRATION_CLI_ROOT
tests/integration/test_candidates_cli.py -> tests/integration/test_cli_entry_flows.py  (4)
    test_candidates_cli_missing_snapshot_fails_explicitly
    test_candidates_cli_published_empty_snapshot_exits_zero
    test_candidates_cli_displays_expected_columns_in_stored_order
    test_candidates_cli_is_strictly_read_only
    RENAME AS_OF -> CANDIDATES_CLI_AS_OF
tests/integration/test_command_snapshot_ownership.py -> tests/integration/test_cli_entry_flows.py  (4)
    test_factors_compute_does_not_touch_the_formal_candidate_snapshot
    test_read_only_commands_write_no_formal_snapshot
    test_scan_leaves_every_formal_snapshot_untouched
    test_scan_does_not_replace_a_formal_candidate_snapshot
    RENAME ROOT -> SNAPSHOT_OWNERSHIP_ROOT
    RENAME CSV_ROOT -> SNAPSHOT_OWNERSHIP_CSV_ROOT
    RENAME DAY -> SNO_DAY
    RENAME LONG_DATASET -> SNAPSHOT_OWNERSHIP_LONG_DATASET
tests/integration/test_dividend_sync_cli.py -> tests/integration/test_cli_entry_flows.py  (3)
    test_sync_dividends_partial_response_resume
    test_sync_dividends_stops_on_no_progress
    test_sync_dividends_landed_blocks_survive_later_rounds
    RENAME AS_OF -> DIV_AS_OF
    RENAME DAY -> DIVIDEND_SYNC_DAY
tests/integration/test_market_signal_readiness_cli.py -> tests/integration/test_cli_entry_flows.py  (3)
    test_missing_snapshot_exits_nonzero
    test_read_only_and_deterministic_output
    test_invalid_qualification_config_fails_loudly
    RENAME AS_OF -> SIGNAL_READINESS_CLI_AS_OF
tests/integration/test_qualification_impact_cli.py -> tests/integration/test_cli_entry_flows.py  (2)
    test_qualification_impact_cli_is_read_only
    test_qualification_impact_cli_fails_on_missing_snapshot
    RENAME DAY -> IMPACT_CLI_DAY
tests/integration/test_qualified_cli.py -> tests/integration/test_cli_entry_flows.py  (9)
    test_qualified_cli_help
    test_qualified_only_dual_pass_displayed
    test_qualified_top_limit_truncates_items_not_coverage
    test_qualified_missing_factor_snapshot
    test_qualified_missing_strategy_snapshot
    test_qualified_invalid_config_fails_closed
    test_qualified_unknown_strategy_fails_loudly
    test_qualified_dividend_zero_result_warns
    test_qualified_read_only_guarantee
    RENAME Result -> TyperResult
    RENAME AS_OF -> QUALIFIED_CLI_AS_OF
    RENAME DAY -> QUALIFIED_CLI_DAY
    RENAME _invoke -> _qualified_cli_invoke
    RENAME _factor -> _qualified_cli_factor
tests/integration/test_screen_cli.py -> tests/integration/test_cli_entry_flows.py  (9)
    test_screen_cli_help
    test_screen_mixed_strategy_snapshot_top_limit
    test_screen_missing_snapshot
    test_screen_unknown_strategy
    test_screen_low_coverage_warning
    test_screen_high_coverage_no_warning
    test_screen_eligible_filter_and_all_results_flag
    test_screen_min_percentile_filter
    test_screen_read_only_guarantee
    RENAME AS_OF -> SCR_AS_OF
    RENAME DAY -> SCREEN_CLI_DAY
    RENAME _invoke -> _screen_cli_invoke
    RENAME SHANGHAI -> SCREEN_CLI_SHANGHAI
    RENAME _strategy_result -> _screen_cli_strategy_result
tests/integration/test_today_cli.py -> tests/integration/test_cli_entry_flows.py  (4)
    test_today_cli_missing_snapshot_fails_explicitly
    test_today_cli_empty_snapshot_exits_zero
    test_today_cli_exact_aggregation_and_top_order
    test_today_cli_is_strictly_read_only
    RENAME AS_OF -> TODAY_CLI_AS_OF
    RENAME runner -> today_cli_runner
    RENAME _make_candidate -> _today_cli_make_candidate
tests/integration/test_trade_gate_cli.py -> tests/integration/test_cli_entry_flows.py  (1)
    test_trade_commands_are_registered
tests/integration/test_valuation_backfill_cli.py -> tests/integration/test_cli_entry_flows.py  (7)
    test_rounds_merge_and_every_round_only_asks_what_is_missing
    test_a_gap_that_does_not_close_stops_and_exits_non_zero
    test_a_covered_symbol_is_not_asked_again
    test_a_missing_universe_file_is_an_error_not_an_empty_run
    test_a_non_positive_batch_size_is_refused
    test_the_coverage_command_reports_the_universe_as_the_denominator
    test_the_coverage_command_refuses_an_empty_universe
    RENAME ROOT -> VALUATION_BACKFILL_ROOT
    RENAME DAY -> VBF_DAY
    RENAME _invoke -> _valuation_backfill_invoke
tests/integration/test_analysis_pipeline.py -> tests/integration/test_pipeline_flows.py  (9)
    test_the_analysis_returns_factors_a_universe_and_strategy_results
    test_the_analysis_writes_nothing
    test_the_daily_pipeline_uses_the_same_business_steps
    test_every_designed_universe_exclusion_fires_on_its_symbol
    test_the_deferred_suspension_rule_is_reported_not_applied
    test_the_ranking_matches_the_hand_computed_order
    test_only_universe_symbols_enter_the_strategies
    test_short_history_is_null_rather_than_a_number
    test_a_missing_input_never_became_zero
    RENAME ROOT -> ANALYSIS_ROOT
    RENAME CONFIGS -> ANALYSIS_CONFIGS
    RENAME AS_OF -> ANALYSIS_AS_OF
    RENAME LONG_DATASET -> ANALYSIS_LONG_DATASET
    RENAME _factor_configs -> _analysis_factor_configs
tests/integration/test_candidate_correctness_gate.py -> tests/integration/test_pipeline_flows.py  (6)
    test_value_qualified_symbol_must_keep_value_validation_semantics
    test_growth_qualified_symbol_never_falls_through_to_value_contrarian_signal
    test_detect_regime_fails_closed_when_market_breadth_is_unavailable
    test_unconfigured_candidate_policy_fails_candidate_publication
    test_only_qualified_symbols_enter_downstream_validation_and_signal
    test_multi_qualified_symbol_derives_deterministic_primary_strategy_mapping
    RENAME ROOT -> CORRECTNESS_GATE_ROOT
    RENAME CSV_ROOT -> CORRECTNESS_GATE_CSV_ROOT
    RENAME CONFIGS -> CG_CONFIGS
    RENAME AS_OF -> CG_AS_OF
tests/integration/test_candidate_qualification_pipeline.py -> tests/integration/test_pipeline_flows.py  (5)
    test_canonical_qualifiers_removes_unconfigured_reason
    test_missing_upstream_layers_blocks_build_candidates
    test_candidate_stage_direct_call_with_complete_evidence_produces_candidates
    test_signal_no_signal_does_not_disqualify_candidate
    test_market_validation_contradicted_disqualifies_candidate
    RENAME AS_OF -> QUALIFICATION_AS_OF
tests/integration/test_daily_candidate_pipeline.py -> tests/integration/test_pipeline_flows.py  (1)
    test_daily_pipeline_executes_regime_validation_signal_and_candidates
    RENAME ROOT -> DAILY_CANDIDATE_ROOT
    RENAME CSV_ROOT -> DAILY_CANDIDATE_CSV_ROOT
    RENAME CONFIGS -> DAILY_CANDIDATE_CONFIGS
    RENAME AS_OF -> DAILY_CANDIDATE_AS_OF
    RENAME LONG_DATASET -> DAILY_CANDIDATE_LONG_DATASET
tests/integration/test_daily_production_evidence.py -> tests/integration/test_pipeline_flows.py  (4)
    test_step1_composition_proves_benchmark_and_industry_reach_run_daily
    test_step2_missing_benchmark_file_fails_closed
    test_step3_insufficient_59_benchmark_bars_regime_fails_closed
    test_step4_qualified_symbol_missing_industry_evidence_fails_closed
    RENAME ROOT -> PRODUCTION_EVIDENCE_ROOT
    RENAME CONFIGS -> PE_CONFIGS
    RENAME AS_OF -> PE_AS_OF
tests/integration/test_dividend_factor_pipeline.py -> tests/integration/test_pipeline_flows.py  (1)
    test_pipeline_computes_dividend_yield_ttm_from_landed_events
    RENAME AS_OF -> DIVIDEND_FACTOR_AS_OF
    RENAME SHANGHAI -> DIVIDEND_FACTOR_SHANGHAI
tests/integration/test_dividend_qualified_discovery.py -> tests/integration/test_pipeline_flows.py  (2)
    test_dividend_qualified_discovery_passes_when_factors_meet_dual_gate
    test_dividend_qualified_discovery_blocks_when_yield_falls_below_threshold
    RENAME AS_OF -> DQ_AS_OF
    RENAME SHANGHAI -> DIVIDEND_DISCOVERY_SHANGHAI
tests/integration/test_financial_pipeline.py -> tests/integration/test_pipeline_flows.py  (7)
    test_a_landed_statement_reaches_the_factor_context
    test_a_period_published_after_the_scan_is_not_in_the_context
    test_statements_that_were_never_landed_are_named
    test_a_scan_without_landed_statements_still_runs_and_says_so
    test_a_missing_value_stays_missing_through_the_pipeline
    test_the_two_statement_sets_land_and_normalize_together
    test_each_factor_context_carries_only_its_own_symbol
    RENAME ROOT -> FINANCIAL_ROOT
tests/integration/test_market_regime_snapshot.py -> tests/integration/test_pipeline_flows.py  (5)
    test_step1_daily_pipeline_writes_exactly_one_market_regime_record
    test_step2_market_regime_snapshot_carries_lineage_regime_version
    test_step3_same_date_changed_content_raises_snapshot_conflict
    test_step5_artifact_validator_for_market_regime
    test_step6_seed_market_regime_and_candidate_today_cli_prints_it
    RENAME ROOT -> REGIME_SNAPSHOT_ROOT
    RENAME AS_OF -> MRG_AS_OF
    RENAME FIXTURE_CSV -> REGIME_SNAPSHOT_FIXTURE_CSV
    RENAME BENCHMARK_ID -> REGIME_SNAPSHOT_BENCHMARK_ID
tests/integration/test_market_signal_pipeline.py -> tests/integration/test_pipeline_flows.py  (1)
    test_market_signal_pipeline_end_to_end_assembly
    RENAME AS_OF -> SIGNAL_PIPELINE_AS_OF
    RENAME SHANGHAI -> SIGNAL_PIPELINE_SHANGHAI
    RENAME _fr -> _signal_pipeline_fr
tests/integration/test_post_valuation_analysis_flow.py -> tests/integration/test_pipeline_flows.py  (2)
    test_formal_snapshot_equals_verified_readonly_analysis
    test_newer_valuation_changes_only_valuation_dependent_evidence
    RENAME CONFIGS -> PV_CONFIGS
tests/integration/test_qualification_pipeline.py -> tests/integration/test_pipeline_flows.py  (4)
    test_growth_qualification_uses_full_factor_evidence_beyond_scoring_snapshot
    test_growth_qualification_fails_closed_when_roe_evidence_is_missing
    test_dividend_qualification_ignores_percent_unit_paid_ratio
    test_garp_qualification_uses_pe_ttm_and_not_pe_percentile
    RENAME AS_OF -> QUALIFICATION_PIPELINE_AS_OF
    RENAME _factor -> _qualification_pipeline_factor
tests/integration/test_research_universe_flow.py -> tests/integration/test_pipeline_flows.py  (8)
    test_a_failed_symbol_keeps_the_symbols_that_succeeded
    test_a_rerun_retries_only_the_coverage_that_is_missing
    test_a_finished_symbol_is_on_disk_before_the_scheduler_forgets_it
    test_short_history_is_extended_backward_until_it_is_enough
    test_history_that_runs_out_is_reported_short_not_padded
    test_the_research_universe_is_a_subset_of_the_listing_prefilter
    test_the_research_command_reports_an_observational_target_and_writes_nothing
    test_only_the_research_universe_is_asked_for_expensive_history
    RENAME AS_OF -> RESEARCH_UNIVERSE_AS_OF
tests/integration/test_stock_discovery_workflow.py -> tests/integration/test_pipeline_flows.py  (3)
    test_stock_discovery_workflow_seeded_growth
    test_read_after_write_consistency
    test_daily_pipeline_to_discovery_workflow_end_to_end
    RENAME ROOT -> DISCOVERY_WORKFLOW_ROOT
    RENAME CSV_ROOT -> DISCOVERY_WORKFLOW_CSV_ROOT
tests/integration/test_valuation_pipeline.py -> tests/integration/test_pipeline_flows.py  (6)
    test_a_scan_without_landed_valuations_says_so
    test_landed_valuations_reach_the_factor_context
    test_a_future_landing_is_invisible_at_the_point_in_time
    test_each_factor_sees_only_its_own_symbol_valuations
    test_the_reported_metrics_match_what_the_response_carried
    test_reading_valuations_twice_gives_the_same_answer
    RENAME ROOT -> VALUATION_ROOT
    RENAME CONFIGS -> VAL_CFG
    RENAME AS_OF -> AS_OF_V
    RENAME LONG_DATASET -> VAL_LONG_DS
    RENAME CSV_FIXTURES -> VALUATION_CSV_FIXTURES
```
