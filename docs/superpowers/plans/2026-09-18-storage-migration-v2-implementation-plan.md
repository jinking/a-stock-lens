# 第二步实施计划：完整证据的 Parquet 与 DuckDB 迁移

> **给执行的 AI：** 使用 `superpowers:executing-plans`。先阅读总计划和第一步基线。本文件替代旧存储计划的实施步骤；S1—S4 的提案不等于历史批准。下面接口是目标接口，须按失败测试逐项实现。

**目标：** 分析读取已归一化的不可变 Parquet 数据包，业务状态默认进入 DuckDB；保留原始 CSV 与历史 JSON，验证后统一切换并演练回滚。

**架构：** 在 data 层建立存储契约与证据模型，pipeline 依赖它们；不能让 data 层导入 pipeline。Parquet 保存值、质量结论和来源元信息，JSON manifest 只保存批次定位与摘要。API、CLI 通过已有 Store 协议读业务状态。

**技术栈：** PyArrow Parquet、DuckDB、现有 Pydantic 模型、pytest、Typer。

**规格：** `docs/STORAGE.md` 和总计划；保留六态、时点、血缘和快照不可覆盖约束。

## 一、进入条件与明确不变项

- 第一阶段基线可读取、哈希未变；没有在迁移过程中同时采集数据或修改规则。
- 本阶段不得修复已发现的估值旧值回退、PEG 定义或源缺失语义；迁移必须保存现有结果，行为修复在第三阶段另建基线。
- S1/S2 未确认可做到临时目录与契约测试，不发布生产布局；S3/S4 未确认可做临时库演练，不切默认。
- 正式报告中 `SOURCE_ERROR` 等既有状态必须保持。当前系统未生成的状态不能为满足“六态”而凭空生成。

## 二、目标目录、数据包与接口

采用总计划 S1 建议时：

```text
data/raw/                                      原件保留
data/normalized/v1/2026-09-17/<bundle_id>/       不可变规范数据包
  daily_bars.parquet
  securities.parquet
  financial_observations.parquet
  valuations.parquet
  financial_evidence.parquet
  diagnostics.parquet
  headers.parquet
  industry_memberships.parquet
  manifest.json                               小型清单、哈希、版本、计数
data/normalized/v1/2026-09-17/active.json        显式选择的批次引用
var/astock.duckdb                              snapshots/watchlist/job_runs
var/acceptance/<run_id>/                       校验报告、演练结果
```

`bundle_id` 为规范输入指纹的 SHA-256：包含 as_of、Raw 文件内容哈希、normalizer 版本、质量规则版本、持久化 schema 版本。因子/策略配置不改变规范数据，但进入分析产物血缘。同一日期新输入生成新批次，不能覆盖旧批次。
`active.json` 只由显式 `storage materialize --activate` 在完整发布后原子更新；读取命令不能创建、改写指针。可传 `--normalized-bundle <bundle_id>` 固定重放批次；指针仅表示“显式选中的批次”，不能声称自动反映所有后来落地的 Raw。

每天正常流程明确改成：同步 Raw → `storage materialize --activate` → daily/scan/calibrate。只同步未 materialize 时，分析仍明确显示选中旧批次；`doctor` 比较源摘要并提示待归一化。不能隐式重算或静默回退 CSV。

### 证据保存规则

| 表 | 内容与键 |
| --- | --- |
| daily_bars | 当前 `outcome.bars.daily_bars` 全字段；业务键 symbol+trade_date；原 ordinal 用于精确重放 |
| securities | `outcome.securities` 与 `outcome.bars.securities` 分别带 slot，避免两处内容混淆；slot+symbol |
| financial_observations | 门禁后 `outcome.bars.observations` 全字段；source+symbol+metric+report_period+available_at；不为消除重复擅自选一条 |
| valuations | `outcome.bars.valuations` 全字段，包括 text_value、as_of、available_at；source+symbol+metric+valuation_date+available_at |
| financial_evidence | 原 FinancialInputs 中每份 outcome 的 observations，带 dataset、outcome ordinal、row ordinal；包括已被门禁拒绝的重复/非法记录证据 |
| diagnostics | 行情 parse_failures/quality issues、财务 failures/issues、估值 failures；类型明确的稀疏列加类别、父记录 ID、ordinal；不把整段 JSON 文本塞进一个列 |
| headers | RawDataset 元信息（不带 payload）、各 report/outcome 的计数、版本、缺列、缺数据集、source_file、not_yet_available 等小字段；显式类型的 struct/list |
| industry_memberships | 原 IndustryMembership 全字段；缺源时 manifest 显式记录，不伪造空市场；不将跨日映射倒填 |

每张业务值表增加 `record_status`；可空字段增加 `<field>_status` 或配套按字段状态的 Arrow struct。存在具体质量/解析结论时保存该结论，否则只区分有值 VALUE/无值 NULL，不臆造 STALE 或 NOT_APPLICABLE。status 属存储证据，重放后领域对象及原质量报告仍应一致。
财务被拒绝的记录只放 evidence，不能进入 factor 可消费表。重复主键在原规范结果中若已经存在，迁移必须暴露为 P0；不能靠增加 ordinal 偷偷通过业务唯一性校验。evidence 的 ordinal 只是保留全部拒绝证据。
空表也必须有完整 Arrow schema；时间为 `timestamp[us, tz=Asia/Shanghai]` 或标准化 UTC 后精确保留时刻，日期为 `date32`，浮点为 `float64`，状态为固定六值字符串验证，禁止 NaN 冒充缺失。

Raw payload 不复制到 Parquet：原始 CSV+内容哈希承担回放职责。CSV/Parquet 双读对比的 canonical view 只剥离 `raw_bars.payload`、`raw_securities.payload`；保留所有其他 metadata/quality/diagnostics 字段。写入器和读取器都不得丢失现有消费者使用的字段。

### 新接口目录

| 文件 | 职责 |
| --- | --- |
| `data/repository/models.py` | 从 stages 移入 FinancialInputs、ValuationInputs、NormalizeOutcome；新增 NormalizedBundle、BundleRef |
| `data/repository/contracts.py` | NormalizedRepository 协议 |
| `data/repository/csv.py` | 原 normalize_stage 的 CSV 回放实现 |
| `data/storage/paths.py` | 唯一有效路径/后端解析 |
| `data/storage/arrow_codec.py` | 完整模型与显式 Arrow schema 双向转换 |
| `data/storage/parquet.py` | 原子发布、读回、校验 manifest 的文件适配器 |
| `data/storage/verify.py` | 独立比较与分级报告 |
| `data/storage/migrate.py` | 历史状态迁入/迁出、事务与审计 |
| `jobs/duckdb_store.py` | 保持执行顺序的 JobStore |
| `jobs/resolve.py` | 后端解析 |
| `cli/storage.py` | 新增 storage 子命令；app.py 只注册 |

## 任务 2.1：统一配置解析，暂不改变默认

**修改：** settings.py、cli/app.py、api/app.py、snapshots/resolve.py、watchlist/store.py。
**新增：** storage/paths.py、tests/unit/test_storage_paths.py。

接口：`resolve_storage_paths(*, config_path: Path | None = None, environ: Mapping[str, str] | None = None) -> StoragePaths`。
`StoragePaths` 为冻结 dataclass，字段 `database: Path`、`normalized_root: Path`、`snapshot_root: Path`、`watchlist_root: Path`、`job_root: Path`、`sources: Mapping[str, str]`。database 取 `ASTOCK_DATABASE > config.storage.database`；normalized_root 取 `ASTOCK_NORMALIZED_ROOT > config.storage.parquet_root / "normalized"`；三个 JSON root 保留现有环境变量和既有默认。
相对路径统一相对命令工作目录，保持当前语义。指定配置文件缺失/非法必须报错，不能“默认成功”。既有 `StorageSettings` 的必填 storage 段保持必填，不引入静默默认配置。
两个 store resolver 新增 keyword-only `database: Path | None = None`，显式传入时优先使用；兼容直接调用旧 resolver(root) 的旧目录行为。CLI/API 总是传统一 database；显式 API `snapshot_root` 参数继续隔离测试：未显式 database 时使用该 root 下旧兼容数据库位置，避免测试触碰生产库。

- [ ] RED：env 覆盖配置；配置非法失败；CLI/API 指同库；显式测试 root 不污染默认目录。

```python
from pathlib import Path
from astock_lens.data.storage.paths import resolve_storage_paths

def test_database_override(tmp_path: Path) -> None:
    config = tmp_path / "app.yaml"
    config.write_text("app:\n  name: test\nstorage:\n  database: var/base.duckdb\n  parquet_root: data\n")
    target = tmp_path / "isolated.duckdb"
    result = resolve_storage_paths(config_path=config, environ={"ASTOCK_DATABASE": str(target)})
    assert result.database == target
    assert result.sources["database"] == "env"
```

- [ ] 运行 `uv run pytest tests/unit/test_storage_paths.py tests/unit/test_settings.py tests/unit/test_api.py -q`，记录 RED。
- [ ] 最小实现使用单一 resolver；`doctor` 打印 effective path 和来源；保持 json/csv 默认。
- [ ] GREEN、静态检查；提交 `统一分析与业务存储的有效路径解析`。

## 任务 2.2：提取完整归一化读取边界

**新增：** repository/models.py、contracts.py、csv.py；修改 stages.py、analysis.py、daily.py；测试新增 `tests/unit/test_normalized_repository.py`。

把三个模型原样从 stages 移入 models，stages 重导出兼容原 import；CSV 算法移入 repository/csv.py。迁移 FinancialInputs 等模型时同步引用，data 层不得 import pipelines。

```python
from datetime import datetime
from typing import Protocol
from astock_lens.data.repository.models import NormalizeOutcome

class NormalizedRepository(Protocol):
    def read(self, *, as_of: datetime, dataset: str, securities_dataset: str) -> NormalizeOutcome:
        """只读已选数据源，缺失或损坏显式失败。"""
        ...
```

`CsvNormalizedRepository(csv_root: Path)` 实现该协议；保留原 financial_inputs/valuation_inputs 可调用入口或兼容转发。
`normalize_stage` 新增 `repository: NormalizedRepository | None = None`；为 None 时暂时使用 CSV repository。
analysis 的 `compute_research_universe`、`compute_factor_state`、`run_analysis`、`run_research_analysis` 和 daily 的 `run_daily` 都加同名可选注入参数并贯通。`run_research_analysis` 内一次 read，多阶段复用同一 outcome，保留原 public 行为。

- [ ] RED：计数型 fake repository 证明一次 research 分析只读一次；fake 抛异常时不回退 CSV；原 CSV 结果不变。
- [ ] 新增单测片段；以下 AS_OF 和空 outcome 在本文件按模型构造，或复用该文件调用 CSV fixture 得到的结果，不引用跨测试私有 fixture。

```python
def test_csv_repository_matches_stage():
    from datetime import UTC, datetime
    from pathlib import Path
    from astock_lens.data.repository.csv import CsvNormalizedRepository
    from astock_lens.pipelines.stages import normalize_stage
    root = Path("tests/fixtures/csv")
    day = datetime(2026, 9, 17, 15, tzinfo=UTC)
    repo = CsvNormalizedRepository(root)
    actual = repo.read(as_of=day, dataset="daily_bars", securities_dataset="securities")
    expected = normalize_stage(csv_root=root, as_of=day)
    assert actual == expected
```

- [ ] 运行 `uv run pytest tests/unit/test_normalized_repository.py tests/integration/test_analysis_pipeline.py tests/integration/test_research_universe_flow.py tests/integration/test_daily_pipeline.py -q`。
- [ ] 实现一次读取，抽出私有 `research_universe_from_outcome`，由现有公开函数复用；不能重写因子/Universe 算法。
- [ ] GREEN 后提交 `提取归一化数据读取边界并复用单次分析输入`。

## 任务 2.3：完整证据编码与 Parquet 原子发布

**新增：** arrow_codec.py、parquet.py、`tests/unit/test_parquet_normalized_store.py`、`tests/unit/test_arrow_codec.py`。
**前置：** S1/S2 已记录；未确认时仅在 pytest 临时目录验证，不能发布正式批次。

新增 `NormalizedBundle`：`outcome: NormalizeOutcome`、`memberships: tuple[IndustryMembership, ...]`、`source_hashes: tuple[tuple[str, str], ...]`、`normalizer_version: str`、`schema_version: str = "v1"`。
新增 `BundleRef`：`bundle_id: str`、`as_of: datetime`、`path: Path`、`manifest_sha256: str`。
`ParquetNormalizedStore(root: Path)` 提供 `write(bundle: NormalizedBundle) -> BundleRef`、`read(ref: BundleRef) -> NormalizedBundle`、`activate(ref: BundleRef) -> None`、`resolve(*, as_of: datetime, bundle_id: str | None = None) -> BundleRef`。
Arrow codec 提供 `encode(bundle) -> dict[str, pyarrow.Table]`、`decode(tables, manifest) -> NormalizedBundle`；PyArrow lazy import，缺依赖报 `uv sync --extra data`，不写假结果。

- [ ] RED：往返保留字段/状态/诊断；空表 schema；跨日财报时区；文本估值；非法 float；同输入幂等；发布途中失败不可见；已有文件损坏不得认为幂等成功。

```python
def test_quality_evidence_roundtrip(tmp_path):
    from datetime import UTC, datetime
    from pathlib import Path
    from astock_lens.data.repository.csv import CsvNormalizedRepository
    from astock_lens.data.repository.models import NormalizedBundle
    from astock_lens.data.storage.parquet import ParquetNormalizedStore
    from astock_lens.data.storage.verify import canonical_view
    day = datetime(2026, 9, 17, 15, tzinfo=UTC)
    outcome = CsvNormalizedRepository(Path("tests/fixtures/csv")).read(
        as_of=day, dataset="dirty_bars", securities_dataset="securities",
    )
    bundle = NormalizedBundle(outcome=outcome, memberships=(), source_hashes=(), normalizer_version="v1")
    store = ParquetNormalizedStore(tmp_path)
    ref = store.write(bundle)
    restored = store.read(ref)
    assert canonical_view(restored) == canonical_view(bundle)
    assert restored.outcome.quality_report == outcome.quality_report
```

`canonical_view` 在此任务先实现于 verify.py：递归 model_dump(mode=json)，仅将两个 Raw payload 设 None；集合型表按业务键排序，具有业务顺序的 issues、Job、tuple 用 ordinal 保持，不去重。该函数是比较视图，不改变生产对象。

- [ ] 运行 `uv run pytest tests/unit/test_arrow_codec.py tests/unit/test_parquet_normalized_store.py -q`，记录 RED。
- [ ] 实现明确 Arrow schema；不同 nested record 类别各有明确表/列映射。不能依赖首行猜类型，也不能把大量 observations 塞入 headers/manifest。
- [ ] 发布算法按以下顺序，加入故障注入测试：

```text
取得单写者文件锁（非阻塞失败并给出占用路径）
计算输入指纹；目标已存在则核对 manifest 和全部文件哈希
在同一文件系统创建独占 staging 目录
分批写 Parquet，写最后一份 manifest，逐文件 flush/fsync
读回并校验 schema/计数/哈希
原子 rename staging 为最终目录并 fsync 父目录
仅 activate 显式调用才更新 active.json；失败时保留旧指针
释放锁；崩溃残留 staging 不参与 resolve
```

- [ ] read 核对 manifest、文件存在性、hash/schema 与 as_of，损坏即错误；禁止在读路径重新写 manifest 或 fallback。
- [ ] GREEN、静态检查；提交 `持久化完整归一化数据与质量证据`。

## 任务 2.4：独立比对、显式物化与两路分析

**新增：** `cli/storage.py`、`tests/unit/test_storage_verifier.py`、`tests/integration/test_storage_cli.py`；完善 verify.py。
**修改：** cli/app.py、analysis.py、daily.py；基线 capture 脚本支持 `--source csv|parquet`、`--normalized-root`、`--normalized-bundle`。

新增 `MigrationIssue` 字段：`severity: ErrorSeverity`、`table: str`、`key: str | None`、`field: str | None`、`reason: str`。
新增 `MigrationReport` 字段：`as_of: datetime`、`source_hashes`、`bundle_id: str`、`issues: tuple[MigrationIssue, ...]`、`counts: dict[str, tuple[int, int]]`；`can_switch` 当且仅当没有 P0 且所有规定校验已完成。未运行项必须记录 P0，不能用空 issues 冒充通过。
接口 `verify_bundle(*, expected: NormalizedBundle, actual: NormalizedBundle, bundle_id: str) -> MigrationReport`；物理 schema/hash 校验由 store 先完成，失败纳入报告而非跳过。

- [ ] RED：少列、时区丢失、少一条、状态改变、诊断丢失、主键冲突、值错而总数相同，分别触发 P0；既有源数据质量 P2 在两路一致时不冒充迁移失败。
- [ ] `uv run pytest tests/unit/test_storage_verifier.py tests/integration/test_storage_cli.py -q`。
- [ ] 实现 CLI 目标：

```text
astock storage materialize --as-of DATE --output-root PATH [--activate]
astock storage verify --as-of DATE --normalized-root PATH --bundle-id ID --output-dir PATH
astock storage inspect --as-of DATE --normalized-root PATH [--bundle-id ID]
```

materialize 从 CSV repository 构造数据包，单次归一化后写，激活必须晚于完整校验。verify 从 CSV replay 独立重建 expected，再读 actual，按类型、逐表计数、业务键、每字段值与状态、全部诊断证据比对；是离线读取，不调用 Provider 网络实现。
对比值使用规范 float64 精确往返，不用排名四舍五入掩盖差异；日期与 aware datetime 规范到同一表示再比较。
CLI 返回码：0=检查全部完成且无 P0；1=校验不通过或无法完成；业务原有 P2 在报告中保留。

- [ ] 为分析命令注入 `ParquetNormalizedRepository(store, bundle_id=None)`，其 read 返回 bundle.outcome；canonical 行业加载也读取该 bundle 的 memberships，不再从 Raw 顺手加载。外部 `--industry-map` 仍为显式输入例外，记录来源。
- [ ] monkeypatch LocalCsvProvider.fetch/read_raw_rows 在 Parquet 路径抛错，scan/calibrate/universe/factors/daily 仍可读取已有包；缺包显式失败。
- [ ] GREEN 后提交 `增加迁移校验与显式归一化数据包命令`。

## 任务 2.5：修正 DuckDB Store 并补齐 JobStore

**新增：** jobs/duckdb_store.py、jobs/resolve.py、`tests/unit/test_duckdb_job_store.py`。
**修改：** snapshots/duckdb_store.py、watchlist/duckdb_store.py、cli/app.py；测试 `test_duckdb_snapshot_store.py`、`test_watchlist_store.py`、`test_job_store.py`。

`DuckDBJobStore(database: Path)` 实现原 JobStore；`resolve_job_store(root: Path, *, backend: str | None = None, database: Path | None = None) -> JobStore` 默认暂为 json；新环境变量 `ASTOCK_JOB_BACKEND`。CLI `_job_store()` 返回 JobStore。
Job 表必须有顺序：

```sql
CREATE TABLE job_runs (
  as_of DATE NOT NULL,
  job_type VARCHAR NOT NULL,
  ordinal BIGINT NOT NULL,
  payload JSON NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (as_of, job_type),
  UNIQUE (as_of, ordinal)
);
```

同日期同阶段 UPDATE 保留 ordinal；首次 INSERT 在单写事务内取下一 ordinal。日期键保持现有 `.date()` 语义，payload 保存原时区时间，不把日期改成时间戳主键。

- [ ] RED：复用 test_job_store 的全部业务断言到两个 backend；新增顺序替换、跨日、损坏 payload、读未建库不创建文件、已存在库缺表/损坏明确报错。

```python
def test_unwritten_database_is_not_created(tmp_path):
    from datetime import UTC, datetime
    from astock_lens.jobs.duckdb_store import DuckDBJobStore
    database = tmp_path / "jobs.duckdb"
    store = DuckDBJobStore(database)
    assert store.runs(datetime(2026, 9, 17, 15, tzinfo=UTC)) == ()
    assert not database.exists()
```

- [ ] 运行 `uv run pytest tests/unit/test_duckdb_job_store.py tests/unit/test_duckdb_snapshot_store.py tests/unit/test_watchlist_store.py tests/unit/test_job_store.py -q`。
- [ ] 全部只读方法使用只读连接，不执行 DDL。写入初始化一次性建立全部三类表与 schema_version，避免“已存在共享库但未初始化另一个表”的歧义。
- [ ] 快照写入在同一事务完成查重、canonical 内容比较、INSERT；禁止检查后无条件 `INSERT OR REPLACE`。已有内容损坏必须报错，不能返回 None 后覆盖。并发写入受单写者锁保护，锁忙明确失败。
- [ ] 在独立 adapter 测试库中初始化完整 schema；兼容旧分库的导入交由任务 2.6，不在读方法里偷偷迁移。
- [ ] GREEN 后提交 `补齐顺序稳定且查询只读的 DuckDB 状态存储`。

## 任务 2.6：历史迁入与无损回滚出口

**新增：** storage/migrate.py、`tests/integration/test_storage_state_migration.py`；修改 cli/storage.py。
**前置：** S3/S4 未确认只在临时库演练。

接口：`import_legacy_state(*, snapshot_root: Path, watchlist_root: Path, job_root: Path, target: Path) -> StateMigrationReport`；`export_state(*, database: Path, output_dir: Path) -> StateMigrationReport`。
StateMigrationReport 保存每类记录数、逐对象 canonical digest、冲突清单、源/目标路径、completed 布尔和阶段；只有事务提交并读回比对后 completed=True。
迁移器使用独立显式事务，不能简单循环调用各 store 的独立连接写入。快照 payload 用 SnapshotKind 对应现有模型校验；Watchlist 用 WatchlistEntry；Job 用 JobRun，保留 ordinal。

- [ ] RED：迁入全等、第二次幂等、目标异内容冲突全部回滚、损坏源全失败、Watchlist timeline 不丢、Job ordinal 不变、迁出后重新导入相等。
- [ ] `uv run pytest tests/integration/test_storage_state_migration.py -q`。
- [ ] 实现以下命令与事务步骤：

```text
astock storage import-state --snapshot-root PATH --watchlist-root PATH --job-root PATH --database PATH --output-dir REPORTS
astock storage export-state --database PATH --output-dir EMPTY_DIRECTORY
```

```text
先完整验证所有源文件及哈希，拒绝符号链接越出指定输入根
获取单写者锁，校验源文件未变化
BEGIN；初始化 schema；逐条比较已存在目标值；相同跳过、不同报冲突
写入所有缺项，读回比对 canonical digest
COMMIT；释放锁；输出交换报告
任何异常 ROLLBACK，源文件原封不动
```

- [ ] 导出只接受新建空目录，snapshot/watchlist/job 都输出原 JSON 协议，可用旧 store 读；写 staging 后原子发布。JSON 是回滚交换材料，不作为新的长期默认后端。
- [ ] 演练先导入，再新增一条 Watchlist 变更和 Job 重录，再导出并由 JSON Store 读回证明后续变更不丢；不能仅用切换前备份验证回滚。
- [ ] GREEN 后提交 `支持业务状态事务迁移与当前状态反向导出`。

## 任务 2.7：真实全量离线验证与隔离 daily 验收

**文件：** 只写 var/acceptance 及 docs/REVIEW_NOTES.md；必要的集成测试放 `tests/integration/test_storage_analysis_parity.py`。

- [ ] 重新核对第一阶段输入哈希，冻结 Raw；如已有新输入，另建基线，不混用旧结果。
- [ ] 先用 fixture 执行两路分析，按 `(symbol,factor)`、`(strategy_id,symbol)` 对比所有值、status、rank、reasons、eligibility、lineage 和 Universe 排除原因。因子是否包含池外记录按原命令语义分别比较，不要求 research 和 daily 的 factor 数量天然相同。
- [ ] 本地全量 materialize、verify 各运行一次；记录返回的 bundle_id，后续命令从实际 manifest 读取，禁止手写猜测 ID。

```bash
uv run astock storage materialize --as-of 2026-09-17 --output-root var/acceptance/storage-20260918/normalized --activate
uv run python scripts/capture_research_baseline.py --csv-root data/raw --as-of 2026-09-17 --config-root configs --industry-path data/raw/westock/industry/2026-09-17.csv --source parquet --normalized-root var/acceptance/storage-20260918/normalized --output-dir var/acceptance/storage-20260918/analysis
```

capture 的 `--industry-path` 在两路比较中是同一份显式外部证据；另做不传该选项、从 bundle 读取 canonical 行业的集成测试。真实 baseline 的行情行数不等于 Parquet accepted bars 行数：分别比较 Raw↔Raw inventory、CSV normalized↔Parquet normalized，不能把门禁正常拒绝当成迁移丢行。

- [ ] 执行新增 verify 命令，bundle-id 使用 materialize 的实际输出；四关均完成、无 P0 才继续。
- [ ] 导入历史状态到 `var/acceptance/storage-20260918/legacy.duckdb`，与原件逐条对照。禁止往该库写同日新的全池快照。
- [ ] 在另一份空数据库 `replay.duckdb` 运行 daily 验收，设置 `ASTOCK_DATABASE`、三个 backend=duckdb、`ASTOCK_NORMALIZED_ROOT`，使用 `--source parquet --allow-incomplete`。该日真实日期仍为 2026-09-17。校验 API 通过同一显式数据库读取新快照，而原历史库和 JSON 未改变。
- [ ] daily 的 Market/Signal/Candidate 仍应 BLOCKED；`--allow-incomplete` 只放宽命令退出，不生成占位结果。检查 UNIVERSE/FACTOR/STRATEGY 成功，不能用退出码 0 代替阶段检查。
- [ ] 记录 wall time、峰值内存、Parquet 大小；不设置未经批准的性能阈值。若仍整体构造大量 Python 对象，明确说明 Parquet 不保证自动解决内存占用。
- [ ] `uv run pytest -q` 及公共检查通过后记录结论；提交 `验证真实数据迁移一致性与隔离正式流水线`。

## 任务 2.8：生产切换、日常接线与回滚演练

**前置：** S1—S4 已有真实批准记录；2.7 全绿；已交付暂停写入时间窗与目标路径。目标库若存在且有未知业务内容，先盘点，不覆盖文件。
**修改：** settings/resolvers 默认值、cli 参数、README.md、docs/STORAGE.md、docs/ROADMAP.md、docs/DATA_MODEL.md、web/README.md（如有相关路径说明）、第一步 capture 默认参数。
**新增测试：** `tests/integration/test_storage_cutover.py`。

- [ ] RED：默认解析为 parquet+duckdb；显式 source=csv/backend=json 回放仍可用；无包不能退回 CSV；API 查询不依赖 Raw；共享 DB 不产生分散的 snapshots.duckdb/watchlist.duckdb。
- [ ] `uv run pytest tests/integration/test_storage_cutover.py tests/unit/test_api.py tests/integration/test_command_snapshot_ownership.py -q`。
- [ ] 切换前停所有写入者；通过现有进程/锁确认后，不强杀用户进程。确认源哈希未漂移；初始化/导入目标 DuckDB，发布正式 Parquet 批次，再改默认。单写者锁不允许两个进程并行更改业务状态。
- [ ] `doctor` 展示实际 database、三类 backend、normalized root、bundle_id、源数据是否晚于该批次，缺数据 extra 给安装命令而非自动降级。更新 daily 的前置流程为先 materialize，不能默认每次分析都重新归一化。
- [ ] 旧日期快照沿用迁入内容，标明只含五只的历史覆盖；历史全池重算继续留隔离库。新分析日期由 daily 写入新正式快照；若用户要替换旧日期正式记录，另立明确版本/替换决策，不能在迁移中解决。
- [ ] 回滚顺序必须完整：停止写入 → `export-state` 导出**当前**库到新目录 → JSON Store 验证 → 指向这套导出目录并设 backend=json/source=csv → 验证新增 Watchlist/Job 和快照仍在 → 保留 DuckDB 与 Parquet 供追查。不能直接指回过期 JSON。
- [ ] 发布前/后各做一次只读 doctor 和 API/CLI 冒烟；不因缺 Market/Signal 把迁移标失败，也不因它们 BLOCKED 声称完整系统成功。
- [ ] 全量测试及静态检查完成；更新旧计划顶部链接为“被本 v2 计划替代”仅在实施文件归属确认后进行，不擅自覆盖他人工作。提交 `将默认分析与业务状态切换到已验证的新存储`。

## 三、第二步最终验收

- [ ] Raw 与历史 JSON 哈希未改变；迁移只新增目标产物。
- [ ] Parquet 保留完整分析值和质量证据，两路数据/因子/策略/Universe 一致。
- [ ] 所有分析入口可仅凭既有 Parquet 包运行；默认查询不读取 Raw CSV。
- [ ] 只有显式物化命令建立新规范批次，读取展示所选批次，不冒充自动最新。
- [ ] 三种业务状态进同一 DuckDB；真正只读；同键冲突、损坏和锁占用有明确错误。
- [ ] 历史迁入和当前状态迁出逐条一致，后切换更新在回滚后仍保留。
- [ ] 正式历史快照未被全池重算覆盖；全池链路在隔离库验证。
- [ ] S1—S4 裁决、RED/GREEN、运行摘要、回滚命令与提交号齐备。

只有上述完成后进入第三步，重新建立估值修复前后的差异说明。
