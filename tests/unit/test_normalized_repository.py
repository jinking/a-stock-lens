"""归一化数据读取边界（任务 2.2）。

规格：`docs/superpowers/plans/2026-09-18-storage-migration-v2-implementation-plan.md`
任务 2.2。要钉住的死规矩：

- 一次 research 分析**只读一次**归一化输入（用计数 fake 证明）；
- fake 抛异常时**失败**，不回退 CSV；
- `data/` 层不得 import `pipelines/`；
- 不重写因子／Universe／策略算法（注入 CSV 仓库必须复现默认运行）；
- `normalize_stage`、四个分析入口与 `run_daily` 都能注入，旧调用行为不变。

本机 `tmp_path` 不可用，因此用仓库内的 `local_tmp`；CSV 夹具用仓库自带、
只读的 `tests/fixtures/csv`。

本文件的 fake 全部**自带**，不引用别的测试文件的私有夹具。
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from astock_lens.data.repository.contracts import NormalizedRepository
from astock_lens.data.repository.csv import CsvNormalizedRepository
from astock_lens.data.repository.models import (
    FinancialInputs,
    NormalizeOutcome,
    ValuationInputs,
)
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import JobStage
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.jobs.store import JsonJobStore
from astock_lens.pipelines import stages
from astock_lens.pipelines.analysis import (
    compute_factor_state,
    compute_research_universe,
    run_analysis,
    run_research_analysis,
)
from astock_lens.pipelines.daily import run_daily
from astock_lens.strategies.registry import RegisteredStrategy, load_scanners
from astock_lens.universe.config import UniverseConfig, load_universe_config

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
LONG_DATASET = "daily_bars_long"

# 一个肯定不存在的 CSV 根：注入生效时它不该被碰，注入失效时它会立刻报错。
MISSING_ROOT = ROOT / "tests" / ".tmp" / "no-such-csv-root"


class RepositoryUnavailable(RuntimeError):
    """读不到的归一化输入。"""


class CountingRepository:
    """把每一次 read 记下来，并原样转发给真正的 CSV 实现。"""

    def __init__(self, inner: NormalizedRepository) -> None:
        self._inner = inner
        self.reads: list[tuple[str, str]] = []

    def read(
        self, *, as_of: datetime, dataset: str, securities_dataset: str
    ) -> NormalizeOutcome:
        self.reads.append((dataset, securities_dataset))
        return self._inner.read(
            as_of=as_of, dataset=dataset, securities_dataset=securities_dataset
        )


class UnavailableRepository:
    """读不到的仓库：它必须让分析**失败**，而不是让调用方悄悄回到 CSV。"""

    def __init__(self) -> None:
        self.reads = 0

    def read(
        self, *, as_of: datetime, dataset: str, securities_dataset: str
    ) -> NormalizeOutcome:
        del as_of, dataset, securities_dataset
        self.reads += 1
        raise RepositoryUnavailable("normalized input is not available")


def _factor_configs() -> tuple[FactorConfig, ...]:
    return tuple(
        load_factor_config(path)
        for path in sorted((CONFIGS / "factors").glob("*.yaml"))
    )


def _universe_config() -> UniverseConfig:
    return load_universe_config(CONFIGS / "universe.yaml")


def _scanners() -> Sequence[RegisteredStrategy]:
    return load_scanners(CONFIGS / "strategies")


def _drop_fetch_clock(value: object) -> object:
    """递归摘掉 `fetched_at`。

    `RawDataset.fetched_at` 是"这次取数发生在哪一刻"的墙钟（provider 用
    `datetime.now(UTC)` 打的），所以同一份数据读两次必然不同。它是审计线索，
    不是数据本身；把它留着就等于断言两次调用发生在同一微秒。

    只摘这一个字段：其余每一个字段仍然逐项比对，比较强度没有被放宽。
    """
    if isinstance(value, dict):
        return {
            key: _drop_fetch_clock(item)
            for key, item in value.items()
            if key != "fetched_at"
        }
    if isinstance(value, list):
        return [_drop_fetch_clock(item) for item in value]
    return value


def _comparable(model: BaseModel) -> object:
    """把模型摊成可比的字典，并摘掉墙钟。"""
    return _drop_fetch_clock(model.model_dump())


# --- 模型搬家，老 import 不许断 ---------------------------------------------


def test_the_stage_import_path_still_resolves_the_moved_models() -> None:
    """三个模型只是换了个家：`pipelines.stages` 上的老路径必须还在。"""
    assert stages.NormalizeOutcome is NormalizeOutcome
    assert stages.FinancialInputs is FinancialInputs
    assert stages.ValuationInputs is ValuationInputs


def test_csv_repository_satisfies_the_protocol() -> None:
    assert isinstance(CsvNormalizedRepository(CSV_ROOT), NormalizedRepository)


# --- CSV 回放实现必须与搬走前的 stage 逐字段一致 ----------------------------


def test_csv_repository_matches_stage() -> None:
    """计划文档给的对照：同一份夹具，仓库读取与 stage 调用必须相等。

    唯一的例外是 `RawDataset.fetched_at`——它是取数那一刻的墙钟，两次调用必然
    不同（计划片段没写这一点，实测才发现）。摘掉它之后逐字段比对。
    """
    root = Path("tests/fixtures/csv")
    day = datetime(2026, 9, 17, 15, tzinfo=UTC)
    repo = CsvNormalizedRepository(root)

    actual = repo.read(as_of=day, dataset="daily_bars", securities_dataset="securities")
    expected = stages.normalize_stage(csv_root=root, as_of=day)

    assert _comparable(actual) == _comparable(expected)


def test_repository_helper_entry_points_match_the_stage_helpers() -> None:
    """`financial_inputs` / `valuation_inputs` 的兼容转发不许改结果。"""
    repo = CsvNormalizedRepository(CSV_ROOT)

    assert _comparable(repo.financial_inputs(as_of=AS_OF)) == _comparable(
        stages.financial_inputs(CSV_ROOT, as_of=AS_OF)
    )
    assert _comparable(repo.valuation_inputs(as_of=AS_OF)) == _comparable(
        stages.valuation_inputs(CSV_ROOT, as_of=AS_OF)
    )


# --- 一次分析只读一次 -------------------------------------------------------


def test_a_research_analysis_reads_the_normalized_input_once() -> None:
    """研究分析要跨阶段复用同一份输入，不是每个阶段重新解析一遍。"""
    counting = CountingRepository(CsvNormalizedRepository(CSV_ROOT))

    population, state = run_research_analysis(
        # 故意给一个不存在的 CSV 根：读取只许走注入的仓库。
        csv_root=MISSING_ROOT,
        as_of=AS_OF,
        universe_config=_universe_config(),
        factor_configs=_factor_configs(),
        scanners=_scanners(),
        dataset=LONG_DATASET,
        repository=counting,
    )

    assert counting.reads == [(LONG_DATASET, "securities")], (
        "one research analysis must read the normalized input exactly once; "
        f"saw {counting.reads}"
    )
    assert population.research_symbols
    assert state.factor_results


# --- 读不到就失败，不许静默回退 CSV ----------------------------------------


def test_unavailable_repository_fails_instead_of_falling_back() -> None:
    exploding = UnavailableRepository()

    with pytest.raises(RepositoryUnavailable, match="not available"):
        run_research_analysis(
            # 注意：这里给的是**真实可用**的 CSV 根。回退在技术上完全做得到，
            # 正因如此它必须是错的——一个读不到的仓库不许被 CSV 掩盖。
            csv_root=CSV_ROOT,
            as_of=AS_OF,
            universe_config=_universe_config(),
            factor_configs=_factor_configs(),
            scanners=_scanners(),
            dataset=LONG_DATASET,
            repository=exploding,
        )

    assert exploding.reads == 1


def test_every_entry_point_forwards_the_repository() -> None:
    """`normalize_stage` 与四个分析入口认同一个注入点，且都不回退。"""
    calls: tuple[tuple[str, Callable[[NormalizedRepository], object]], ...] = (
        (
            "normalize_stage",
            lambda repo: stages.normalize_stage(
                csv_root=CSV_ROOT,
                as_of=AS_OF,
                dataset=LONG_DATASET,
                repository=repo,
            ),
        ),
        (
            "compute_research_universe",
            lambda repo: compute_research_universe(
                csv_root=CSV_ROOT,
                as_of=AS_OF,
                universe_config=_universe_config(),
                factor_configs=_factor_configs(),
                dataset=LONG_DATASET,
                repository=repo,
            ),
        ),
        (
            "compute_factor_state",
            lambda repo: compute_factor_state(
                csv_root=CSV_ROOT,
                as_of=AS_OF,
                factor_configs=_factor_configs(),
                dataset=LONG_DATASET,
                repository=repo,
            ),
        ),
        (
            "run_analysis",
            lambda repo: run_analysis(
                csv_root=CSV_ROOT,
                as_of=AS_OF,
                universe_config=_universe_config(),
                factor_configs=_factor_configs(),
                scanners=_scanners(),
                dataset=LONG_DATASET,
                repository=repo,
            ),
        ),
        (
            "run_research_analysis",
            lambda repo: run_research_analysis(
                csv_root=CSV_ROOT,
                as_of=AS_OF,
                universe_config=_universe_config(),
                factor_configs=_factor_configs(),
                scanners=_scanners(),
                dataset=LONG_DATASET,
                repository=repo,
            ),
        ),
    )

    for name, invoke in calls:
        exploding = UnavailableRepository()
        with pytest.raises(RepositoryUnavailable):
            invoke(exploding)
        assert exploding.reads == 1, name


def test_run_daily_uses_the_injected_repository(local_tmp: Path) -> None:
    """`run_daily` 的 NORMALIZE 阶段走注入点；失败就是失败，不落任何快照。"""
    exploding = UnavailableRepository()

    result = run_daily(
        csv_root=CSV_ROOT,
        as_of=AS_OF,
        universe_config=_universe_config(),
        factor_configs=_factor_configs(),
        scanners=_scanners(),
        strategy_directory=CONFIGS / "strategies",
        store=JsonSnapshotStore(local_tmp / "snapshots"),
        job_store=JsonJobStore(local_tmp / "jobs"),
        dataset=LONG_DATASET,
        repository=exploding,
    )

    assert result.failed_stages == (JobStage.NORMALIZE,)
    assert result.snapshot_paths == ()
    assert exploding.reads == 1


# --- 旧调用行为不变 ---------------------------------------------------------


def test_an_injected_csv_repository_reproduces_the_default_run() -> None:
    """不注入时走 CSV；注入 CSV 仓库时结果必须逐字段一致（墙钟除外）。"""
    kwargs = {
        "as_of": AS_OF,
        "universe_config": _universe_config(),
        "factor_configs": _factor_configs(),
        "scanners": _scanners(),
        "dataset": LONG_DATASET,
    }

    default = run_analysis(csv_root=CSV_ROOT, **kwargs)
    injected = run_analysis(
        csv_root=MISSING_ROOT,
        repository=CsvNormalizedRepository(CSV_ROOT),
        **kwargs,
    )

    assert _comparable(injected) == _comparable(default)


def test_the_research_population_is_unchanged_by_where_the_input_came_from() -> None:
    """同一份输入，从 CSV 读还是从注入点读，研究池必须一模一样。"""
    kwargs = {
        "as_of": AS_OF,
        "universe_config": _universe_config(),
        "factor_configs": _factor_configs(),
        "scanners": _scanners(),
        "dataset": LONG_DATASET,
    }

    default_population, default_state = run_research_analysis(
        csv_root=CSV_ROOT, **kwargs
    )
    injected_population, injected_state = run_research_analysis(
        csv_root=MISSING_ROOT,
        repository=CsvNormalizedRepository(CSV_ROOT),
        **kwargs,
    )

    assert injected_population == default_population
    assert _comparable(injected_state) == _comparable(default_state)


# --- 依赖方向 ---------------------------------------------------------------


def test_the_data_layer_never_imports_the_pipeline_layer() -> None:
    """`data/` 是分析层的下游而不是上游：它不认识 pipelines。"""
    data_root = ROOT / "src" / "astock_lens" / "data"

    offenders = [
        f"{path.relative_to(ROOT)}: {line.strip()}"
        for path in sorted(data_root.rglob("*.py"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if "astock_lens.pipelines" in line
        or "from astock_lens import pipelines" in line
    ]

    assert offenders == []


def test_valuation_inputs_point_in_time_isolation(local_tmp: Path) -> None:
    """证明时点早的 as_of 绝不泄漏使用晚于该时点的估值文件，且同一指标在两日取值各异。"""
    raw_root = local_tmp / "raw"
    val_dir = raw_root / "neodata" / "valuation"
    val_dir.mkdir(parents=True, exist_ok=True)

    def _make_csv(pe_value: float) -> str:
        block = (
            "**标的代码（统一输出字段名）**: 000001.SZ\n\n"
            "  **标的名称**: 平安银行\n\n"
            f"  **滚动市盈率（倍）**: {pe_value}\n\n"
            "  **市盈率历史分位数（%）**: 50.0\n\n"
            "  **市净率（倍）**: 0.5\n"
        )
        escaped = block.replace('"', '""')
        return f'type,desc,content\n统一估值查询,统一估值查询,"{escaped}"\n'

    (val_dir / "2026-09-17.csv").write_text(_make_csv(5.18), encoding="utf-8")
    (val_dir / "2026-09-19.csv").write_text(_make_csv(6.25), encoding="utf-8")

    repo = CsvNormalizedRepository(raw_root)
    older = repo.valuation_inputs(as_of=datetime(2026, 9, 17, 15, 0, tzinfo=UTC))
    newer = repo.valuation_inputs(as_of=datetime(2026, 9, 19, 15, 0, tzinfo=UTC))

    assert older.source_file is not None
    assert newer.source_file is not None
    assert older.source_file.name == "2026-09-17.csv"
    assert newer.source_file.name == "2026-09-19.csv"

    older_obs = {(item.symbol, item.metric): item.value for item in older.observations}
    newer_obs = {(item.symbol, item.metric): item.value for item in newer.observations}

    assert older_obs[("000001.SZ", "pe_ttm")] == 5.18
    assert newer_obs[("000001.SZ", "pe_ttm")] == 6.25
    assert older_obs[("000001.SZ", "pe_ttm")] != newer_obs[("000001.SZ", "pe_ttm")]
