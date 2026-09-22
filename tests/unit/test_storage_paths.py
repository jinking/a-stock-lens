"""统一存储路径解析（任务 2.1）。

规格：`docs/superpowers/plans/2026-09-18-storage-migration-v2-implementation-plan.md`
任务 2.1。要钉住的死规矩：

- env 覆盖配置；
- 配置文件缺失或非法必须报错，不许静默走默认；
- 相对路径仍相对命令工作目录（不做绝对化）；
- 两个 store resolver 的显式 `database` 参数优先，旧调用方式行为不变；
- 显式测试 root 不得触碰默认库。

本机 `tmp_path` 不可用（系统临时目录被沙箱拒绝），因此用仓库内的 `local_tmp`。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import astock_lens.api.app as api_module
import astock_lens.cli.app as cli_module
from astock_lens.data.snapshots.duckdb_store import DuckDBSnapshotStore
from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.data.storage.paths import StoragePaths, resolve_storage_paths
from astock_lens.domain.enums import SnapshotKind
from astock_lens.domain.models import SnapshotLineage
from astock_lens.universe.models import UniverseSnapshot
from astock_lens.watchlist.duckdb_store import DuckDBWatchlistStore
from astock_lens.watchlist.state_machine import open_entry
from astock_lens.watchlist.store import resolve_watchlist_store

AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
DAY = "2026-09-04"
LEGACY_SNAPSHOT_DATABASE = "snapshots.duckdb"
LEGACY_WATCHLIST_DATABASE = "watchlist.duckdb"

CONFIG = """\
app:
  name: test
storage:
  database: var/base.duckdb
  parquet_root: data
"""


def _config(root: Path) -> Path:
    """写一份最小但合法的配置，返回它的路径。"""
    path = root / "app.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def _universe() -> UniverseSnapshot:
    return UniverseSnapshot(
        as_of=AS_OF,
        snapshot_id="2026-09-04:abc123",
        config_digest="abc123",
        lineage=SnapshotLineage(universe_snapshot="2026-09-04:abc123"),
        included=("600000.SH",),
        exclusions=(),
        deferred_rules=(),
    )


# --- env 覆盖配置 -----------------------------------------------------------


def test_database_override(local_tmp: Path) -> None:
    """测试片段来自计划文档：env 优先于 config，并如实标注来源。"""
    config = _config(local_tmp)
    target = local_tmp / "isolated.duckdb"

    result = resolve_storage_paths(
        config_path=config, environ={"ASTOCK_DATABASE": str(target)}
    )

    assert isinstance(result, StoragePaths)
    assert result.database == target
    assert result.sources["database"] == "env"


def test_database_falls_back_to_config_and_keeps_it_relative(local_tmp: Path) -> None:
    """没有 env 时取配置值；相对路径保持相对，不偷偷绝对化。"""
    result = resolve_storage_paths(config_path=_config(local_tmp), environ={})

    assert result.database == Path("var/base.duckdb")
    assert result.sources["database"] == "config"
    assert not result.database.is_absolute()


def test_normalized_root_hangs_off_the_configured_parquet_root(
    local_tmp: Path,
) -> None:
    result = resolve_storage_paths(config_path=_config(local_tmp), environ={})

    assert result.normalized_root == Path("data/normalized")
    assert result.sources["normalized_root"] == "config"


def test_normalized_root_env_overrides_the_configured_parquet_root(
    local_tmp: Path,
) -> None:
    target = local_tmp / "normalized"

    result = resolve_storage_paths(
        config_path=_config(local_tmp),
        environ={"ASTOCK_NORMALIZED_ROOT": str(target)},
    )

    assert result.normalized_root == target
    assert result.sources["normalized_root"] == "env"


def test_json_roots_keep_their_existing_env_vars_and_defaults(
    local_tmp: Path,
) -> None:
    """三个 JSON root 不引入配置键：只有 env 和既有默认两条路。"""
    defaults = resolve_storage_paths(config_path=_config(local_tmp), environ={})

    assert defaults.snapshot_root == Path("data/snapshots")
    assert defaults.watchlist_root == Path("data/watchlist")
    assert defaults.job_root == Path("var/jobs")
    assert defaults.trade_root == Path("data/trades")
    assert [
        defaults.sources[key]
        for key in ("snapshot_root", "watchlist_root", "job_root", "trade_root")
    ] == [
        "default",
        "default",
        "default",
        "default",
    ]

    overridden = resolve_storage_paths(
        config_path=_config(local_tmp),
        environ={
            "ASTOCK_SNAPSHOT_ROOT": str(local_tmp / "snapshots"),
            "ASTOCK_WATCHLIST_ROOT": str(local_tmp / "watchlist"),
            "ASTOCK_JOB_ROOT": str(local_tmp / "jobs"),
            "ASTOCK_TRADE_ROOT": str(local_tmp / "trades"),
        },
    )

    assert overridden.snapshot_root == local_tmp / "snapshots"
    assert overridden.watchlist_root == local_tmp / "watchlist"
    assert overridden.job_root == local_tmp / "jobs"
    assert overridden.trade_root == local_tmp / "trades"
    assert [
        overridden.sources[key]
        for key in ("snapshot_root", "watchlist_root", "job_root", "trade_root")
    ] == [
        "env",
        "env",
        "env",
        "env",
    ]


# --- 配置缺失 / 非法必须报错 ------------------------------------------------


def test_missing_config_file_fails_loudly(local_tmp: Path) -> None:
    """配置文件不存在时不许"默认成功"。"""
    with pytest.raises(FileNotFoundError):
        resolve_storage_paths(config_path=local_tmp / "absent.yaml", environ={})


def test_invalid_yaml_fails_loudly(local_tmp: Path) -> None:
    config = local_tmp / "app.yaml"
    config.write_text("app: [unterminated\n", encoding="utf-8")

    with pytest.raises(ValueError, match="app.yaml"):
        resolve_storage_paths(config_path=config, environ={})


def test_config_without_a_storage_section_fails_loudly(local_tmp: Path) -> None:
    """`storage` 段是必填的，不引入静默默认配置。"""
    config = local_tmp / "app.yaml"
    config.write_text("app:\n  name: test\n", encoding="utf-8")

    with pytest.raises(ValueError):
        resolve_storage_paths(config_path=config, environ={})


def test_settings_still_report_the_yaml_error_as_a_value_error(
    local_tmp: Path,
) -> None:
    """`doctor` 只捕获 OSError/ValueError，所以非法 YAML 必须是 ValueError。"""
    from astock_lens.settings import load_app_config

    config = local_tmp / "app.yaml"
    config.write_text("app: [unterminated\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_app_config(config)


def test_yaml_error_is_still_a_yaml_error_for_callers_that_want_one(
    local_tmp: Path,
) -> None:
    """包装成 ValueError 的同时保留 YAML 的原始诊断，不吞掉细节。"""
    from astock_lens.settings import load_app_config

    config = local_tmp / "app.yaml"
    config.write_text("app: [unterminated\n", encoding="utf-8")

    with pytest.raises(ValueError) as raised:
        load_app_config(config)

    assert isinstance(raised.value.__cause__, yaml.YAMLError)


# --- 两个 resolver：显式 database 优先，旧调用方式不变 ----------------------


def test_snapshot_resolver_prefers_the_explicit_database(local_tmp: Path) -> None:
    pytest.importorskip("duckdb")
    legacy_root = local_tmp / "snapshots"
    database = local_tmp / "unified.duckdb"

    store = resolve_snapshot_store(legacy_root, backend="duckdb", database=database)
    store.write(SnapshotKind.UNIVERSE, AS_OF, [_universe()])

    assert database.is_file()
    assert not (legacy_root / LEGACY_SNAPSHOT_DATABASE).exists()


def test_snapshot_resolver_keeps_the_legacy_layout_without_a_database(
    local_tmp: Path,
) -> None:
    """旧调用方式 `resolve_snapshot_store(root)` 的行为一字不变。"""
    pytest.importorskip("duckdb")
    legacy_root = local_tmp / "snapshots"

    store = resolve_snapshot_store(legacy_root, backend="duckdb")
    store.write(SnapshotKind.UNIVERSE, AS_OF, [_universe()])

    assert (legacy_root / LEGACY_SNAPSHOT_DATABASE).is_file()


def test_watchlist_resolver_prefers_the_explicit_database(local_tmp: Path) -> None:
    pytest.importorskip("duckdb")
    legacy_root = local_tmp / "watchlist"
    database = local_tmp / "unified.duckdb"

    store = resolve_watchlist_store(legacy_root, backend="duckdb", database=database)
    store.write(open_entry("600519.SH", at=AS_OF, thesis="brand moat"))

    assert database.is_file()
    assert not (legacy_root / LEGACY_WATCHLIST_DATABASE).exists()


def test_watchlist_resolver_keeps_the_legacy_layout_without_a_database(
    local_tmp: Path,
) -> None:
    pytest.importorskip("duckdb")
    legacy_root = local_tmp / "watchlist"

    store = resolve_watchlist_store(legacy_root, backend="duckdb")
    store.write(open_entry("600519.SH", at=AS_OF, thesis="brand moat"))

    assert (legacy_root / LEGACY_WATCHLIST_DATABASE).is_file()


# --- CLI 与 API 指同一个库 --------------------------------------------------


def test_cli_and_api_point_at_the_same_database(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI 写进去的正式快照，API 必须能从同一个库里读到。"""
    pytest.importorskip("duckdb")
    database = local_tmp / "unified.duckdb"
    monkeypatch.setenv("ASTOCK_CONFIG", str(_config(local_tmp)))
    monkeypatch.setenv("ASTOCK_DATABASE", str(database))
    monkeypatch.setenv("ASTOCK_SNAPSHOT_BACKEND", "duckdb")
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(local_tmp / "snapshots"))

    cli_module._store().write(SnapshotKind.UNIVERSE, AS_OF, [_universe()])
    assert database.is_file()
    assert not (local_tmp / "snapshots" / LEGACY_SNAPSHOT_DATABASE).exists()

    response = TestClient(api_module.create_app()).get(
        "/universe", params={"as_of": DAY}
    )

    assert response.status_code == 200
    assert response.json()["snapshot"]["included"] == ["600000.SH"]


def test_explicit_api_roots_never_touch_the_default_database(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式传 root 的测试必须留在自己的目录里，不碰 `ASTOCK_DATABASE`。"""
    pytest.importorskip("duckdb")
    default_database = local_tmp / "prod.duckdb"
    snapshot_root = local_tmp / "isolated" / "snapshots"
    watchlist_root = local_tmp / "isolated" / "watchlist"
    monkeypatch.setenv("ASTOCK_CONFIG", str(_config(local_tmp)))
    monkeypatch.setenv("ASTOCK_DATABASE", str(default_database))
    monkeypatch.setenv("ASTOCK_SNAPSHOT_BACKEND", "duckdb")
    monkeypatch.setenv("ASTOCK_WATCHLIST_BACKEND", "duckdb")

    DuckDBSnapshotStore(snapshot_root / LEGACY_SNAPSHOT_DATABASE).write(
        SnapshotKind.UNIVERSE, AS_OF, [_universe()]
    )
    DuckDBWatchlistStore(watchlist_root / LEGACY_WATCHLIST_DATABASE).write(
        open_entry("600519.SH", at=AS_OF, thesis="brand moat")
    )
    client = TestClient(
        api_module.create_app(
            snapshot_root=snapshot_root, watchlist_root=watchlist_root
        )
    )

    response = client.get("/universe", params={"as_of": DAY})
    watchlist_response = client.get("/watchlist")

    assert response.status_code == 200
    assert response.json()["snapshot"]["included"] == ["600000.SH"]
    assert watchlist_response.json()["symbols"] == ["600519.SH"]
    assert not default_database.exists()
