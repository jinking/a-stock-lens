"""存储路径的唯一解析点（任务 2.1）。

在这之前，"数据库放哪、归一化产物放哪、快照/自选/任务状态放哪"由每个入口各自
`os.getenv(...)` 拼一遍，默认值散落在 CLI 与 API 里；同一个进程里两个入口完全
可以指到不同的库而无人发现。本模块把那件事收敛成一处：只有这里读 env、只有这里
读配置文件，`astock doctor` 直接打印它算出来的生效路径与来源。

规则（计划任务 2.1）：

- env 优先于配置文件；
- 配置文件缺失或非法必须报错，不许静默走默认；
- 相对路径保持相对，命令的工作目录决定它落在哪；
- 三个 JSON root 沿用既有环境变量与既有默认，不引入新的配置键。

本模块**只解析路径**：不建目录、不建数据库、不写任何文件。
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from astock_lens.settings import load_app_config, resolve_config_path

DATABASE_ENV = "ASTOCK_DATABASE"
NORMALIZED_ROOT_ENV = "ASTOCK_NORMALIZED_ROOT"
SNAPSHOT_ROOT_ENV = "ASTOCK_SNAPSHOT_ROOT"
WATCHLIST_ROOT_ENV = "ASTOCK_WATCHLIST_ROOT"
JOB_ROOT_ENV = "ASTOCK_JOB_ROOT"
TRADE_ROOT_ENV = "ASTOCK_TRADE_ROOT"

DEFAULT_SNAPSHOT_ROOT = Path("data/snapshots")
DEFAULT_WATCHLIST_ROOT = Path("data/watchlist")
DEFAULT_JOB_ROOT = Path("var/jobs")
DEFAULT_TRADE_ROOT = Path("data/trades")

ENV = "env"
CONFIG = "config"
DEFAULT = "default"


@dataclass(frozen=True)
class StoragePaths:
    """本次运行真正生效的路径，以及每条路径的来源。

    `sources` 的键与上面的字段同名，值是 `env` / `config` / `default` 之一：
    一个路径是"配置里写的"还是"没人配置所以用默认"，是两件不同的事。
    """

    database: Path
    normalized_root: Path
    snapshot_root: Path
    watchlist_root: Path
    job_root: Path
    trade_root: Path
    sources: Mapping[str, str]


def resolve_storage_paths(
    *, config_path: Path | None = None, environ: Mapping[str, str] | None = None
) -> StoragePaths:
    """解析本次运行生效的全部存储路径。

    `environ` 为 `None` 时读进程环境；显式传入时只认传进来的那一份，让测试与
    调用方把"环境"当成参数而不是全局状态。

    配置文件缺失或非法一律向上抛（`FileNotFoundError` / `ValueError`）：一个
    不知道自己的库在哪的运行不应该假装自己知道。
    """
    source = os.environ if environ is None else environ
    config = load_app_config(config_path or resolve_config_path(source))

    database, database_source = _from_env_or(
        source, DATABASE_ENV, config.storage.database, CONFIG
    )
    normalized_root, normalized_source = _from_env_or(
        source,
        NORMALIZED_ROOT_ENV,
        config.storage.parquet_root / "normalized",
        CONFIG,
    )
    snapshot_root, snapshot_source = _from_env_or(
        source, SNAPSHOT_ROOT_ENV, DEFAULT_SNAPSHOT_ROOT, DEFAULT
    )
    watchlist_root, watchlist_source = _from_env_or(
        source, WATCHLIST_ROOT_ENV, DEFAULT_WATCHLIST_ROOT, DEFAULT
    )
    job_root, job_source = _from_env_or(source, JOB_ROOT_ENV, DEFAULT_JOB_ROOT, DEFAULT)
    trade_root, trade_source = _from_env_or(
        source, TRADE_ROOT_ENV, DEFAULT_TRADE_ROOT, DEFAULT
    )

    return StoragePaths(
        database=database,
        normalized_root=normalized_root,
        snapshot_root=snapshot_root,
        watchlist_root=watchlist_root,
        job_root=job_root,
        trade_root=trade_root,
        sources={
            "database": database_source,
            "normalized_root": normalized_source,
            "snapshot_root": snapshot_source,
            "watchlist_root": watchlist_source,
            "job_root": job_source,
            "trade_root": trade_source,
        },
    )


def _from_env_or(
    environ: Mapping[str, str], name: str, configured: Path, fallback: str
) -> tuple[Path, str]:
    """环境变量优先；没有就返回配置值（或既有默认）并标注它来自哪里。"""
    override = environ.get(name)
    if override:
        return Path(override), ENV
    return configured, fallback
