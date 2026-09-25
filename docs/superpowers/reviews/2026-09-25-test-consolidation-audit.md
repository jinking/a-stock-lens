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
| Task 7 | 本提交 | −29 | 1116 | 1145−29=1116 ✓ | 七文件 101→72（benchmark 15→11 −4、research_audit 21→17 −4、universe 21→16 −5、dividend_yield 7→2 −5、avg_amount 10→7 −3、trailing 16→11 −5、proximity 11→8 −3），逐条断言零丢失，全量 1116 全绿。**族口径与偏差**：计划按行号预算 benchmark 15→10、research_audit 21→16、universe 21→17，但实测行号区间分别只有 5 / 5 / 6 名成员（与「省 5 / 5 / 4」隐含的 6 / 6 / 5 差 1）；按「区间内成员全部成行」执行：benchmark/audit 各少省 1（−4），universe 多省 1（−5），trailing 的 NULL 族实为 6 名（计划记省 4），多省 1；总账仍为 −29，收口 1116 与预期一致。dividend_yield 计划记「6→1 省 5」，实测该 compute 骨架共 7 名，且断言形状分两类（4 名取值/单位、3 名状态边界），拆为两张表 `test_dividend_yield_ttm_value_cases` / `test_dividend_yield_ttm_status_boundaries`（7→2），净减仍是 5。**保留格式差异而非抹平**：universe 前 4 行保原 `rules == (...)` 全等、后 2 行保原 `rule in rules` 特判；audit 4 行保 `re.search`（原 `match=`，片段含 `empty.csv` 的 `.`）、1 行保字面 `in`；dividend 4 行保 `round(..., 4)` 口径、第 7 行保精确 `== 0.0`。Task 2 已合并的 `test_return_equals_the_ratio_of_the_window_ends`（trailing）与 `test_proximity_equals_the_latest_close_over_the_window_peak` / `test_a_planted_high_pulls_proximity_below_a_flat_ratio`（proximity）本轮零改动，AST 逐字节相同。**负控证据**：7 张表共 43 行逐行单独变异，43/43 被检出且失败消息点名对应 label（详见 task-7-report.md） |
