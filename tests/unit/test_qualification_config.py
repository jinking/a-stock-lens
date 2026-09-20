"""生产资格规则严格配置加载单元测试（fail-closed）。

覆盖规格 §5 要求拒绝的每一种畸形配置。设计原则：配置损坏必须响亮失败，
绝不允许"空阈值自动通过""畸形条目静默跳过""缺键静默兜底"。
"""

from pathlib import Path

import pytest

from astock_lens.qualifications.config import QualificationConfigInvalid
from astock_lens.qualifications.rules import (
    FactorThresholdRule,
    load_qualification_rule,
)


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


def test_null_version_is_invalid(tmp_path: Path) -> None:
    """YAML 空值 ``version:`` 解析为 None，绝不能因 str(None)=='None' 而蒙混过关。"""
    path = _write(
        tmp_path,
        "strategy_id: value\nversion:\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="version"):
        load_qualification_rule(path)


def test_null_strategy_id_is_invalid(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strategy_id:\nversion: v1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="strategy_id"):
        load_qualification_rule(path)


def test_non_string_version_is_invalid(tmp_path: Path) -> None:
    """非字符串标量（如 version: 1）拒绝静默强转。"""
    path = _write(
        tmp_path,
        "strategy_id: value\nversion: 1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="version"):
        load_qualification_rule(path)


def test_unknown_threshold_key_is_invalid(tmp_path: Path) -> None:
    """键名拼错（maximum）会让边界被静默丢弃，属 fail-open，必须拒绝。"""
    path = _write(
        tmp_path,
        "strategy_id: value\n"
        "version: v1\n"
        "thresholds:\n"
        "  pe_ttm:\n"
        "    min: 8.0\n"
        "    maximum: 1.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="maximum"):
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


def test_unknown_root_key_is_invalid(tmp_path: Path) -> None:
    """根级多余键（如 weight）会让配置被静默忽略，属 fail-open，必须拒绝。"""
    path = _write(
        tmp_path,
        "strategy_id: value\n"
        "version: v1\n"
        "weight: 0.5\n"
        "thresholds:\n"
        "  pe_ttm:\n"
        "    max: 25.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="weight"):
        load_qualification_rule(path)


def test_misspelled_root_key_is_invalid(tmp_path: Path) -> None:
    """根级键名拼错（descripton）应被根级未知键校验抓住。"""
    path = _write(
        tmp_path,
        "strategy_id: value\n"
        "version: v1\n"
        "descripton: 拼错了\n"
        "thresholds:\n"
        "  pe_ttm:\n"
        "    max: 25.0\n",
    )
    with pytest.raises(QualificationConfigInvalid, match="descripton"):
        load_qualification_rule(path)


def test_allowed_root_keys_still_load(tmp_path: Path) -> None:
    """四个允许的根级键必须继续通过（生产 YAML 只有这四键）。"""
    path = _write(
        tmp_path,
        "strategy_id: value\n"
        "version: v1\n"
        "description: 允许的说明\n"
        "thresholds:\n"
        "  pe_ttm:\n"
        "    max: 25.0\n",
    )
    rule = load_qualification_rule(path)
    assert rule.strategy_id == "value"
