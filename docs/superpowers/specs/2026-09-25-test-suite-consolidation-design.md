# 测试用例精简设计规格（Test Suite Consolidation）

**日期：** 2026-09-25
**仓库：** `jinking/a-stock-lens`
**性质：** 无行为变化的测试套件收敛（只动 `tests/`，不碰 `src/` 与 `configs/`）
**基线：** 2026-09-25 工作区实测 `1298 collected / 136 文件`（含未提交 WIP）
**关联：** `2026-09-22-a-stock-lens-complexity-reduction-design-v3.md`
**状态：** 待所有者复核

## 1. 为什么独立成文

v3 的靶子是「生产复杂度 + 测试复杂度」：删 Qualification 重复实现、拆 CLI God File、冻结 Pipeline，顺带收敛已证重复的测试。本规格的靶子只有一件事：

> **测试 case 的数量与文件布局。**

两者混写会让 v3 的验收标准（`final collected <= baseline`、CLI 行为不变、Trade Gate 冻结）失焦。v3 已落地的三条治理继续有效，并作为本规格的前提：

- Test Ownership（`docs/ARCHITECTURE.md` §20.5）
- Pure Refactor Rule
- Test Delta Budget

本规格在其上追加两条规范：**表驱动合并规范**（§4.1）与**常设 case 数量上限**（§7.5）。

## 2. 基线实测

实测命令：

```bash
PYTHONPATH= uv run --no-sync pytest --collect-only -q
```

| 指标 | 实测值 |
| --- | --- |
| collected cases | **1298** |
| 含用例的测试文件 | **136** |
| 去参数化后的测试函数 | 1168 |
| 参数化函数 | 34 个，额外产生 130 case |

分层分布：

| 层 | cases |
| --- | --- |
| `tests/unit` | 1060 |
| `tests/integration` | 158 |
| `tests/artifacts` | 60 |
| `tests/contract` | 16 |
| `tests/stress` | 4 |

文件规模分布：

| 单文件用例数 | 文件数 |
| --- | --- |
| ≤3 | 28 |
| 4–5 | 23 |
| 6–9 | 35 |
| 10–15 | 29 |
| >15 | 21 |

两条结论：

1. **参数化不是膨胀主因**（只占 10%），主因是「一个断言一条 case」的写法；
2. **51 个文件 ≤5 例，合计只有 158 例**——文件数的一半被长尾占据。

单点异常（已逐行核对）：`tests/unit/test_financial_normalizer.py::test_every_metric_declares_a_unit` 一个函数贡献 **49 个 case**，函数体只有 `assert metric.unit`。

## 3. 冻结清单（本轮只读）

### 3.1 工作区未提交的 5 个测试文件

| 文件 | cases |
| --- | --- |
| `tests/unit/test_cli_lifecycle.py` | 42 |
| `tests/unit/test_raw_sync.py` | 19 |
| `tests/unit/test_akshare_provider.py` | 18 |
| `tests/contract/test_extension_contracts.py` | 16 |
| `tests/unit/test_bootstrap_sync.py` | 15 |

这 110 个 case 本轮不合并、不删除、不重命名、不移动。理由：工作区共用同一棵树，这些文件中存在未提交改动，按既有约定视为他人 WIP。

**代价必须说清：** 目标减量要在剩余 1188 例里完成，等于 −21.7%，比表面上的 −20% 更紧。

### 3.2 断言不可删、只可合并

| 范围 | 理由 |
| --- | --- |
| `tests/artifacts/*` | 独立复算，不 import 生产代码，是防「校验器与实现一起错」的唯一安全网 |
| `tests/stress/*` | 全市场规模性质，删掉就没有任何规模证据 |

这两处的家族可以表驱动合并（减少 case 数），但**不得删除任何断言**。

### 3.3 语义冻结

`trade_gate/` 的 PASS / WAIT / NO_TRADE 语义、阈值、veto 业务含义不动（延续 v3 §6.3）。`src/` 与 `configs/` 本轮零改动。

### 3.4 v3 保护套件在本轮的含义

v3 计划点名保留的套件（`test_qualification_config.py`、`test_signal_detector.py`、`test_candidate_selection_policy.py`、`test_api.py`、`tests/artifacts/*`、`tests/contract/*`）在本轮的约束是：

- **文件**不合并、不删除、不改名（§6 规则 2）；
- 其中的 **case 级表驱动合并允许**——它不减断言，也不改文件名。

如果所有者认为这些套件连 case 级合并也要豁免，请在复核时指出；默认按上述口径执行。

## 4. 三条手法

### 4.1 表驱动合并（主力）

把「同一断言的参数枚举」收成单条遍历断言。合并后的用例必须满足三条：

1. **遍历全部成员**，不得只检查第一个；
2. **先收集再断言**，不得在循环里直接 `assert` 后中断；
3. **失败消息点名参数**，让人不用读源码就知道是哪个成员出错。

正例：

```python
def test_every_metric_declares_a_unit() -> None:
    missing = [metric.metric for metric in FINANCIAL_METRICS if not metric.unit]
    assert not missing, f"指标缺单位: {missing}"
```

反例（禁止）：

```python
for metric in FINANCIAL_METRICS:
    assert metric.unit  # 只报第一个失败者，且看不到全部不合格项
```

**例外：** 后端维度参数化保留。`@pytest.fixture(params=["json", "duckdb"])` 这类 fixture 级参数化承载的是「同一契约在两个后端成立」，删掉它等于不再测 duckdb 后端，不属于本规格的精简对象。

### 4.2 跨层去重

每条规则只保留「离它最近、最能解释失败原因」的那一层（v3 §7 的 Test Ownership 判据）：

| 规则类型 | 权威层 |
| --- | --- |
| 领域不变量、阈值、状态机 | 规则层 unit |
| Provider 字段与状态契约 | contract |
| 跨模块装配与接线 | integration |
| 产物合法性 | artifacts |

上层只测「接线是否正确」，不重复证明下层规则。**每条删除都必须在 review 文档里指名权威替代（文件 + 测试名）**，指不出替代的一律 KEEP。

已复核的候选（详见附录 A）。

### 4.3 低信息量清理

- **源码文本扫描表化**：散落在 `test_financial_normalizer.py`、`test_fundamental_factors.py`、`test_api.py`、`test_bootstrap_progress.py` 的 `assert "禁用词" not in source` 合并为一张「模块 × 禁用词」表，4 处收敛为 1 处。
- **同义反复删除**：`assert x is not None` 这类被 docstring 自认「赋值就是断言」的用例（类型检查器已覆盖）。注意 `tests/contract/test_extension_contracts.py` 的 5 条属于此类，但该文件在 §3.1 冻结清单内，本轮不动。
- **用例内恒真断言**（如 `>= 400` 之后又 `!= 200`）：随所属用例顺带清掉，不计入减量。

## 5. 分批与预算

| 批次 | 内容 | 预算 | 出口条件 |
| --- | --- | --- | --- |
| 0 | 冻结基线：重采 collected 清单、每文件计数、src 行覆盖率、逐条复核候选 | ±0 | 基线全绿 |
| 1 | 参数化收敛（≈15 处，含 49 例那个函数） | −114 | 相关文件全绿 |
| 2 | 同文件近邻家族表驱动（≈18 个家族） | −109 | 相关文件全绿 |
| 3 | 跨层去重（逐组指名权威层） | −20 | review 文档有替代记录 |
| 4 | 架构边界扫描表化 + 同义反复清理 | −6 | — |
| 5 | 文件合并（见 §6） | ±0 | node id 变更已记录 |
| 6 | 文档与治理：§20.5 增补规范 | ±0 | — |
| 7 | 全量验收 + 远端 CI 复跑 | 终值 ≤1040 | 见 §7 |

**关于差额的诚实说明：** 批次 1–4 的可减量在审计中是 **249–270** 区间（存在约 4 例的重复计数风险），而验收线 −258 落在这个区间中部。批次 0 重采后如果可执行清单低于 258，**触发目标复议：我带数据回来找所有者重新裁决，不自行凑数、不删除未登记的断言**。备用池是 35 个「6–9 例」文件里的近邻家族（合计约 250 例），那里尚未穷尽。

## 6. 文件合并规则

目标：**136 → 约 65 个文件**。口径是并掉 86 个 ≤9 例文件为约 15 个域文件（50 个 ≥10 例文件保留）。

规则：

1. 只合并 **≤9 例**的文件；
2. **不合并**下列文件：§3.1 冻结清单、被 Test Ownership 点名为权威的文件（`test_qualification_config.py`、`test_signal_detector.py`、`test_candidate_selection_policy.py`、`test_api.py`、`tests/artifacts/*`、`tests/contract/*`）、helper（`tests/artifacts/validator.py`、`tests/support.py`）、`conftest.py`。注意 `test_signal_detector.py` 只有 8 例，规则 1 挡不住它，必须靠规则 2 挡住；
3. 按域归并并命名，例如 trade_gate 三个小文件 → `test_trade_gate_contracts.py`；
4. 合并会改变 node id，**必须同步更新** Test Ownership 表与 review 文档里的文件映射；
5. 文件合并**独立成批、独立 commit**，不得与 case 级合并混在同一 diff。

排序理由：先减 case、后并文件，避免 node id 变更与用例合并两次搅动同一批 diff。

## 7. 验收

### 7.1 数量

```text
final collected      <= 1040
含用例文件数          <= 65
src 行覆盖率          不低于批次 0 基线（--cov=src/astock_lens）
```

覆盖率口径说明：它是**必要不充分**防线——能抓住「合并时把分支一起删掉了」，抓不住「断言写弱了」。断言强度靠 §7.3 的人工追溯。

### 7.2 质量

```bash
PYTHONPATH= uv run --no-sync pytest -q          # 全量，含 stress
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check .
uv run --no-sync mypy
```

### 7.3 追溯

每个 KEEP / MERGE / DELETE 决策写入 review 文档：位置、现状、决策、权威替代、复核人。合并类必须记录「合并前 N 条各自断言什么、合并后由哪条断言覆盖」。

### 7.4 独立验证

**本地全绿不算完成。** 必须推远端 CI 复跑同一门禁（`ci.yml` 已含全量 pytest + stress），回报 run id 与结论。

### 7.5 常设上限（治理）

将以下两条写入 `ARCHITECTURE.md` §20.5 并长期有效：

1. **表驱动优先**：同族枚举断言必须写成单条表驱动用例，不得为每个参数新增 case；
2. **数量上限**：本规格生效后，collected case 数不得再净增长；新增行为需按 v3「四类合法理由」申报，并同时说明是否有可合并的同族旧 case。

### 7.6 禁止

- 用 `skip` / `xfail` / `importorskip` 掩盖未通过的门禁；
- 以「补覆盖率」为名新增 case（v3 四类合法理由除外）；
- 在不可见的地方降低断言强度（例如把 `== expected` 改成 `is not None`）。

## 8. 已知风险

| 风险 | 处置 |
| --- | --- |
| 减量差额紧（249–270 vs 258） | 批次 0 重采；不足则触发目标复议（§5） |
| 表驱动降低 pytest 逐条可见性 | 强制失败消息点名参数；批次 3 review 时抽查消息质量 |
| 文件合并产生大 diff，review 成本高 | 独立批次 + 独立 commit；node id 映射表随附 |
| 与共用工作树的其他会话冲突 | §3.1 冻结 5 文件；若基线期间 WIP 落地并改动其他测试，批次 0 基线重采 |
| 审计估值与实测漂移 | 附录 A 区分「已核对」与「待复核」，批次 0 逐条定稿 |

## 9. 不做清单

- 不重构生产代码，不改 `src/` 与 `configs/`；
- 不新增测试（发现真实缺口时先记录裁决，再按 v3 四类理由申报）；
- 不删除 `tests/stress`、`tests/artifacts` 的任何断言；
- 不引入测试框架、DSL、插件或自定义 fixture 容器；
- 不改阈值、配置与 Trade Gate 语义；
- 不为凑数删除未登记的断言。

## 10. 实施顺序

```text
批次 0  冻结基线 + 逐条复核候选（产出 review 文档初稿）
批次 1  参数化收敛
批次 2  近邻家族表驱动
批次 3  跨层去重
批次 4  边界扫描表化 + 同义反复清理
批次 5  文件合并（独立 commit）
批次 6  文档与治理（ARCHITECTURE §20.5 / README / PROGRESS）
批次 7  全量验收 + 远端 CI
```

依赖关系：批次 1–4 相互独立，可并行；批次 5 依赖 1–4 完成（node id 稳定后再动文件）；批次 6 依赖 5（归属表要写最终文件名）；批次 7 依赖全部。

## 附录 A：候选清单与复核状态

| 位置 | 现状 | 决策 | 复核状态 |
| --- | --- | --- | --- |
| `tests/unit/test_financial_normalizer.py:289` | 49 case，`assert metric.unit` | MERGE → 1 | 已逐行核对 |
| `tests/unit/test_strategy_scanners.py:67–141` | 6 个参数化函数 × 5 策略 = 30 | MERGE → 6 | 已逐行核对 |
| `tests/unit/test_eligibility_scanner.py:94` | 5 case，仅 `DataStatus` 变 | MERGE → 1 | 已核对参数块 |
| `tests/unit/test_api.py:411` | 5 case，仅非法值变，只断言 422 | MERGE → 1 | 已核对参数块 |
| `tests/unit/test_qualification_config.py:24–208` | 18 例中 15 例为「写 YAML → raises」 | MERGE → 3 | 已核对函数名清单 |
| `tests/unit/test_snapshot_store.py:36–146` | 11 例中约 6 例被参数化 store 套件（json+duckdb）覆盖 | DELETE 6，其余 KEEP | 已对照函数名；逐条断言待批次 0 |
| `tests/unit/test_trailing_return_factor.py:85` | 6 case，仅 symbol 变 | MERGE → 1 | 待复核 |
| `tests/unit/test_proximity_high_factor.py:62,73` | 6+4 case，仅 symbol 变 | MERGE → 2 | 待复核 |
| `tests/unit/test_valuation_factors.py:73` | 5 case，仅 factor 名变 | MERGE → 1 | 待复核 |
| `tests/unit/test_watchlist_state_machine.py:83` | 4 case，仅 reserved state 变 | MERGE → 1 | 待复核 |
| `tests/contract/test_qualification_production_rules.py:69` | 6 case 逐字比对 EXPECTED | MERGE → 1 | 待复核；文件不合并（§3.4），case 可合并 |
| `tests/artifacts/test_snapshot_validator.py:112–207` | 13 条 finding 报出族 | MERGE（不删断言） | 待复核 |
| `tests/artifacts/test_job_manifest_validator.py:86–151` | 9 条「X is reported」 | MERGE（不删断言） | 待复核 |
| `tests/unit/test_signal_detector.py:28–134` | 8 条因子→signal | MERGE → 1 | 待复核 |
| `tests/unit/test_market_regime.py:36–134` | 7 条 regime 判定 | MERGE → 3 | 待复核 |
| `test_financial_normalizer` / `test_fundamental_factors` / `test_api` / `test_bootstrap_progress` | 4 处源码文本扫描 | MERGE → 1 张表 | 已定位 |
| `tests/unit/test_docs_consistency.py:10,21,33` | 3 条过期文案检查 | MERGE → 1 | 待复核 |
| `tests/unit/test_normalized_dataset_dividends.py:16`、`test_market_signal_readiness.py:196`、`test_westock_bars.py:258` | 用例内 `hasattr`/`callable` 恒真断言 | 顺带清理（±0） | 待复核 |

**假重复（明确 KEEP，不得以精简为名删除）：**

- `tests/artifacts/validator.py` 的独立复算（不 import 生产代码，无可替代）；
- `tests/stress` 的规模性质；
- market regime 三处 fail-closed 分别对应「无数据 / 宽度不可用 / 基准仅 59 根」三种不同上游状态；
- `@pytest.fixture(params=["json", "duckdb"])` 的后端维度。
