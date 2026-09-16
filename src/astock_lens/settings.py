"""Typed application configuration."""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


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


def load_app_config(path: Path | None = None) -> AppConfig:
    """Load application configuration from YAML."""
    config_path = path or Path(os.getenv("ASTOCK_CONFIG", "configs/app.yaml"))
    with config_path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004
            f"Configuration root must be a mapping: {config_path}"
        )
    return AppConfig.model_validate(payload)
