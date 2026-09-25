"""资格长尾（严格配置、上下文证据、资格扫描器）。

本文件由 Task 12「文件合并」把以下 3 个同域小文件整体搬入：
    - tests/unit/test_qualification_config.py（4 例）
    - tests/unit/test_qualification_context.py（3 例）
    - tests/unit/test_eligibility_scanner.py（9 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.qualifications.config import QualificationConfigInvalid
from astock_lens.qualifications.growth import GrowthQualifier
from astock_lens.qualifications.models import QualificationContext
from astock_lens.qualifications.rules import (
    FactorThreshold,
    FactorThresholdRule,
    load_qualification_rule,
)
from astock_lens.strategies.config import StrategyConfig
from astock_lens.strategies.contracts import StrategyContext, StrategyResult
from astock_lens.strategies.eligibility import EligibilityScanner

# ===========================================================================
# 来源：tests/unit/test_qualification_config.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 生产资格规则严格配置加载单元测试（fail-closed）。
#
# 覆盖规格 §5 要求拒绝的每一种畸形配置。设计原则：配置损坏必须响亮失败，
# 绝不允许"空阈值自动通过""畸形条目静默跳过""缺键静默兜底"。
# """
#


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


# ===========================================================================
# 来源：tests/unit/test_qualification_context.py（3 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# QualificationContext 单元测试：分离策略评分证据与绝对资格证据。
#
# 设计目标（见 2026-09-20 规格 §4）：资格判定必须读取该股票在正式 FACTOR
# Snapshot 中的**完整** FactorResult 集合，而不是仅能读取策略评分时保留的
# ``StrategyResult.factor_snapshot``。否则一个获批但非评分用途的因子（如
# Growth 的 ``roe_ttm``）将无法被资格规则取到，迫使实现者替换业务指标。
#
# 本测试用 Growth 复现该缺陷：``roe_ttm`` 在策略评分快照里不存在，只能通过
# ``QualificationContext.factors`` 提供。
# """
#


QUALIFICATION_CONTEXT_AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


# 测试专用获批 Growth 绝对规则：roe_ttm 是资格证据，但不是策略评分因子。
_GROWTH_ABSOLUTE_RULE = FactorThresholdRule(
    strategy_id="growth",
    version="v1",
    thresholds={
        "net_profit_parent_yoy": FactorThreshold(min=15.0),
        "revenue_yoy": FactorThreshold(min=5.0),
        "roe_ttm": FactorThreshold(min=8.0),
    },
)


qualifier = GrowthQualifier(
    absolute_rule=_GROWTH_ABSOLUTE_RULE,
    qualification_version="v1",
)


def factor(name: str, value: float) -> FactorResult:
    """构造一个 VALUE 状态的因子证据。"""
    return FactorResult(
        symbol="600000.SH",
        factor=name,
        as_of=QUALIFICATION_CONTEXT_AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def growth_result(
    *,
    rank_percentile: float,
    factor_snapshot: tuple[FactorResult, ...] = (),
) -> StrategyResult:
    """构造 Growth 策略结果；评分快照默认不含 roe_ttm。"""
    return StrategyResult(
        symbol="600000.SH",
        strategy_id="growth",
        strategy_version="v1",
        as_of=QUALIFICATION_CONTEXT_AS_OF,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=88.0,
        rank_percentile=rank_percentile,
        factor_snapshot=factor_snapshot,
    )


def test_growth_qualification_can_read_non_scoring_roe_factor() -> None:
    """Growth 资格能读取不在评分快照里的 roe_ttm 因子。"""
    context = QualificationContext(
        strategy_result=growth_result(rank_percentile=0.95),
        factors=(
            factor("net_profit_parent_yoy", 20.0),
            factor("revenue_yoy", 8.0),
            factor("roe_ttm", 9.0),
        ),
    )
    qualification = qualifier.qualify(context)
    assert qualification.absolute_pass is True
    assert qualification.qualified is True


def test_strategy_scoring_snapshot_is_not_used_as_qualification_evidence() -> None:
    """评分快照不得被当作资格证据来源。

    ``roe_ttm`` 存在于此处的评分快照里，但不在 ``context.factors`` 中，资格层
    必须基于 ``context.factors`` 判定为缺证据失败，证明两者已分离。
    """
    scoring_snapshot = (
        factor("net_profit_parent_yoy", 20.0),
        factor("revenue_yoy", 8.0),
        factor("roe_ttm", 30.0),
    )
    context = QualificationContext(
        strategy_result=growth_result(
            rank_percentile=0.95,
            factor_snapshot=scoring_snapshot,
        ),
        factors=(
            factor("net_profit_parent_yoy", 20.0),
            factor("revenue_yoy", 8.0),
        ),
    )
    qualification = qualifier.qualify(context)
    assert qualification.absolute_pass is False
    assert any("roe_ttm" in risk for risk in qualification.risks)


def test_qualification_context_defaults_to_no_factors() -> None:
    """``factors`` 默认空集：缺证据即失败关闭。"""
    context = QualificationContext(
        strategy_result=growth_result(rank_percentile=0.95),
    )
    assert context.factors == ()
    qualification = qualifier.qualify(context)
    assert qualification.absolute_pass is False


# ===========================================================================
# 来源：tests/unit/test_eligibility_scanner.py（9 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Eligibility-only scanner tests.
#
# The rule these tests pin down: with weights deferred
# (`docs/STRATEGY_SYSTEM.md` §5), a scanner may say whether a symbol's evidence
# is complete enough to consider, and must not say anything else. No score, no
# percentile, no confidence — each of those would be a number nobody reviewed,
# and a number reads downstream as a judgement.
# """
#


AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


SYMBOL = "600519.SH"


NON_VALUE_STATUSES = (
    DataStatus.NULL,
    DataStatus.STALE,
    DataStatus.INVALID,
    DataStatus.SOURCE_ERROR,
    DataStatus.NOT_APPLICABLE,
)


def _config(**overrides: object) -> StrategyConfig:
    payload: dict[str, object] = {
        "id": "quality",
        "version": "v1",
        "description": "quality",
        "required_factors": ["roe_ttm", "gross_margin"],
    }
    payload.update(overrides)
    return StrategyConfig.model_validate(payload)


def _factor(name: str, status: DataStatus, value: float | None = 1.0) -> FactorResult:
    return FactorResult(
        symbol=SYMBOL,
        factor=name,
        as_of=AS_OF,
        status=status,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
        unit="%",
    )


def _context(*factors: FactorResult) -> StrategyContext:
    return StrategyContext(symbol=SYMBOL, as_of=AS_OF, factors=tuple(factors))


def test_a_symbol_with_every_required_factor_is_eligible() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE, 17.7),
        _factor("gross_margin", DataStatus.VALUE, 89.5),
    )

    verdict = scanner.eligibility(context)

    assert verdict.eligible is True
    assert verdict.reasons == ()
    assert scanner.required_factors() == {"roe_ttm", "gross_margin"}


def test_the_verdict_never_carries_a_score() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE),
        _factor("gross_margin", DataStatus.VALUE),
    )

    result = scanner.score(context)

    assert result.eligible is True
    assert result.score is None
    assert result.rank_percentile is None
    assert result.confidence is None
    assert result.factor_snapshot == context.factors
    assert result.lineage.strategy_version == "v1"


def test_a_missing_factor_makes_the_symbol_ineligible_and_says_which() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(_factor("roe_ttm", DataStatus.VALUE))

    result = scanner.score(context)

    assert result.eligible is False
    assert "gross_margin was not computed for this symbol" in result.risks


def test_any_status_other_than_value_is_not_eligible() -> None:
    """六个状态保持可区分；除 VALUE 外都不算证据。"""
    wrong = []
    for status in NON_VALUE_STATUSES:
        scanner = EligibilityScanner(_config())
        context = _context(
            _factor("roe_ttm", DataStatus.VALUE),
            _factor("gross_margin", status, value=None),
        )
        result = scanner.score(context)
        if (
            result.eligible is not False
            or f"gross_margin is {status}, not VALUE" not in result.risks
        ):
            wrong.append(
                f"{status}: eligible={result.eligible!r} risks={result.risks!r}"
            )
    assert not wrong, "非 VALUE 状态不应算证据:\n" + "\n".join(wrong)


def test_a_population_gets_one_verdict_each_and_no_ranking() -> None:
    scanner = EligibilityScanner(_config())
    contexts = (
        _context(
            _factor("roe_ttm", DataStatus.VALUE),
            _factor("gross_margin", DataStatus.VALUE),
        ),
        _context(_factor("roe_ttm", DataStatus.VALUE)),
    )

    results = scanner.score_cross_section(contexts)

    assert len(results) == 2
    assert [result.eligible for result in results] == [True, False]
    assert all(result.rank_percentile is None for result in results)


def test_the_explanation_states_that_scoring_is_deferred() -> None:
    scanner = EligibilityScanner(_config())
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE),
        _factor("gross_margin", DataStatus.VALUE),
    )

    explanation = scanner.explain(scanner.score(context))

    assert "no score" in explanation.summary
    assert "not been reviewed" in explanation.summary
    assert {item.factor for item in explanation.factors} == {"roe_ttm", "gross_margin"}


def test_a_scanner_must_declare_what_it_requires() -> None:
    with pytest.raises(ValueError, match="must declare required_factors"):
        EligibilityScanner(_config(required_factors=[]))


def test_a_configured_scanner_with_weights_is_refused_here() -> None:
    """Weights mean a scoring implementation belongs, not this one."""
    with pytest.raises(ValueError, match="does not score"):
        EligibilityScanner(
            _config(required_factors=["roe_ttm"], weights={"roe_ttm": 1.0})
        )


def test_the_result_carries_the_configured_identity() -> None:
    """A verdict must name the scanner and version that produced it."""
    scanner = EligibilityScanner(_config(id="growth", version="v2"))
    context = _context(
        _factor("roe_ttm", DataStatus.VALUE),
        _factor("gross_margin", DataStatus.VALUE),
    )

    result = scanner.score(context)

    assert result.strategy_id == "growth"
    assert result.strategy_version == "v2"
    assert result.as_of == AS_OF
    assert result.symbol == SYMBOL
