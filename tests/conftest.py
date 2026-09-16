"""Shared test fixtures."""

import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def local_tmp() -> Iterator[Path]:
    """A writable scratch directory inside the repository.

    `tmp_path` is unusable here: it lives under the system temp root, which
    this environment's sandbox denies. A repository-local scratch directory is
    removed after every test, so nothing leaks into `git status`.
    """
    root = Path(__file__).resolve().parent / ".tmp" / uuid4().hex
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
