# 第一步实施计划：研究证据基线

> **给执行的 AI：** 使用 `superpowers:executing-plans` 按任务实施。执行前阅读总计划；每个行为变更先记录失败测试。此阶段不修估值计算、不切存储后端。

**目标：** 固定迁移前的数据和分析证据，并使不完整行业映射生成的诊断报告如实标识来源与局限。

**架构：** 复用现有研究分析和校准引擎，只新增审计产物及证据字段。正式状态保持只读。

**技术栈：** 现有 Python、Pydantic、Typer、pytest；审计脚本使用标准库。

**规格：** 总计划的全局约束；`docs/OWNER-PROPOSAL-2026-09-18.md`；既有校准模型和快照写入权。

## 任务 1.1：建立输入与状态清单

**文件：** 新增 `scripts/audit_research_baseline.py`、`tests/unit/test_research_baseline_audit.py`；产物写指定目录。

**接口：** 脚本提供 `inventory(root: Path) -> tuple[dict[str, object], ...]`，按相对路径稳定排序；每项包含 `path`、`bytes`、`sha256`，CSV 再记录 `rows`、`columns`，JSON 记录形态/条数。`main()` 接收 `--root`、`--output`，仅写 output。目录不存在或文件损坏显式失败。
文件白名单为 `data/raw/**/*.csv`、`data/snapshots/**/*.json`、`data/watchlist/**/*.json`、`var/jobs/**/*.json`、`configs/**/*.yaml`、`uv.lock`、`pyproject.toml`；不读凭证或 `.env`。使用 CSV 解析计数，不能按换行计数，因为 neodata 单元格可能含换行。

- [ ] 写失败测试：多行 CSV 单元格只计一行，哈希稳定，损坏 JSON 不伪装成空，执行后根目录文件摘要不变。

```python
from pathlib import Path
from scripts.audit_research_baseline import inventory

def test_multiline_cell_is_one_record(tmp_path: Path) -> None:
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    (raw / "sample.csv").write_text('code,content\n1,"甲\n乙"\n', encoding="utf-8")
    found = inventory(tmp_path)
    assert len(found) == 1
    assert found[0]["rows"] == 1
    assert found[0]["path"] == "data/raw/sample.csv"
```

- [ ] 运行 `uv run pytest tests/unit/test_research_baseline_audit.py -q`，保存失败原因。
- [ ] 实现：对每个文件流式计算 SHA-256；CSV 使用 `csv.DictReader` 计数；JSON 使用 `json.load` 并验证已有快照/Job/Watchlist 的外壳字段；文件读取前后大小及修改时间变化则中止，提示固定输入后重试。

```python
import hashlib
from pathlib import Path

def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
```

- [ ] 测试转绿后运行新增命令：

```bash
uv run python scripts/audit_research_baseline.py --root . --output var/acceptance/baseline-20260918/input-inventory.json
git rev-parse HEAD
git status --short
```

- [ ] 将 HEAD、工作区差异摘要与清单路径记录到 `docs/REVIEW_NOTES.md`；不得提交全量产物。提交主题：`建立研究数据与正式状态的离线审计基线`。

**验收：** 无 Provider 调用，原件哈希未改变，五只标的旧快照与全池 Raw 分开记录。行业九只缺口使用实际计算得到的研究池复核，不能继续用财务覆盖名单冒充研究池。

## 任务 1.2：校准报告显式携带行业证据

**修改：** `src/astock_lens/calibration/candidate_report.py`、`calibration/render.py`、`cli/app.py`。
**测试：** `tests/unit/test_candidate_calibration.py`、新增 `tests/unit/test_industry_evidence.py`、`tests/integration/test_calibration_readiness_cli.py`、`tests/integration/test_command_snapshot_ownership.py`。

**新增模型与接口（放 candidate_report.py）：**

```python
from datetime import datetime
from typing import Literal
from astock_lens.domain.models import DomainRecord

class IndustryEvidence(DomainRecord):
    origin: Literal["canonical", "external", "unspecified"]
    source_ref: str | None = None
    source_sha256: str | None = None
    mapping_as_of: datetime | None = None
    diagnostic_only: bool = True

class IndustryCoverage(DomainRecord):
    missing_symbols: tuple[str, ...]
    known_count: int
    total_count: int
    ratio: float
```

给 `CandidateCalibrationReport` 增加 `industry_evidence: IndustryEvidence`（兼容默认 origin=unspecified、diagnostic_only=True）与 `unknown_industry_symbols: tuple[str, ...] = ()`。
给 `generate_calibration_report` 增加可选 `industry_evidence: IndustryEvidence | None = None`，保持现有调用兼容；内部仍按所有参与 factor/strategy 的唯一标的计算覆盖，CLI 再核对其与研究池一致。
`--industry-map` 仍允许不完整诊断；新增 `--industry-map-as-of` 为可选的带时区 ISO 时间，未提供就存 `None`，不能用文件 mtime 充当事实日期。canonical 读模型中的 as_of，禁止未来记录进入历史正式口径。
本阶段所有校准报告均为诊断材料，`diagnostic_only=True`；不要新增“已批准”标识。

- [ ] RED：将下列测试放新增文件，并在现有集成测试复制真实 fixture 生成方式，断言外部缺一只时名单仍保留且 missing_symbols 恰好含该只；canonical 缺一只仍拒绝。

```python
from datetime import UTC, datetime
from astock_lens.calibration.candidate_report import (
    IndustryEvidence, generate_calibration_report,
)

def test_external_origin_survives_report_serialization() -> None:
    evidence = IndustryEvidence(origin="external", source_ref="sample.csv")
    report = generate_calibration_report(
        as_of=datetime(2026, 9, 17, 15, tzinfo=UTC),
        strategy_results=(), factor_results=(),
        industry_map={"600519.SH": "白酒Ⅱ"},
        industry_evidence=evidence,
    )
    payload = report.model_dump(mode="json")
    assert payload["industry_evidence"]["origin"] == "external"
    assert payload["industry_evidence"]["mapping_as_of"] is None
    assert payload["industry_evidence"]["diagnostic_only"] is True
```

- [ ] 运行 `uv run pytest tests/unit/test_industry_evidence.py tests/integration/test_calibration_readiness_cli.py -q`，保存失败。
- [ ] 最小实现：已有 `all_symbols` 与 `known_symbols` 求差，稳定排序存字段；来源和哈希由 CLI 注入；Markdown 明确打印“诊断材料、外部/规范映射、日期未知/已声明、缺失代码”。禁止把未知日期写成分析日。

```python
unknown_industry_symbols = tuple(sorted(set(all_symbols) - set(known_symbols)))
```

- [ ] 单独覆盖未来外部映射的诊断行为：允许显示，但标明晚于分析时点、不得作为该时点正式行业证据；不得将 external 转成 canonical。canonical 仍由 `build_industry_map` 过滤未来记录。
- [ ] 运行四个测试文件及公共静态检查，记录到工作记忆。提交主题：`在校准报告中保存行业映射来源与覆盖缺口`。

**验收：** 不添加容忍百分比、不排除缺行业标的、不批准门槛；报告字段改变但策略值完全相同。

## 任务 1.3：生成一次离线研究基线，供迁移对照

**新增：** `scripts/capture_research_baseline.py`、`tests/integration/test_research_baseline_capture.py`。
**复用：** `run_research_analysis`、`load_universe_config`、`load_factor_config`、`load_scanners`、校准报告生成器。

**接口：** `capture(*, csv_root: Path, as_of: datetime, output_dir: Path, config_root: Path, industry_path: Path) -> Path`。
脚本 CLI 参数分别为 `--csv-root`、`--as-of`、`--output-dir`、`--config-root`、`--industry-path`。
日期 CLI 遵循上海收盘时间；完整 ISO 时间也必须带时区。只调用一次 `run_research_analysis`，其返回结果同时生成报告与 factor/strategy JSONL 交换文件；本任务不优化内部重复归一化。

- [ ] RED：在新集成测试沿用 `tests/integration/test_calibration_readiness_cli.py::_write_fixture` 的 100/40 样本代码，放入本文件私有辅助函数；断言 capture 返回 manifest 路径，四个交换文件存在，原快照/Watchlist/Job 内容不变；通过 monkeypatch 将外部 Provider fetch 设为抛异常，捕获流程仍通过。
- [ ] 执行 `uv run pytest tests/integration/test_research_baseline_capture.py -q`。
- [ ] 实现一次分析、多产物渲染；JSONL 每行直接用领域对象的 `model_dump_json()`，排序键为因子 `(symbol, factor)`、策略 `(strategy_id, symbol)`，不四舍五入数值；manifest 保存输入哈希、as_of、配置摘要与产物哈希，标记 `artifact_kind=research_diagnostic`，不是 SnapshotStore。

```python
def write_records(path, records, *, key):
    with path.open("w", encoding="utf-8") as stream:
        for record in sorted(records, key=key):
            stream.write(record.model_dump_json() + "\n")
```

- [ ] 使用 9 月 17 日的 canonical 成员 CSV 显式作为诊断输入，记录其实际 provenance；缺行业仍产出诊断：

```bash
uv run python scripts/capture_research_baseline.py --csv-root data/raw --as-of 2026-09-17 --config-root configs --industry-path data/raw/westock/industry/2026-09-17.csv --output-dir var/acceptance/baseline-20260918/analysis
```

- [ ] 产物：`manifest.json`、`factors.jsonl`、`strategies.jsonl`、`research-universe.json`、`calibration.json`、`calibration.md`。完整 JSONL 是明确的 CLI 交换证据，不注册成持久化业务状态。
- [ ] 对照任务 1.1 的哈希；变动则本次基线作废并定位并发写入。全量回归通过后提交主题：`固化迁移前的研究分析与校准基线`。

**第一步出口：** 真实研究池和四榜数字可复核；九只缺口若与先前结论不同，记录原因而不是改数据凑数；迁移前基线被固定。随后进入第二步，不在此处先做估值修复。
