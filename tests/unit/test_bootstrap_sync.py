"""Liquidity-bootstrap requirement.

Cold start has to fetch some price history before it can know which symbols are
liquid enough to research — `avg_amount_20d` is measured, not assumed. How much
history is "enough" is not a number this code may choose: it is whatever the
configured liquidity factor's window says. These tests pin that the number is
derived from configuration, that a missing or unreviewed configuration fails
loudly instead of falling back, and that the read-only CLI reports it without
touching any state.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astock_lens.cli.app import app
from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    BootstrapRequirementNotConfigured,
    liquidity_bootstrap_requirement,
)
from astock_lens.factors.config import FactorConfig, load_factor_config

ROOT = Path(__file__).resolve().parents[2]
FACTOR_DIR = ROOT / "configs" / "factors"
LIQUIDITY_FACTOR = "avg_amount_20d"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


def _configs() -> tuple[FactorConfig, ...]:
    return tuple(load_factor_config(path) for path in sorted(FACTOR_DIR.glob("*.yaml")))


def _liquidity_config(**params: int | None) -> FactorConfig:
    """A liquidity factor config built from the real one, with a new window."""
    real = next(item for item in _configs() if item.name == LIQUIDITY_FACTOR)
    return real.model_copy(update={"params": {**real.params, **params}})


def test_the_requirement_comes_from_the_configured_window() -> None:
    configured = next(item for item in _configs() if item.name == LIQUIDITY_FACTOR)

    requirement = liquidity_bootstrap_requirement(_configs())

    assert isinstance(requirement, BootstrapRequirement)
    assert requirement.factor_name == LIQUIDITY_FACTOR
    assert requirement.required_valid_bars == configured.params["window"]


def test_removing_the_liquidity_factor_fails_loudly() -> None:
    without_it = tuple(item for item in _configs() if item.name != LIQUIDITY_FACTOR)

    with pytest.raises(BootstrapRequirementNotConfigured, match=LIQUIDITY_FACTOR):
        liquidity_bootstrap_requirement(without_it)


def test_an_unreviewed_window_fails_loudly_instead_of_defaulting() -> None:
    """`window: null` is how the config records "not reviewed yet"."""
    broken = (_liquidity_config(window=None),)

    with pytest.raises(BootstrapRequirementNotConfigured, match="window"):
        liquidity_bootstrap_requirement(broken)


def test_a_different_window_changes_the_requirement() -> None:
    """Proof the number is read, not hard-coded: another window moves it."""
    requirement = liquidity_bootstrap_requirement((_liquidity_config(window=61),))

    assert requirement.required_valid_bars == 61


def test_the_cli_reports_the_derived_requirement_and_writes_nothing(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_root = local_tmp / "snapshots"
    watchlist_root = local_tmp / "watchlist"
    job_root = local_tmp / "jobs"
    for root in (snapshot_root, watchlist_root, job_root):
        root.mkdir()
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snapshot_root))
    monkeypatch.setenv("ASTOCK_WATCHLIST_ROOT", str(watchlist_root))
    monkeypatch.setenv("ASTOCK_JOB_ROOT", str(job_root))

    result = CliRunner().invoke(app, ["universe", "bootstrap-requirement"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["factor_name"] == LIQUIDITY_FACTOR
    assert payload["required_valid_bars"] == 20
    assert payload["min_average_turnover_20d"] == 20_000_000
    assert payload["min_listing_days"] == 120
    assert list(snapshot_root.iterdir()) == []
    assert list(watchlist_root.iterdir()) == []
    assert list(job_root.iterdir()) == []
