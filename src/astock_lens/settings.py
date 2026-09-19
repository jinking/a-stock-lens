"""Typed application configuration."""

import os
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

CONFIG_PATH_ENV = "ASTOCK_CONFIG"
DEFAULT_CONFIG_PATH = Path("configs/app.yaml")


class AppMetadata(BaseModel):
    """Static application metadata."""

    model_config = ConfigDict(frozen=True)

    name: str


class StorageSettings(BaseModel):
    """Paths used by local storage adapters."""

    model_config = ConfigDict(frozen=True)

    database: Path
    parquet_root: Path


class AppConfig(BaseModel):
    """Root application configuration."""

    model_config = ConfigDict(frozen=True)

    app: AppMetadata
    storage: StorageSettings


def resolve_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """配置文件路径的唯一解析点。

    环境变量是唯一的覆盖来源，没有它就走仓库里的既有默认。相对路径保持相对：
    命令的工作目录决定它落在哪，和其余存储路径的语义一致。
    """
    source = os.environ if environ is None else environ
    return Path(source.get(CONFIG_PATH_ENV, str(DEFAULT_CONFIG_PATH)))


def load_app_config(path: Path | None = None) -> AppConfig:
    """Load application configuration from YAML.

    非法 YAML 统一报成 `ValueError` 并保留原始诊断：调用方（`astock doctor`）
    只捕获 `OSError` / `ValueError` / `ValidationError`，不让配置问题以一条
    没头没尾的回溯结束。
    """
    config_path = path or resolve_config_path()
    with config_path.open(encoding="utf-8") as stream:
        try:
            payload = yaml.safe_load(stream)
        except yaml.YAMLError as error:
            raise ValueError(
                f"Configuration file is not valid YAML: {config_path}"
            ) from error
    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004
            f"Configuration root must be a mapping: {config_path}"
        )
    return AppConfig.model_validate(payload)
