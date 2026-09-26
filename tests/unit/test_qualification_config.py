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


# 每行五列：(label, name, text, expected, kwargs)。label 是失败原因；原用例 docstring
# 里的理由一并折进 label，逐字保留。text 是写盘 YAML，expected 是原 match 片段
# （None 表示原用例只断言异常类型、不校验错误信息文本），kwargs 是传给
# load_qualification_rule 的额外参数。行序与原文件函数顺序一一对应。
INVALID_RULE_CASES: tuple[tuple[str, str, str, str | None, dict[str, object]], ...] = (
    (
        "thresholds 为空",
        "value.yaml",
        "strategy_id: value\nversion: v1\nthresholds: {}\n",
        "thresholds",
        {},
    ),
    (
        "threshold 既无 min 也无 max",
        "value.yaml",
        "strategy_id: value\nversion: v1\nthresholds:\n  pe_ttm: {}\n",
        "min and/or max",
        {},
    ),
    (
        "min 大于 max",
        "value.yaml",
        (
            "strategy_id: value\n"
            "version: v1\n"
            "thresholds:\n"
            "  pe_ttm:\n"
            "    min: 5.0\n"
            "    max: 1.0\n"
        ),
        "min cannot exceed max",
        {},
    ),
    (
        "边界为 .nan 非有限值",
        "value.yaml",
        "strategy_id: value\nversion: v1\nthresholds:\n  pe_ttm:\n    min: .nan\n",
        "finite",
        {},
    ),
    (
        "threshold 条目不是映射",
        "value.yaml",
        "strategy_id: value\nversion: v1\nthresholds:\n  pe_ttm: 25.0\n",
        "pe_ttm",
        {},
    ),
    (
        "strategy_id 与期望身份不符",
        "growth.yaml",
        "strategy_id: growth\nversion: v1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
        "strategy_id mismatch",
        {"expected_strategy_id": "value"},
    ),
    (
        "因子名不在 known_factor_names 内",
        "value.yaml",
        "strategy_id: value\nversion: v1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
        "Unknown factor",
        {"known_factor_names": frozenset({"pb"})},
    ),
    (
        "version 为纯空白",
        "value.yaml",
        "strategy_id: value\nversion: '   '\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
        "version",
        {},
    ),
    (
        "version 为 YAML 空值 None（不得因 str(None)=='None' 而蒙混过关）",
        "value.yaml",
        "strategy_id: value\nversion:\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
        "version",
        {},
    ),
    (
        "strategy_id 为 YAML 空值",
        "value.yaml",
        "strategy_id:\nversion: v1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
        "strategy_id",
        {},
    ),
    (
        "version 为非字符串标量（version: 1 拒绝静默强转）",
        "value.yaml",
        "strategy_id: value\nversion: 1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
        "version",
        {},
    ),
    (
        "threshold 键名拼错 maximum（边界会被静默丢弃，属 fail-open）",
        "value.yaml",
        (
            "strategy_id: value\n"
            "version: v1\n"
            "thresholds:\n"
            "  pe_ttm:\n"
            "    min: 8.0\n"
            "    maximum: 1.0\n"
        ),
        "maximum",
        {},
    ),
    (
        "根级缺 strategy_id 键",
        "value.yaml",
        "version: v1\nthresholds:\n  pe_ttm:\n    max: 25.0\n",
        None,
        {},
    ),
    (
        "根级多余键 weight（配置会被静默忽略，属 fail-open）",
        "value.yaml",
        (
            "strategy_id: value\n"
            "version: v1\n"
            "weight: 0.5\n"
            "thresholds:\n"
            "  pe_ttm:\n"
            "    max: 25.0\n"
        ),
        "weight",
        {},
    ),
    (
        "根级键名拼错 descripton（应被根级未知键校验抓住）",
        "value.yaml",
        (
            "strategy_id: value\n"
            "version: v1\n"
            "descripton: 拼错了\n"
            "thresholds:\n"
            "  pe_ttm:\n"
            "    max: 25.0\n"
        ),
        "descripton",
        {},
    ),
)


def test_invalid_rules_are_refused(tmp_path: Path) -> None:
    """损坏的配置必须响亮失败：空阈值、缺边界、非有限值、未知键、身份不符一律拒绝。"""
    wrong = []
    for label, name, text, expected, kwargs in INVALID_RULE_CASES:
        try:
            load_qualification_rule(_write(tmp_path, text, name), **kwargs)
        except QualificationConfigInvalid as exc:
            if expected is not None and expected not in str(exc):
                wrong.append(f"{label}: 错误信息缺少 {expected!r}，实际 {exc}")
        else:
            wrong.append(f"{label}: 未拒绝非法配置")
    assert not wrong, "非法配置未被正确拒绝:\n" + "\n".join(wrong)


def test_missing_file_keeps_not_configured_semantics(tmp_path: Path) -> None:
    """文件缺失是"未配置"，不是"配置损坏"：抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        load_qualification_rule(tmp_path / "value.yaml")


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
