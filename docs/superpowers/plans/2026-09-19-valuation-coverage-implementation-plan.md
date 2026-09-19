# 第二步实施计划：估值覆盖扩容（Valuation Coverage）

> **给执行的 AI：** 使用 `superpowers:executing-plans` 按任务实施。每个行为变更先记录失败测试。
> 本计划**不新增任何覆盖率阈值、不改策略必需因子、不重算正式快照**。

**目标：** 让"估值覆盖受限"从一句结论变成可复现的证据与可重复运行的补齐能力——
分批补抓不丢数据、覆盖数字能从原始内容块重算、缺口始终显式。

**背景证据（2026-09-19 只读核对，非本轮发明）：**

- 研究池 2,303 只（`var/acceptance/baseline-20260918/analysis/research-universe.json`）；
- 落地原始估值只有 2 只标的（`data/raw/neodata/valuation/2026-09-17.csv`），
  请求的是 5 只、源端只回 2 只；
- 13,818 条策略评估里 `value` 可打分 2 只、`garp` 1 只，其余 2,301 只的估值因子
  状态是 `NOT_APPLICABLE`（**不是** `SOURCE_ERROR`）；
- `docs/REMAINING_PRODUCT_BLOCKERS.md` 里"90% 覆盖率"没有设计文档出处，
  按 `AGENTS.md` 属 `Deferred`，需所有者签发。

**架构：** 只在既有 `Provider → Raw → Normalized → Quality` 边界内加能力。
落地仍是"数据集 + 取数日"一个文件，但写入从"整天覆盖"改为"按块身份合并"，
这样分批、断点、重跑共用同一条路径。覆盖报告只读 Raw + 策略配置，不碰 Strategy 结果。

**技术栈：** 现有 Python、Pydantic、Typer、pytest；不新增第三方依赖。

**规格依据：** 设计规格 §24.1（neodata 定位与三条限制）、`AGENTS.md`
（禁止静默兜底、阈值 Deferred）、`docs/OWNER-PROPOSAL-2026-09-18.md` 切片 2/3。

---

## 任务 1：估值落地改为按块身份合并

**问题：** `land_neodata_blocks` 用 `open("w")` 覆盖整天文件。缺口驱动的批量补抓必然要
分多轮执行，任何"第二轮写进去就冲掉第一轮"的实现都会静默丢数据。

**文件：** `src/astock_lens/data/sync.py`、`tests/unit/test_neodata_landing.py`。

**接口：** `land_neodata_blocks` 签名不变；写入前读回已有行，按**块身份**建索引：

- 内容块里有 `标的代码（统一输出字段名）` → 身份是该代码；
- 有 `板块代码` → 身份是该板块代码；
- 两者都没有 → 身份是 `(type, desc, content)` 整体，只做去重。

同身份的新块替换旧块，不同身份取并集。原子写（复用 `_atomic_write_rows`）。

- [ ] RED：新增"两个不同标的各落一次，文件里两块都在"的失败用例；把既有
  `test_the_same_day_replaces_and_another_day_is_kept` 改写成"同一标的当天重抓被替换、
  别的标的块不受影响"。保存失败输出。
- [ ] GREEN：实现合并写入。
- [ ] `uv run pytest tests/unit/test_neodata_landing.py tests/integration/test_valuation_pipeline.py -q` 全绿。

**验收：** 两批不同标的 → 两块都在；同标的复抓新内容 → 只留新内容；行数 = 块数，无重复。

---

## 任务 2：估值覆盖报告（字段级 + 策略必需因子交集）

**问题：** 现在没有人能从产物里回答"Value/GARP 到底差几个字段"。`entity` 不能当覆盖依据，
因子状态又分不出"没采"和"不适用"。

**文件：** 新增 `src/astock_lens/data/quality/valuation_coverage.py`；
`src/astock_lens/data/quality/__init__.py`；新增 `tests/unit/test_valuation_coverage.py`。

**接口：**

```python
def valuation_coverage(
    observations: Sequence[ValuationObservation],
    *,
    as_of: datetime,
    universe: Sequence[str],
    strategy_configs: Sequence[StrategyConfig] = (),
) -> ValuationCoverageReport: ...
```

模型：`MetricCoverage(metric, symbols_with_value, ratio)`、
`StrategyCoverage(strategy_id, required_factors, scoreable_symbols, missing_factor_symbols)`、
`ValuationCoverageReport(as_of, universe_size, metrics, strategies, covered_symbols, uncovered_symbols)`。

规则：只看 `available_at <= as_of` 且 `value is not None`；**不把缺失写成 0**；
覆盖分母是显式传入的研究池，缺参数直接报错。策略侧按 `required_factors` 的交集计算，
不硬编码策略名。

- [ ] RED：写"未采集标的记入 uncovered、不进 0"、"必需因子缺一即不可打分"、
  "未来日期的观测不计入"三个失败用例。
- [ ] GREEN：实现纯函数与模型。
- [ ] `uv run pytest tests/unit/test_valuation_coverage.py -q` 全绿。

**验收：** 用 2026-09-17 真实落地重算，必须复现 `value=2`、`garp=1` 与基线一致；
该数字来自内容块，与 `strategies.jsonl` 无关。

---

## 任务 3：缺口驱动的批量补抓命令 `astock sync-valuation`

**问题：** `astock sync --valuation` 要求显式 `--symbol`，没有"按缺口多点补"的入口，
也没有断点与缺口清单。

**文件：** `src/astock_lens/cli/app.py`；新增 `tests/integration/test_valuation_backfill_cli.py`。

**接口：** `astock sync-valuation --as-of DATE --universe PATH [--max-rounds 2] [--output PATH] [--limit N]`

- `--universe` 接受研究池文件（JSON 的 `research_symbols` 或 CSV 的 `symbol` 列），必须显式给；
- 每轮：算缺口 → 请求 → 合并落地 → 重算缺口；无进展即停，不空转；
- 打印每轮的 requested / landed / still missing，并把剩余缺口写进 `--output`；
- 仍有缺口时退出码 1（缺口是事实，不是成功）；
- 凭证不可用时立刻失败，不发请求。

- [ ] RED：用假 provider 写"第一轮只回一半、第二轮补齐"、"重复运行不再请求已覆盖标的"、
  "缺口未完时退出码 1"三个失败用例。
- [ ] GREEN：实现命令与循环。
- [ ] `uv run pytest tests/integration/test_valuation_backfill_cli.py -q` 全绿。

**验收：** 离线可复现；不会把缺失写成 0；不会因为重跑而丢已有落地。

---

## 任务 4：真实探针（凭证门禁）与文档订正

**前置门禁：** neodata 凭证 12 小时有效。本轮实测 `saved_at=2026-09-18 20:07`，
已过期，因此**不发起真实全量请求**，只记录 blocked 证据。

- [x] 记录 `load_token()` 状态与时间证据到 `docs/REVIEW_NOTES.md`（§31.4）。
- [x] 所有者刷新凭证后执行（2026-09-19 当晚完成，实际用的命令见下；
      注意 `--as-of` 必须用取数当天，写进 09-17 会把今天的数据混进冻结基线）：

```bash
uv run astock sync-valuation --as-of 2026-09-19 \
  --universe var/acceptance/baseline-20260918/analysis/research-universe.json \
  --batch-size 5 --max-rounds 8 \
  --output var/acceptance/valuation-backfill-20260919/missing.json
```

结果：8 轮约 77 分钟，落地 2,241 / 2,303（97.3%），缺口 62 只；
覆盖核对 **Value 2 → 1,578、GARP 1 → 850**。详见 `docs/REVIEW_NOTES.md` §32。

- [x] 订正 `docs/REMAINING_PRODUCT_BLOCKERS.md` 两处事实：落地是"请求 5 只、回 2 只"，
  不是"抓了 5 只"；缺失状态是 `NOT_APPLICABLE`，不是 `SOURCE_ERROR`；
  并注明 90% 阈值待所有者签发。
- 新增发现（超出原计划）：源的批量响应被截到 1–2 块，原吞吐估算不成立 →
  `sync-valuation` 增加 `--batch-size`；报告命令两处 O(N×M) 退化已修（251s → 10s）。

**本任务之后仍待所有者决定**：是否重算正式因子与策略快照；是否把新 Raw 重新归一化
进 Parquet / DuckDB（`scripts/migrate_storage.py`，会重写 `data/normalized/**`）。

## 任务 5：本阶段明确不做

- 不新增覆盖率阈值、不改 `configs/strategies/*.yaml` 的必需因子；
- 不重算、不覆盖 `data/snapshots/**` 与 `var/acceptance/baseline-20260918/**`；
- 不发布 Candidate，不触碰绝对质量门槛、Market Regime、Market Validation、Signal；
- 不改 `configs/universe.yaml` 与研究池口径。

**总验收：** `uv run pytest` 全绿、`ruff check`、`ruff format --check`、`mypy` 全过；
覆盖数字可复现；缺口清单落盘；结论写入 `.workbuddy/memory/2026-09-19.md`。
