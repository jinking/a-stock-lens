"""生产资格规则严格配置加载单元测试（fail-closed）。

覆盖规格 §5 要求拒绝的每一种畸形配置。设计原则：配置损坏必须响亮失败，
绝不允许"空阈值自动通过""畸形条目静默跳过""缺键静默兜底"。
"""

from pathlib import Path

import pytest

from astock_lens.qualifications.config import (
    QualificationConfigInvalid,
    load_qualification_rule,
)
from astock_lens.qualifications.rules import FactorThresholdRule


def _write(tmp_path: Path, text: str, name: str = "value.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_empty_thresholds_are_invalid(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id: value\nversion: v1\nthresholds: {}\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="thresholds"):
        load_qualification_rule(path)


def test_threshold_without_min_or_max_is_invalid(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id: value\nversion: v1\nthresholds:\n  pe_ttm: {}\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="min and/or max"):
        load_qualification_rule(path)


def test_min_greater_than_max_is_invalid(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id: value\nversion: v1\nthresholds:\n  pe_ttm:\n    min: 5.0\n    max: 1.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="min cannot exceed max"):
        load_qualification_rule(path)


def test_nan_or_inf_is_invalid(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id: value\nversion: v1\nthresholds:\n  pe_ttm:\n    min: .nan\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="finite"):
        load_qualification_rule(path)


def test_non_mapping_threshold_is_invalid(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id: value\nversion: v1\nthresholds:\n  pe_ttm: 25.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="pe_ttm"):
        load_qualification_rule(path)


def test_strategy_id_must_match_expected_strategy(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id: growth\nversion: v1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
        name="growth.yaml",
    )
    with pytest.raises(QualificationConfigInvalid, match="strategy_id mismatch"):
        load_qualification_rule(path, expected_strategy_id="value")


def test_unknown_factor_is_invalid(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id: value\nversion: v1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="Unknown factor"):
        load_qualification_rule(
            path,
            known_factor_names=frozenset({"pb"}),
        )


def test_blank_version_is_invalid(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id: value\nversion: '   '\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="version"):
        load_qualification_rule(path)


def test_missing_file_keeps_not_configured_semantics(tmp_path: Path) -> None:
    """文件缺失是"未配置"，不是"配置损坏"：抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        load_qualification_rule(tmp_path / "value.yaml")


def test_missing_strategy_id_key_is_invalid(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: v1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
    )
    with pytest.raises(QualificationConfigInvalid):
        load_qualification_rule(path)


def test_valid_rule_loads_with_expected_fields(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id: value\n"
        "version: v1\n"
        "description: 示例\n"
        "thresholds:\n"
        "  pe_ttm:\n"
        "    max: 25.0\n",
    )
    rule = load_qualification_rule(
        path,
        expected_strategy_id="value",
        known_factor_names=frozenset({"pe_ttm"}),
    )
    assert isinstance(rule, FactorThresholdRule)
    assert rule.strategy_id == "value"
    assert rule.version == "v1"
    assert rule.thresholds["pe_ttm"].max == 25.0
    assert rule.thresholds["pe_ttm"].min is None
