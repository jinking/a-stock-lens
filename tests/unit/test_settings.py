from pathlib import Path

from astock_lens.settings import load_app_config


def test_load_app_config_reads_local_storage_paths() -> None:
    config = load_app_config(Path("configs/app.yaml"))

    assert config.app.name == "A-Stock Lens"
    assert config.storage.database == Path("var/astock.duckdb")
    assert config.storage.parquet_root == Path("data")
