# 测试用例精简实施计划（Test Suite Consolidation）

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改动任何生产代码、不削弱任何断言覆盖的前提下，把测试套件从 1298 个 collected case 压到 ≤1040，文件从 136 个收敛到约 65 个。

**Architecture:** 三条手法分四批执行——参数化收敛（把同族枚举收成单条遍历断言）、近邻家族表驱动、跨层去重、低信息量清理；再单独一批做文件按域归并。每批独立 commit、独立验证，批次 5 依赖前四批（node id 稳定后再动文件）。

**Tech Stack:** Python 3.14 / pytest 8 / pytest-cov 7 / ruff / mypy / uv

**Spec:** `docs/superpowers/specs/2026-09-25-test-suite-consolidation-design.md`

## Global Constraints

以下约束对**每个任务**都成立，不再逐条重复：

- **只动 `tests/`**。`src/` 与 `configs/` 本轮零改动——行为不变因此可证。
- **冻结 5 个文件，一行都不许改**：`tests/unit/test_cli_lifecycle.py`、`tests/unit/test_raw_sync.py`、`tests/unit/test_akshare_provider.py`、`tests/contract/test_extension_contracts.py`、`tests/unit/test_bootstrap_sync.py`。
- **`tests/artifacts/*` 与 `tests/stress/*` 的断言不可删**，只允许表驱动合并。
- **不新增测试**。发现真实缺口时先停下记录裁决，不得顺手补测。
- **禁止** `skip` / `xfail` / `importorskip` 掩盖任何未通过的门禁。
- **提交只按显式路径** `git add <文件>`，禁止 `git add -A` / `git add .`——本工作树与其他会话共用，存在他人未提交改动。
- **提交信息用中文**，沿用「测试：/文档：」前缀，不写英文 conventional 前缀。
- 每个任务开始前先 `git status --short` 检查目标文件是否已被他人改动；**若目标文件出现在未提交列表里，停止并报告**，不要覆盖。
- 每个任务结束前必须：目标文件 `pytest -q` 全绿 + `ruff check` + `ruff format --check` + `mypy`。

### 合并后的代码必须遵守的三条

1. **遍历全部成员**，不得只检查第一个；
2. **先收集再断言**，不得在循环里直接 `assert` 后中断；
3. **失败消息点名参数**，读消息就知道是哪个成员出错。

正例：

```python
def test_every_metric_declares_a_unit() -> None:
    missing = [metric.metric for metric in FINANCIAL_METRICS if not metric.unit]
    assert not missing, f"缺少单位的指标: {missing}"
```

反例（禁止）：

```python
for metric in FINANCIAL_METRICS:
    assert metric.unit  # 只报第一个失败者，看不到全部不合格项
```

---

## File Structure

**新建：**

| 文件 | 责任 |
| --- | --- |
| `docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md` | 逐条 KEEP / MERGE / DELETE 决策、权威替代、执行前后的 case 数对照 |
| `var/test-consolidation/`（本地，不提交） | 基线快照、collect 清单、覆盖率、每批 before/after |

**修改：** 见各任务的 Files 段。共触及约 60 个测试文件。

**不修改：** `src/**`、`configs/**`、`tests/artifacts/validator.py`、`tests/support.py`、`tests/conftest.py`、§Global Constraints 的 5 个冻结文件。

---

### Task 0: 冻结基线

**Files:**
- Create: `docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md`
- Local only: `var/test-consolidation/`

**预算：** new 0 / removed 0 / net 0

- [ ] **Step 1: 确认工作区状态**

```bash
cd /Users/huangjinjin/Documents/ChatGPT/a-stock-lens
git status --short
git rev-parse HEAD
```

把 HEAD 与本轮新增的未提交路径记进 review 文档。若 §Global Constraints 的 5 个冻结文件**不在**未提交列表里（说明对方已提交），同样记录下来——基线口径要写清"冻结的是文件当前内容"。

- [ ] **Step 2: 采集基线**

```bash
mkdir -p var/test-consolidation

PYTHONPATH= uv run --no-sync pytest --collect-only -q \
  > var/test-consolidation/pytest-collect-baseline.txt 2>&1

PYTHONPATH= uv run --no-sync pytest --collect-only -q 2>/dev/null \
  | grep "::" | sed 's/::.*//' | sort | uniq -c | sort -rn \
  > var/test-consolidation/per-file-baseline.txt

wc -l < var/test-consolidation/per-file-baseline.txt      # 期望 136
tail -3 var/test-consolidation/pytest-collect-baseline.txt # 期望 1298 tests collected
```

- [ ] **Step 3: 采集覆盖率基线（本轮唯一的覆盖率口径来源）**

```bash
PYTHONPATH= uv run --no-sync pytest -q \
  --cov=src/astock_lens --cov-report=term \
  > var/test-consolidation/coverage-baseline.txt 2>&1

grep -E "^TOTAL" var/test-consolidation/coverage-baseline.txt
```

把 TOTAL 行原样抄进 review 文档的「覆盖率基线」小节。

- [ ] **Step 4: 分类基线的红项**

同一条命令的输出里已经包含失败清单。逐个归类：

- 由 §Global Constraints 冻结的 WIP 文件引起的失败 → 记为 `out of scope`，在 review 文档里写明文件名与失败测试名；
- 其他任何失败 → **停下，报告，不要继续**。红色的基线无法支撑"无行为变化"的验证。

- [ ] **Step 5: 逐条复核附录 A 的候选，写出 review 文档**

review 文档必须包含这张表（每个删除/合并项一行）：

```markdown
| 位置 | 现状 case 数 | 决策 | 权威替代（文件::测试名） | 复核结论 |
| --- | --- | --- | --- | --- |
| tests/unit/test_snapshot_store.py::test_write_then_read_round_trips | 1 | DELETE | tests/unit/test_duckdb_snapshot_store.py::test_a_written_snapshot_reads_back（json+duckdb 双后端） | 断言等价，可删 |
```

复核时对每个 DELETE 候选做一件事：**打开两边的测试体，确认被保留者真的覆盖了被删者的每一条断言**。只要有一条断言在保留者里找不到对应，就改判 KEEP。这条规则是硬约束——它防止"看起来像重复"的误删。

- [ ] **Step 6: 提交**

```bash
git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md
git commit -m "文档：建立测试精简基线与逐条复核台账"
```

---

### Task 1: 参数化收敛 A1 —— 两个最大头

**Files:**
- Modify: `tests/unit/test_financial_normalizer.py:289-291`
- Modify: `tests/unit/test_strategy_scanners.py:67-141`

**Interfaces:**
- Consumes: `FINANCIAL_METRICS`（现有模块常量）、`SCANNERS`（现有模块常量）、`_scanner(strategy_id)`（现有 helper）
- Produces: 无新接口，只改测试结构

**预算：** new 0 / removed 72 / net −72
（48 来自 `test_every_metric_declares_a_unit` 的 49→1；24 来自 6 个函数各 5→1）

- [ ] **Step 1: 记录本文件当前 case 数**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_financial_normalizer.py \
  tests/unit/test_strategy_scanners.py --collect-only -q 2>/dev/null | tail -1
```

期望：`93 tests collected`（63 + 30）。

- [ ] **Step 2: 把 49 例收成 1 例**

`tests/unit/test_financial_normalizer.py` 末尾，删除 `@pytest.mark.parametrize(...)` 装饰器，函数体改为：

```python
def test_every_metric_declares_a_unit() -> None:
    missing = [metric.metric for metric in FINANCIAL_METRICS if not metric.unit]
    assert not missing, f"缺少单位的指标: {missing}"
```

然后检查 `import pytest` 是否还有其他用途：

```bash
grep -n "pytest" tests/unit/test_financial_normalizer.py
```

若只剩 `import pytest` 一行，删掉它——留着会被 ruff 判为 F401。

- [ ] **Step 3: 运行该文件**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_financial_normalizer.py -q
```

期望：`15 passed`（该文件 15 个函数、63 例，去掉参数化后收敛为 15 例）。

- [ ] **Step 4: 把 6 个 ×5 收成 6 个 ×1**

`tests/unit/test_strategy_scanners.py` 里 6 个带 `@pytest.mark.parametrize("strategy_id", sorted(SCANNERS))` 的函数，逐个改为遍历版本并删掉装饰器。六个函数体逐个照抄下面这段（注释里是该函数原本的断言，一条都不能少）：

```python
def test_the_class_is_its_own() -> None:
    wrong = [
        sid
        for sid in sorted(SCANNERS)
        if type(_scanner(sid)).__name__ != SCANNERS[sid]
    ]
    assert not wrong, f"扫描器类名与配置不符: {wrong}"


def test_the_required_factors_match_the_configuration() -> None:
    wrong = []
    for sid in sorted(SCANNERS):
        config = load_strategy_config(CONFIGS / f"{sid}.yaml")
        if _scanner(sid).required_factors() != set(config.required_factors):
            wrong.append(sid)
    assert not wrong, f"必需因子与配置不符: {wrong}"


def test_scoring_one_symbol_alone_reports_no_score() -> None:
    """`score()` 没有总体可排，所以它只报告资格与证据。"""
    wrong = []
    for sid in sorted(SCANNERS):
        scanner = _scanner(sid)
        result = scanner.score(_context(scanner, "ONLY"))
        ok = (
            result.eligible is True
            and result.score is None
            and result.rank_percentile is None
            and result.confidence is None
            and result.strategy_id == sid
        )
        if not ok:
            wrong.append(f"{sid}: eligible={result.eligible!r} score={result.score!r} "
                         f"percentile={result.rank_percentile!r} "
                         f"confidence={result.confidence!r} id={result.strategy_id!r}")
    assert not wrong, "单独评分应只报资格与证据:\n" + "\n".join(wrong)


def test_a_missing_factor_makes_the_symbol_ineligible_with_a_reason() -> None:
    wrong = []
    for sid in sorted(SCANNERS):
        scanner = _scanner(sid)
        missing = min(scanner.required_factors())
        result = scanner.score(_context(scanner, "HOLE", missing=missing))
        if result.eligible is not False or not any(
            missing in reason for reason in result.risks
        ):
            wrong.append(f"{sid}: eligible={result.eligible!r} risks={result.risks!r}")
    assert not wrong, "缺因子应判不合格并给出原因:\n" + "\n".join(wrong)


def test_the_explanation_reaches_factor_level() -> None:
    wrong = []
    for sid in sorted(SCANNERS):
        scanner = _scanner(sid)
        contexts = (
            _context(scanner, "A"),
            _context(scanner, "B"),
            _context(scanner, "C"),
        )
        result = scanner.score_cross_section(contexts)[0]
        explanation = scanner.explain(result)
        factors = {item.factor for item in explanation.factors}
        if explanation.strategy_id != sid or factors != scanner.required_factors():
            wrong.append(
                f"{sid}: id={explanation.strategy_id!r} factors={sorted(factors)!r} "
                f"expected={sorted(scanner.required_factors())!r}"
            )
    assert not wrong, "解释应落到因子层:\n" + "\n".join(wrong)


def test_the_cross_section_ranks_exactly_the_eligible_population() -> None:
    wrong = []
    for sid in sorted(SCANNERS):
        scanner = _scanner(sid)
        missing = min(scanner.required_factors())
        contexts = (
            _context(scanner, "A"),
            _context(scanner, "B"),
            _context(scanner, "HOLE", missing=missing),
        )
        results = {
            result.symbol: result for result in scanner.score_cross_section(contexts)
        }
        if not (
            results["A"].score is not None
            and results["B"].score is not None
            and results["HOLE"].score is None
        ):
            wrong.append(
                f"{sid}: A={results['A'].score!r} B={results['B'].score!r} "
                f"HOLE={results['HOLE'].score!r}"
            )
    assert not wrong, "横截面应只给合格标的打分:\n" + "\n".join(wrong)
```

- [ ] **Step 5: 运行并核对减量**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_strategy_scanners.py -q
PYTHONPATH= uv run --no-sync pytest tests/unit/test_financial_normalizer.py \
  tests/unit/test_strategy_scanners.py --collect-only -q 2>/dev/null | tail -1
```

期望：全绿，且末行是 `21 tests collected`（93 − 72）。

- [ ] **Step 6: lint 与类型**

```bash
uv run --no-sync ruff check tests/unit/test_financial_normalizer.py tests/unit/test_strategy_scanners.py
uv run --no-sync ruff format --check tests/unit/test_financial_normalizer.py tests/unit/test_strategy_scanners.py
uv run --no-sync mypy
```

- [ ] **Step 7: 更新台账并提交**

```bash
git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md \
        tests/unit/test_financial_normalizer.py tests/unit/test_strategy_scanners.py
git commit -m "测试：收敛财务指标与策略扫描器的参数枚举用例"
```

---

### Task 2: 参数化收敛 A2 —— 因子类

**Files:**
- Modify: `tests/unit/test_trailing_return_factor.py:85-95`
- Modify: `tests/unit/test_proximity_high_factor.py:62-78`
- Modify: `tests/unit/test_valuation_factors.py:73-83`

**预算：** new 0 / removed 17 / net −17
（trailing 6→1 省 5；proximity 6→1 与 4→1 省 8；valuation 5→1 省 4）

- [ ] **Step 1: 三处改为遍历版**

`tests/unit/test_trailing_return_factor.py`：

```python
def test_return_equals_the_ratio_of_the_window_ends() -> None:
    """20 日收益跨 21 个收盘价：今天对 20 天前。"""
    wrong = []
    for symbol in RANKED:
        closes = _closes(symbol)
        expected = closes[-1] / closes[-21] - 1
        result = _compute(symbol)
        if result.status is not DataStatus.VALUE or result.raw_value != pytest.approx(
            expected, rel=1e-9
        ):
            wrong.append(f"{symbol}: status={result.status!r} value={result.raw_value!r} expected={expected!r}")
    assert not wrong, "收益不等于窗口两端比:\n" + "\n".join(wrong)
```

`tests/unit/test_proximity_high_factor.py`：

```python
def test_proximity_equals_the_latest_close_over_the_window_peak() -> None:
    wrong = []
    for symbol in (*SPIKED, "000001.SZ", "900948.SH"):
        closes, highs = _columns(symbol)
        expected = closes[-1] / max(highs[-WINDOW:])
        result = _compute(symbol)
        if result.status is not DataStatus.VALUE or result.raw_value != pytest.approx(
            expected, rel=1e-9
        ):
            wrong.append(f"{symbol}: status={result.status!r} value={result.raw_value!r} expected={expected!r}")
    assert not wrong, "近高点不等于收盘/窗口峰值:\n" + "\n".join(wrong)


def test_a_planted_high_pulls_proximity_below_a_flat_ratio() -> None:
    """没有植入的高点，每个上涨标的都会得到同一个 1/1.01。"""
    wrong = [
        f"{symbol}: {_compute(symbol).raw_value!r}"
        for symbol in SPIKED
        if not (_compute(symbol).raw_value is not None and _compute(symbol).raw_value < 1 / 1.01)
    ]
    assert not wrong, "植入高点未把近高压到平坦比之下:\n" + "\n".join(wrong)
```

`tests/unit/test_valuation_factors.py`：

```python
def test_a_non_positive_multiple_is_not_applicable() -> None:
    """负倍数不是便宜，是不存在。"""
    wrong = []
    for factor in ("pe_ttm", "pb", "ps_ttm", "pcf_operating_ttm", "peg"):
        result = build_factor(_config(factor)).compute(_context(_observation(factor, -71.31)))
        if result.status is not DataStatus.NOT_APPLICABLE or result.raw_value is not None:
            wrong.append(f"{factor}: status={result.status!r} value={result.raw_value!r}")
    assert not wrong, "非正倍数应为 NOT_APPLICABLE:\n" + "\n".join(wrong)
```

三处都把原来的 `@pytest.mark.parametrize(...)` 装饰器连同参数列表一起删掉。

- [ ] **Step 2: 核对减量并跑绿**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_trailing_return_factor.py \
  tests/unit/test_proximity_high_factor.py tests/unit/test_valuation_factors.py -q
PYTHONPATH= uv run --no-sync pytest tests/unit/test_trailing_return_factor.py \
  tests/unit/test_proximity_high_factor.py tests/unit/test_valuation_factors.py \
  --collect-only -q 2>/dev/null | tail -1
```

期望：全绿；收集数比改动前少 17。

- [ ] **Step 3: lint / 格式 / 类型，更新台账并提交**

```bash
uv run --no-sync ruff check tests/unit/test_trailing_return_factor.py \
  tests/unit/test_proximity_high_factor.py tests/unit/test_valuation_factors.py
uv run --no-sync ruff format --check tests/unit/test_trailing_return_factor.py \
  tests/unit/test_proximity_high_factor.py tests/unit/test_valuation_factors.py
uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md \
  tests/unit/test_trailing_return_factor.py tests/unit/test_proximity_high_factor.py \
  tests/unit/test_valuation_factors.py
git commit -m "测试：收敛因子窗口类参数枚举用例"
```

---

### Task 3: 参数化收敛 A3 —— 状态机与 Provider

**Files:**
- Modify: `tests/unit/test_eligibility_scanner.py:88-112`
- Modify: `tests/unit/test_watchlist_state_machine.py:82-90`
- Modify: `tests/unit/test_westock_provider.py:98-110` 与 `:140-150`

**预算：** new 0 / removed 11 / net −11
（eligibility 5→1 省 4；watchlist 4→1 省 3；westock 3→1 两次省 4）

- [ ] **Step 1: eligibility 5→1**

把装饰器里的状态列表提为模块常量，函数改为：

```python
NON_VALUE_STATUSES = (
    DataStatus.NULL,
    DataStatus.STALE,
    DataStatus.INVALID,
    DataStatus.SOURCE_ERROR,
    DataStatus.NOT_APPLICABLE,
)


def test_any_status_other_than_value_is_not_eligible() -> None:
    """六个状态保持可区分；除 VALUE 外都不算证据。"""
    wrong = []
    for status in NON_VALUE_STATUSES:
        scanner = EligibilityScanner(_config())
        context = _context(
            _factor("roe_ttm", DataStatus.VALUE),
            _factor("gross_margin", status, value=None),
        )
        result = scanner.score(context)
        if result.eligible is not False or f"gross_margin is {status}, not VALUE" not in result.risks:
            wrong.append(f"{status}: eligible={result.eligible!r} risks={result.risks!r}")
    assert not wrong, "非 VALUE 状态不应算证据:\n" + "\n".join(wrong)
```

- [ ] **Step 2: watchlist 4→1**

```python
def test_reserved_states_are_unreachable_in_v1() -> None:
    wrong = []
    for target in RESERVED_STATES:
        entry = open_entry("600519.SH", at=CREATED_AT)
        try:
            transition(entry, target, at=LATER)
        except WatchlistTransitionError as exc:
            if target.value not in str(exc):
                wrong.append(f"{target}: 错误信息未点名状态: {exc}")
        else:
            wrong.append(f"{target}: 未拒绝保留状态")
    assert not wrong, "保留状态在 V1 必须不可达:\n" + "\n".join(wrong)
```

- [ ] **Step 3: westock 两处 3→1**

```python
def test_every_recorded_statement_parses_into_one_table() -> None:
    wrong = []
    for dataset in DATASETS:
        tables = parse_tables(_recorded(dataset))
        if len(tables) != 1:
            wrong.append(f"{dataset}: 解析出 {len(tables)} 张表")
            continue
        columns = tables[0].columns
        missing = [name for name in ("EndDate", "InfoPublDate", "code") if name not in columns]
        if missing or len(tables[0].rows) != 24:
            wrong.append(
                f"{dataset}: 缺列={missing} 行数={len(tables[0].rows)}（期望 24）"
            )
    assert not wrong, "每份录制报表应解析成一张表:\n" + "\n".join(wrong)
```

`test_each_dataset_maps_to_its_statement` 用同一结构：遍历 `(("financial_income", "income"), ("financial_balance", "balance"), ("financial_cashflow", "cashflow"))`，把原本的断言结果收集进 `wrong` 再统一断言。**先读该函数现有函数体，确认它断言的字段名后再改写**，不得凭猜测重写断言。

- [ ] **Step 4: 跑绿 + 核对减量 + lint + 提交**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_eligibility_scanner.py \
  tests/unit/test_watchlist_state_machine.py tests/unit/test_westock_provider.py -q

uv run --no-sync ruff check tests/unit/test_eligibility_scanner.py \
  tests/unit/test_watchlist_state_machine.py tests/unit/test_westock_provider.py
uv run --no-sync ruff format --check tests/unit/test_eligibility_scanner.py \
  tests/unit/test_watchlist_state_machine.py tests/unit/test_westock_provider.py
uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md \
  tests/unit/test_eligibility_scanner.py tests/unit/test_watchlist_state_machine.py \
  tests/unit/test_westock_provider.py
git commit -m "测试：收敛资格状态与 Provider 参数枚举用例"
```

---

### Task 4: 参数化收敛 A4 —— API 与契约

**Files:**
- Modify: `tests/unit/test_api.py:411-431`
- Modify: `tests/contract/test_qualification_production_rules.py:69-77`
- Modify: `tests/unit/test_strategy_parity.py:92-101`

**注意：** `tests/contract/test_extension_contracts.py` 是冻结文件，**不要碰**。`test_qualification_production_rules.py` 不在冻结清单里，可以改。

**预算：** new 0 / removed 14 / net −14
（api 5→1 省 4；contract 6→1 省 5；parity 6→1 省 5）

- [ ] **Step 1: api 5→1**

```python
INVALID_QUERY_VALUES = (
    ("limit", 0),
    ("limit", -1),
    ("limit", 501),
    ("min_percentile", -0.1),
    ("min_percentile", 1.1),
)


def test_strategy_results_invalid_query_returns_422(local_tmp: Path) -> None:
    _seed(local_tmp)
    client = TestClient(create_app(snapshot_root=local_tmp))

    wrong = []
    for param, value in INVALID_QUERY_VALUES:
        response = client.get(
            "/strategies/growth/results", params={"as_of": DAY, param: value}
        )
        if response.status_code != 422:
            wrong.append(f"{param}={value!r}: {response.status_code}")
    assert not wrong, "非法查询参数应返回 422:\n" + "\n".join(wrong)
```

- [ ] **Step 2: 生产规则 6→1**

```python
def test_production_rule_matches_owner_approval() -> None:
    """生产 YAML 必须与所有者批准的因子名与阈值逐字一致。"""
    wrong = []
    for strategy_id in EXPECTED:
        raw = _load_yaml(strategy_id)
        expected = EXPECTED[strategy_id]
        if raw["strategy_id"] != strategy_id:
            wrong.append(f"{strategy_id}: strategy_id={raw['strategy_id']!r}")
        if raw["version"] != "v1":
            wrong.append(f"{strategy_id}: version={raw['version']!r}")
        if raw["thresholds"] != expected:
            wrong.append(
                f"{strategy_id}: thresholds 与获批口径不一致\n"
                f"  实际: {raw['thresholds']!r}\n  获批: {expected!r}"
            )
    assert not wrong, "生产资格 YAML 偏离所有者批准口径:\n" + "\n".join(wrong)
```

这条合并在语义上更强：原先 6 个 case 只会报第一个不合格策略，现在是全部。

- [ ] **Step 3: 策略一致性 6→1**

```python
def test_the_refactored_scanner_reproduces_the_recorded_output() -> None:
    wrong = []
    for strategy_id in sorted(PARITY["strategies"]):
        scanner = build_scanner(load_strategy_config(CONFIGS / f"{strategy_id}.yaml"))
        observed = [_observed(result) for result in scanner.score_cross_section(_contexts())]
        expected = PARITY["strategies"][strategy_id]["results"]
        if observed != expected:
            first = next(
                (i for i, (a, b) in enumerate(zip(observed, expected, strict=False)) if a != b),
                None,
            )
            wrong.append(f"{strategy_id}: 第 {first} 条起不一致")
    assert not wrong, "重构后的扫描器未复现录制输出:\n" + "\n".join(wrong)
```

- [ ] **Step 4: 跑绿 + 核对减量 + lint + 提交**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_api.py \
  tests/contract/test_qualification_production_rules.py tests/unit/test_strategy_parity.py -q

uv run --no-sync ruff check tests/unit/test_api.py \
  tests/contract/test_qualification_production_rules.py tests/unit/test_strategy_parity.py
uv run --no-sync ruff format --check tests/unit/test_api.py \
  tests/contract/test_qualification_production_rules.py tests/unit/test_strategy_parity.py
uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md \
  tests/unit/test_api.py tests/contract/test_qualification_production_rules.py \
  tests/unit/test_strategy_parity.py
git commit -m "测试：收敛查询校验与生产规则参数枚举用例"
```

- [ ] **Step 5: 批次 1 收口**

```bash
PYTHONPATH= uv run --no-sync pytest --collect-only -q 2>/dev/null | tail -1
```

期望：`1184 tests collected`（1298 − 114）。把数字写进台账。

---

### Task 5: 近邻家族 B1 —— 资格配置

**Files:**
- Modify: `tests/unit/test_qualification_config.py:24-208`

**预算：** new 0 / removed 14 / net −14

该文件 18 个函数中有 15 个是「写一份非法 YAML → 断言抛错」，另 3 个是合法加载 / 缺文件语义 / 允许的根键，**这 3 个保持独立**。15 条非法输入合并为 1 条表驱动用例，文件从 18 收敛到 4。

**先读完整文件**，把 15 个函数各自的三要素（构造的 YAML、期望的异常类型、期望的错误信息片段）抄成一张表，再合并。

- [ ] **Step 1: 读文件并制表**

```bash
sed -n '1,223p' tests/unit/test_qualification_config.py
```

在台账里记下 15 行的三要素。

- [ ] **Step 2: 合并为一条**

按「失败原因」分组填写下面这张表：

```python
INVALID_RULE_CASES: tuple[tuple[str, dict[str, object], str], ...] = (
    ("空 thresholds", {"thresholds": {}}, "不能为空"),
    # ... 其余 14 行照实填写，字段取自 Step 1 的表
)


def test_invalid_rules_are_refused(tmp_path: Path) -> None:
    wrong = []
    for label, payload, expected in INVALID_RULE_CASES:
        try:
            load_qualification_config(_write(tmp_path, payload))
        except QualificationConfigError as exc:
            if expected not in str(exc):
                wrong.append(f"{label}: 错误信息缺少 {expected!r}，实际 {exc}")
        else:
            wrong.append(f"{label}: 未拒绝非法配置")
    assert not wrong, "非法配置未被正确拒绝:\n" + "\n".join(wrong)
```

`_write` 与异常类型名以文件实际签名为准（Step 1 里记下）。**合法加载、缺文件语义、未知根键这三类不属于「非法拒绝」，保持独立用例**——它们各自守住不同的成功/失败路径。

- [ ] **Step 3: 跑绿，期望 `4 passed`**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_qualification_config.py -q
uv run --no-sync ruff check tests/unit/test_qualification_config.py
uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md \
  tests/unit/test_qualification_config.py
git commit -m "测试：合并资格配置非法输入用例"
```

---

### Task 6: 近邻家族 B2 —— 信号、市场与 API 缺快照族

**Files:**
- Modify: `tests/unit/test_signal_detector.py:28-134`
- Modify: `tests/unit/test_market_regime.py:36-134`
- Modify: `tests/unit/test_market_validator.py`（4 条 status 族）
- Modify: `tests/unit/test_csv_security_normalizer.py:107-136`
- Modify: `tests/unit/test_api.py`（缺快照 404 族）

**预算：** new 0 / removed 24 / net −24
（signal 8→1 省 7；regime 9→3 省 6；validator 4→1 省 3；csv 4→1 省 3；api 404 族 6 条省 5）

- [ ] **Step 1: 逐个家族制表**

每个家族先读原文，把「输入 → 期望」抄成表。合并骨架：

```python
def test_<族名>() -> None:
    wrong = []
    for label, payload, expected in CASES:
        try:
            observed = <调用>
        except <期望异常> as exc:
            if expected not in str(exc):
                wrong.append(f"{label}: 错误信息缺少 {expected!r}，实际 {exc}")
            continue
        if observed != expected:
            wrong.append(f"{label}: 得到 {observed!r}，期望 {expected!r}")
    assert not wrong, "<族名> 未按预期:\n" + "\n".join(wrong)
```

- [ ] **Step 2: 跑绿 + 核对减量**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_signal_detector.py \
  tests/unit/test_market_regime.py tests/unit/test_market_validator.py \
  tests/unit/test_csv_security_normalizer.py tests/unit/test_api.py -q
```

- [ ] **Step 3: lint / 格式 / 类型，更新台账并提交**

```bash
uv run --no-sync ruff check tests/unit/test_signal_detector.py tests/unit/test_market_regime.py \
  tests/unit/test_market_validator.py tests/unit/test_csv_security_normalizer.py tests/unit/test_api.py
uv run --no-sync ruff format --check tests/unit/test_signal_detector.py tests/unit/test_market_regime.py \
  tests/unit/test_market_validator.py tests/unit/test_csv_security_normalizer.py tests/unit/test_api.py
uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md \
  tests/unit/test_signal_detector.py tests/unit/test_market_regime.py \
  tests/unit/test_market_validator.py tests/unit/test_csv_security_normalizer.py tests/unit/test_api.py
git commit -m "测试：合并信号判定与市场校验近邻用例"
```

**市场 regime 的例外：** 该文件的 9 条里，有 3 条分别守「无数据 / 宽度不可用 / 基准仅 59 根」三种不同上游状态，**必须保持 3 条独立**，只把各自内部同形的判定收进遍历。合并后该文件不应低于 3 例。

---

### Task 7: 近邻家族 B3 —— 基准、审计、Universe 与因子

**Files:**
- Modify: `tests/unit/test_benchmark_landing_reader.py:75-147`
- Modify: `tests/unit/test_research_baseline_audit.py:108-145`
- Modify: `tests/unit/test_universe_builder.py:123-152`
- Modify: `tests/unit/test_dividend_yield_factor.py`（6 条 compute 同骨架）
- Modify: `tests/unit/test_avg_amount_factor.py:51-79`
- Modify: `tests/unit/test_trailing_return_factor.py`（NULL 族）
- Modify: `tests/unit/test_proximity_high_factor.py`（NULL 族）

**预算：** new 0 / removed 29 / net −29
（benchmark 15→10 省 5；research_audit 21→16 省 5；universe 21→17 省 4；dividend_yield 6→1 省 5；avg_amount 8→5 省 3；trailing NULL 省 4；proximity NULL 省 3）

- [ ] **Step 1: 按 Task 6 的骨架逐个家族合并**

`test_dividend_yield_factor.py` 的 6 条是同一 compute 骨架，直接收成 1 条遍历。

**`test_trailing_return_factor.py` 与 `test_proximity_high_factor.py` 是两个不同文件，注意别与 Task 2 改过的函数重名**——Task 2 处理的是「窗口比值」族，本任务处理「NULL / 缺数据」族，函数名不同、互不覆盖。

- [ ] **Step 2: 跑绿 + 核对减量 + lint + 提交**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_benchmark_landing_reader.py \
  tests/unit/test_research_baseline_audit.py tests/unit/test_universe_builder.py \
  tests/unit/test_dividend_yield_factor.py tests/unit/test_avg_amount_factor.py \
  tests/unit/test_trailing_return_factor.py tests/unit/test_proximity_high_factor.py -q

uv run --no-sync ruff check tests/unit/ && uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md \
  tests/unit/test_benchmark_landing_reader.py tests/unit/test_research_baseline_audit.py \
  tests/unit/test_universe_builder.py tests/unit/test_dividend_yield_factor.py \
  tests/unit/test_avg_amount_factor.py tests/unit/test_trailing_return_factor.py \
  tests/unit/test_proximity_high_factor.py
git commit -m "测试：合并基准、审计与因子近邻用例"
```

---

### Task 8: 近邻家族 B4 —— artifacts（断言不可删）

**Files:**
- Modify: `tests/artifacts/test_snapshot_validator.py:112-207` 与 `:271-411`
- Modify: `tests/artifacts/test_job_manifest_validator.py:86-151`

**预算：** new 0 / removed 23 / net −23
（snapshot_validator 25→10 省 15；job_manifest 11→3 省 8）

**硬约束：** 这两个文件守的是「校验器与生产实现一起错」的唯一安全网。**只允许把「同一 finding 的枚举」收成表驱动，一条断言都不许删。** 合并后如果发现某个 finding 不再被任何断言覆盖，说明改错了，回退。

- [ ] **Step 1: 制表并合并**

每个 finding 一行：`(finding 代码, 构造的输入, 期望出现的字段)`。骨架：

```python
def test_every_broken_snapshot_reports_its_finding() -> None:
    wrong = []
    for label, payload, expected_code in BROKEN_CASES:
        findings = validate_snapshot(payload)
        codes = {finding.code for finding in findings}
        if expected_code not in codes:
            wrong.append(f"{label}: 期望 {expected_code}，实际 {sorted(codes)}")
    assert not wrong, "快照校验未报出预期 finding:\n" + "\n".join(wrong)
```

`validate_snapshot` 的实际签名以文件为准。

- [ ] **Step 2: 跑绿并确认断言未减**

```bash
PYTHONPATH= uv run --no-sync pytest tests/artifacts/ -q
```

改前先记录 `grep -c "assert " tests/artifacts/test_snapshot_validator.py`，改后不得减少。

- [ ] **Step 3: lint + 提交**

```bash
uv run --no-sync ruff check tests/artifacts/ && uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md \
  tests/artifacts/test_snapshot_validator.py tests/artifacts/test_job_manifest_validator.py
git commit -m "测试：校验器 finding 用例改为表驱动"
```

---

### Task 9: 近邻家族 B5 —— 小家族批量

**Files（8 个家族）：**
- `tests/unit/test_candidate_evidence.py`
- `tests/unit/test_industry_market_evidence.py`
- `tests/unit/test_percentile_scorer.py`
- `tests/unit/test_strategy_scoring.py`
- `tests/unit/test_universe_config.py`
- `tests/unit/test_market_evidence.py`
- `tests/unit/test_candidate_primary_strategy.py`
- `tests/integration/test_command_snapshot_ownership.py`

**预算：** new 0 / removed 17 / net −17

- [ ] **Step 1: 每个家族先读、后按 Task 6 骨架合并**

这 8 个家族合计 25 例 → 8 例。逐家族处理，**每改完一个就跑一次该文件**：

```bash
PYTHONPATH= uv run --no-sync pytest <该文件> -q
```

- [ ] **Step 2: 全量核对批次 2 减量**

```bash
PYTHONPATH= uv run --no-sync pytest --collect-only -q 2>/dev/null | tail -1
```

期望：`1077 tests collected`（1298 − 114 − 107）。**若高于此数，说明批次 2 有家族没做干净**，回到未达标的家族补齐；**若低于此数，检查是否误删了断言**，回退误删部分并在台账里记录原因。

- [ ] **Step 3: lint + 提交**

```bash
uv run --no-sync ruff check tests/ && uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md \
  tests/unit/test_candidate_evidence.py tests/unit/test_industry_market_evidence.py \
  tests/unit/test_percentile_scorer.py tests/unit/test_strategy_scoring.py \
  tests/unit/test_universe_config.py tests/unit/test_market_evidence.py \
  tests/unit/test_candidate_primary_strategy.py \
  tests/integration/test_command_snapshot_ownership.py
git commit -m "测试：合并八个小规模近邻家族用例"
```

---

### Task 10: 跨层去重

**预算：** new 0 / removed 20 / net −20

**硬约束：** 每条删除必须在台账里指名权威替代（`文件::测试名`）。**指不出替代的一律 KEEP。** 保留者必须覆盖被删者的每一条断言——逐个打开两边对照，不许凭测试名相似就删。

已定位的 12 组（行号是基线时的位置，可能因前几批改动漂移，以测试名为准）：

| 组 | 被删候选 | 保留的权威 |
| --- | --- | --- |
| 1 | `test_snapshot_store.py` 的 JSON 专属重复 6 例 | `test_duckdb_snapshot_store.py` 的 `store` fixture 套件（json+duckdb 双后端） |
| 2 | `test_qualification_context.py:88,102` | `tests/integration/test_qualification_pipeline.py` 生产 YAML 装配例 |
| 3 | `test_candidate_builder.py` 的 TREND_WEAKEN / NO_SIGNAL 2 例 | `test_candidate_selection_policy.py` |
| 4 | `test_daily_pipeline.py:164` | `test_daily_pipeline.py:147` |
| 5 | `test_candidate_qualification_pipeline.py:65` | `test_candidate_policy.py:135` |
| 6 | `test_daily_pipeline.py:315` | `test_daily_pipeline.py:291` |
| 7 | `test_market_signal_pipeline.py` 流动性例 | `test_market_validator.py:34` |
| 8 | `test_qualified_discovery.py` 双门槛断言 | `test_strategy_qualification.py:91` |
| 9 | `test_dividend_qualified_discovery.py:89-108` | `test_qualified_discovery.py:254` |
| 10 | `test_bootstrap_batch_fallback.py:391` | `test_bootstrap_sync.py:166` |
| 11 | `test_cli_industry_loader.py:126` 或 `test_candidate_calibration_cli.py:154` 择一 | `test_industry_membership.py:147` |
| 12 | `test_daily_production_evidence.py` step5 | 同文件 step4 |

**组 6 与组 12 需要额外注意：** 被删者如果断言的是「同一规则在不同观察点」而非同一断言，改判 KEEP。逐个打开确认。

- [ ] **Step 1: 逐组对照、记录、执行**
- [ ] **Step 2: 跑受影响文件全绿**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_snapshot_store.py \
  tests/unit/test_duckdb_snapshot_store.py tests/unit/test_qualification_context.py \
  tests/unit/test_candidate_builder.py tests/integration/test_daily_pipeline.py \
  tests/integration/test_candidate_qualification_pipeline.py \
  tests/integration/test_market_signal_pipeline.py tests/unit/test_qualified_discovery.py \
  tests/integration/test_dividend_qualified_discovery.py \
  tests/unit/test_bootstrap_batch_fallback.py tests/unit/test_cli_industry_loader.py \
  tests/integration/test_daily_production_evidence.py -q
```

- [ ] **Step 3: lint + 提交**

```bash
uv run --no-sync ruff check tests/ && uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md <被改文件逐个列出>
git commit -m "测试：删除跨层重复证明并指名权威替代"
```

**注意：** `test_bootstrap_sync.py` 在冻结清单里。组 10 只能改 `test_bootstrap_batch_fallback.py`（删的那一侧），**保留侧一行都不许动**。若发现保留侧也不得不改，跳过组 10 并在台账里记明原因。

---

### Task 11: 架构边界扫描表化 + 同义反复清理

**Files:**
- Modify: `tests/unit/test_financial_normalizer.py`（源码扫描例）
- Modify: `tests/unit/test_fundamental_factors.py:406`
- Modify: `tests/unit/test_api.py:235,1015`
- Modify: `tests/unit/test_bootstrap_progress.py:325`
- Modify: `tests/unit/test_docs_consistency.py:10,21,33`

**预算：** new 0 / removed 6 / net −6

- [ ] **Step 1: 建一张「模块 × 禁用词」表**

在 `tests/unit/` 下**修改**现有文件中的一处（建议放 `test_financial_normalizer.py` 或新建 `tests/unit/test_architecture_boundaries.py`——若新建，另需 1 个 case，净减量相应减 1，台账里注明）：

```python
FORBIDDEN_IN_MODULE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("src/astock_lens/data/normalize/financials.py", ("subprocess", "urlopen", "Runner", ".fetch(", "requests")),
    ("src/astock_lens/factors/fundamental.py", (...)),   # 从 test_fundamental_factors.py:406 抄
    ("src/astock_lens/api/app.py", (...)),               # 从 test_api.py:235 抄
    ("scripts/watch-bootstrap.sh", (...)),               # 从 test_bootstrap_progress.py:325 抄
)


def test_modules_do_not_reach_for_transport_or_computation() -> None:
    violations = []
    for path, forbidden in FORBIDDEN_IN_MODULE:
        source = Path(path).read_text(encoding="utf-8")
        hits = [word for word in forbidden if word in source]
        if hits:
            violations.append(f"{path}: {hits}")
    assert not violations, "架构边界被突破:\n" + "\n".join(violations)
```

**把各文件的禁用词原样抄进表——不许删词、不许换词。**

- [ ] **Step 2: 删 API 的两条重复边界检查**

`test_api.py` 的 `test_api_never_imports_the_computation_engines`(:235) 与 `test_api_module_imports_strictly_bounded`(:1015) 守的是同一边界，保留更强的那一个（AST 解析的那个），删另一个。删之前确认保留者的禁用清单是被删者的超集。

- [ ] **Step 3: docs_consistency 3→1**

```python
def test_documentation_does_not_claim_stale_status() -> None:
    stale = []
    for path, phrases in STALE_CLAIMS:      # 从三个现有用例抄
        text = Path(path).read_text(encoding="utf-8")
        for phrase in phrases:
            if phrase in text:
                stale.append(f"{path}: {phrase!r}")
    assert not stale, "文档仍在声称过期状态:\n" + "\n".join(stale)
```

- [ ] **Step 4: 跑绿 + 核对减量 + lint + 提交**

```bash
PYTHONPATH= uv run --no-sync pytest tests/unit/test_docs_consistency.py \
  tests/unit/test_financial_normalizer.py tests/unit/test_fundamental_factors.py \
  tests/unit/test_api.py tests/unit/test_bootstrap_progress.py -q
uv run --no-sync ruff check tests/ && uv run --no-sync mypy

git add docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md <被改文件逐个列出>
git commit -m "测试：架构边界扫描与文档一致性检查表驱动化"
```

- [ ] **Step 5: 批次 1–4 收口核对**

```bash
PYTHONPATH= uv run --no-sync pytest --collect-only -q 2>/dev/null | tail -1
```

期望：`1051 tests collected`（1298 − 247）。

**与验收线的关系要算清：** 四批细目（72 + 14 + 17 + 11 + 14 + 24 + 29 + 23 + 17 + 20 + 6）合计 **−247**，落在规格 §5 估计的 249–270 区间下沿，比验收线所需的 −258 少 11。**因此 Task 15 不是可选项，而是收口步骤**：只要收口 > 1040 就必须执行。若补完仍不到 1040，按规格 §5 停下报告所有者，不自行凑数。

---

### Task 12: 文件合并（独立批次）

**预算：** new 0 / removed 0 / net 0（**只改文件布局，不动 case 数**）

**Files:**
- Create: 约 14 个域文件（见下表）
- Delete: 84 个 ≤9 例的源文件（内容整体移入域文件）

**目标：** 136 → 约 65 个含用例的文件。

**不合并：** 冻结清单 5 个文件、`tests/artifacts/*`、`tests/contract/*`、`tests/unit/test_signal_detector.py`、`tests/stress/*`（单文件域）、`tests/artifacts/validator.py`、`tests/support.py`、`tests/conftest.py`。

**允许的唯一例外：** trade_gate 三个权威小文件（`test_trade_gate_models.py` + `test_trade_gate_profiles.py` + `test_trade_gate_audit_adapter.py`）合并为 `tests/unit/test_trade_gate_contracts.py`——它们同域且合计只有 8 例，合并后仍是该域唯一权威，台账与 `ARCHITECTURE.md §20.5` 的归属表同步指向新文件。

**推荐桶划分**（实现者须先产出映射表再动手）：

| 目标文件 | 吸收来源（≤9 例） |
| --- | --- |
| `tests/unit/test_candidate_stage.py` | test_candidate_builder / test_candidate_calibration / test_candidate_discovery / test_candidate_evidence / test_candidate_policy / test_candidate_primary_strategy / test_candidate_routing / test_candidate_v2_impact |
| `tests/unit/test_bootstrap_stage.py` | test_bootstrap_scan_cost / test_bootstrap_scheduler |
| `tests/unit/test_quality_gates.py` | test_daily_bar_quality_gate / test_financial_quality_gate |
| `tests/unit/test_dividends.py` | test_dividend_coverage / test_dividend_event_normalizer / test_dividend_yield_factor / test_normalized_dataset_dividends |
| `tests/unit/test_market_stage.py` | test_market_evidence / test_industry_market_evidence / test_market_signal_readiness / test_benchmark_evidence |
| `tests/unit/test_cli_surface.py` | test_cli / test_cli_industry_loader / test_cli_research_adapter |
| `tests/unit/test_valuation_stage.py` | test_valuation_coverage / test_valuation_normalizer |
| `tests/unit/test_calibration_stage.py` | test_calibration_factor_distribution / test_qualification_impact |
| `tests/unit/test_platform_basics.py` | test_settings / test_import / test_trading_calendar / test_docs_consistency |
| `tests/unit/test_universe_stage.py` | test_universe_config / test_qualified_discovery / test_discovery_service |
| `tests/unit/test_trade_gate_contracts.py` | test_trade_gate_models / test_trade_gate_profiles / test_trade_gate_audit_adapter |
| `tests/unit/test_trade_gate_evaluation.py` | 其余 9 个 trade_gate 小文件（context / engine / scoring / veto / store / duckdb_store / metrics / replay / service） |
| `tests/integration/test_cli_entry_flows.py` | integration 里 ≤9 例的 CLI 入口文件 |
| `tests/integration/test_pipeline_flows.py` | integration 里 ≤9 例的 pipeline / workflow 文件 |

`tests/unit/test_domain_models.py`、`test_factor_registry.py`、`test_strategy_factor_index.py`、`test_qualification_context.py`、`test_momentum_scanner.py`、`test_strategy_parity.py`、`test_jev_triage.py` 等未能归入上表的，实现者按「同域」就近归并，并在映射表里说明归属理由。

- [ ] **Step 1: 产出映射表**

在台账里写全：源文件 → 目标文件 → 搬移的测试函数名 → 迁移后 case 数。**映射表写完先自查一遍：每个源文件的每个测试函数都必须有唯一落点，不许丢。**

- [ ] **Step 2: 逐桶搬移**

只搬函数与它们私有的 helper / 常量；同名 helper 冲突时重命名并加域前缀，**不得删除任何 helper**。搬完删源文件。

- [ ] **Step 3: 验证 case 数一个字都没变**

```bash
PYTHONPATH= uv run --no-sync pytest --collect-only -q 2>/dev/null | tail -1
wc -l < <(PYTHONPATH= uv run --no-sync pytest --collect-only -q 2>/dev/null | grep "::" | sed 's/::.*//' | sort -u)
```

第一行必须与 Task 11 收口时的数字**完全一致**；第二行应约等于 65。

- [ ] **Step 4: 全量跑绿 + lint + 提交**

```bash
PYTHONPATH= uv run --no-sync pytest -q
uv run --no-sync ruff check tests/ && uv run --no-sync ruff format --check tests/ && uv run --no-sync mypy

git add tests/ docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md
git commit -m "测试：按域合并长尾测试文件"
```

---

### Task 13: 文档与治理

**Files:**
- Modify: `docs/ARCHITECTURE.md:559-580`
- Modify: `README.md`（仅在测试运行方式需要更新时）
- Modify: `PROGRESS.md`（记录实际前后指标）
- Modify: `docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md`

**预算：** new 0 / removed 0 / net 0

- [ ] **Step 1: 在 `§20.5 Testing Architecture` 追加两条**

```markdown
#### 表驱动优先

同族枚举断言必须写成单条表驱动用例：遍历全部成员、先收集再断言、失败消息点名参数。
不得为每个参数新增 case，也不得在循环里直接 `assert` 后中断（那只会报第一个失败者）。

#### 数量上限

自 2026-09-25 起，collected case 数不得净增长。新增行为需按「四个合法理由」申报，
并同时说明是否有可合并的同族旧 case（Test Delta Budget 的常设形式）。
```

- [ ] **Step 2: 更新 Test Ownership 的文件名映射**

Task 12 改过的文件名（含 `test_trade_gate_contracts.py`）在 `§20.5` 的 Test Ownership 段落与台账里同步更新。**合并后如果某条规则的权威文件已不存在，归属表必须改指新文件**——这步做漏了，下一次重构就会有人去找一个不存在的文件。

- [ ] **Step 3: PROGRESS 记录实测数字**

写实际值，不写目标值：collected before/after、文件数 before/after、覆盖率 before/after、每一批的 commit hash。

- [ ] **Step 4: 提交**

```bash
git add docs/ARCHITECTURE.md README.md PROGRESS.md \
  docs/superpowers/reviews/2026-09-25-test-consolidation-audit.md
git commit -m "文档：固化表驱动规范与测试数量上限"
```

---

### Task 14: 全量验收与远端 CI

**预算：** new 0 / removed 0 / net ≤ 0

- [ ] **Step 1: 全量门禁（与 `Makefile` 交付前门禁一致）**

```bash
PYTHONPATH= uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check .
uv run --no-sync mypy

cd web && npm test && npm run typecheck && npm run build && cd ..
```

- [ ] **Step 2: 数量与覆盖率对照**

```bash
grep -E "^TOTAL" var/test-consolidation/coverage-baseline.txt
PYTHONPATH= uv run --no-sync pytest -q --cov=src/astock_lens --cov-report=term \
  > var/test-consolidation/coverage-after.txt 2>&1
grep -E "^TOTAL" var/test-consolidation/coverage-after.txt
```

覆盖率不得低于基线。逐项核对：collected ≤1040、文件 ≤65、两者都写进台账。

- [ ] **Step 3: 确认生产侧零改动**

```bash
git diff <Task 0 记录的 HEAD>...HEAD --stat -- src/ configs/
```

期望：**空输出**。非空则本轮已经越过边界，停下来报告。

- [ ] **Step 4: 推远端并回报 CI**

推送到远端触发 `ci.yml`（全量 pytest 含 stress）：

```bash
git push
gh run list --limit 3
gh run watch <run-id>
```

**本地全绿不算完成。** 必须回报 run id 与最终结论；CI 红则回到对应批次修复。

- [ ] **Step 5: 收口台账**

台账最后一节写：run id、CI 结论、最终 collected / 文件数 / 覆盖率、以及与目标的差额说明。

---

### Task 15: 备用池（条件触发）

**触发条件：** Task 11 Step 5 的收口数字 > 1040（按当前细目预计为 1051，即必须执行）。

**预算：** new 0 / removed 由复核决定 / net 视缺口而定

- [ ] **Step 1: 对 35 个「6–9 例」文件做近邻家族审计**

审计方式与 Task 6 相同：找「同一断言的枚举展开」与「只有输入不同、断言结构完全一样」的家族。

- [ ] **Step 2: 只执行满足 §4.1 三条的家族**，逐条记入台账。

- [ ] **Step 3: 若补到 ≤1040 仍不足，停下报告所有者**

按规格 §5：**带数据回来重新裁决目标线，不自行凑数，不删除未登记的断言。** 报告里给出：当前实际值、可用减量上限、以及每一批的明细。

---

## Self-Review

**1. Spec coverage：** 规格 §4.1 表驱动规范 → Global Constraints + Task 1–9；§4.2 跨层去重 → Task 10；§4.3 低信息量清理 → Task 11；§3 冻结清单 → Global Constraints + Task 10 组 10 的特别说明；§5 分批预算 → Task 0–11 各预算 + Task 11 Step 5 收口；§6 文件合并 → Task 12；§7.1 数量 → Task 14 Step 2；§7.2 质量 → 各任务 Step + Task 14 Step 1；§7.3 追溯 → Task 0 Step 5 台账；§7.4 独立验证 → Task 14 Step 4；§7.5 常设上限 → Task 13；§7.6 禁止 → Global Constraints；§8 风险 → Task 15；§9 不做清单 → Global Constraints。无缺口。

**2. Placeholder scan：** 无 TBD / TODO。Task 5、6、7、9 的 CASE 表内容要求实现者先从源文件抄录再填写——这是刻意的，因为凭记忆写这些表就会造假。

**3. Type consistency：** `NON_VALUE_STATUSES`（Task 3 Step 1 定义）、`INVALID_QUERY_VALUES`（Task 4 Step 1）、`INVALID_RULE_CASES`（Task 5 Step 2）、`FORBIDDEN_IN_MODULE`（Task 11 Step 1）均为本任务内新定义、本任务内消费，不跨任务引用。`_scanner` / `_context` / `_compute` / `_closes` / `_columns` / `SCANNERS` / `FINANCIAL_METRICS` / `RANKED` / `SPIKED` / `WINDOW` / `RESERVED_STATES` / `PARITY` / `EXPECTED` 全部来自现有文件，未新增。
