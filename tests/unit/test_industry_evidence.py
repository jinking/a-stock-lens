"""行业映射来源必须随校准报告一起被保存，而且不许改变任何一个算出来的数。

这份报告在本阶段是**诊断材料**，不是已批准的产品规则。因此"缺 9 只行业的映射"
不该让整份报告消失——它该被如实写出来：谁给的映射、文件摘要、映射日期是声明的
还是未知的、缺了哪些代码。但同时有一条更硬的红线：**加了证据字段之后，策略与
因子的数值一个都不许变**。若两者冲突，数值正确优先。

本文件钉住三件事：

1. `IndustryEvidence` / `IndustryCoverage` 的字段与序列化形态；
2. `unknown_industry_symbols` 恰好是"参与计算标的 − 有行业归属标的"，稳定排序；
3. 换一份 `industry_evidence` 进去，报告里除它自己之外**逐字段完全相同**。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from astock_lens.calibration.candidate_report import (
    CALIBRATION_WARNING,
    IndustryCoverage,
    IndustryCoverageUnavailable,
    IndustryEvidence,
    generate_calibration_report,
)
from astock_lens.calibration.render import render_json, render_markdown
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult

AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
LINEAGE = SnapshotLineage(factor_version="v1", strategy_version="v1")


def _strat(symbol: str, strategy_id: str, percentile: float, score: float):
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=AS_OF,
        eligible=True,
        lineage=LINEAGE,
        score=score,
        rank_percentile=percentile,
    )


def _factor(symbol: str, factor: str, value: float | None):
    return FactorResult(
        symbol=symbol,
        factor=factor,
        factor_version="v1",
        as_of=AS_OF,
        status=DataStatus.VALUE if value is not None else DataStatus.NULL,
        raw_value=value,
        lineage=LINEAGE,
    )


def _inputs():
    """四只标的、四份因子，其中两只没有行业归属。"""
    strategies = (
        _strat("600001.SH", "momentum", 0.96, 96.0),
        _strat("600002.SH", "momentum", 0.91, 91.0),
        _strat("600003.SH", "quality", 0.88, 88.0),
        _strat("600004.SH", "quality", 0.71, 71.0),
    )
    factors = (
        _factor("600001.SH", "peg", 1.2),
        _factor("600002.SH", "peg", 0.8),
        _factor("600003.SH", "peg", None),
        _factor("600004.SH", "net_profit_parent_yoy", 25.0),
    )
    return strategies, factors


# --- 1. 两个新模型 -----------------------------------------------------------


def test_external_origin_survives_report_serialization() -> None:
    """计划里的原始断言：外部来源与"日期未知"都必须原样活到序列化之后。"""
    evidence = IndustryEvidence(origin="external", source_ref="sample.csv")
    report = generate_calibration_report(
        as_of=datetime(2026, 9, 17, 15, tzinfo=UTC),
        strategy_results=(),
        factor_results=(),
        industry_map={"600519.SH": "白酒Ⅱ"},
        industry_evidence=evidence,
    )
    payload = report.model_dump(mode="json")
    assert payload["industry_evidence"]["origin"] == "external"
    assert payload["industry_evidence"]["mapping_as_of"] is None
    assert payload["industry_evidence"]["diagnostic_only"] is True


def test_default_evidence_is_unspecified_and_diagnostic_only() -> None:
    """不传证据时是"未声明"，且仍然是诊断材料——不会默认变成规范映射。"""
    evidence = IndustryEvidence()
    assert evidence.origin == "unspecified"
    assert evidence.source_ref is None
    assert evidence.source_sha256 is None
    assert evidence.mapping_as_of is None
    assert evidence.diagnostic_only is True

    report = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=(),
        factor_results=(),
        industry_map={"600001.SH": "银行"},
    )
    assert report.industry_evidence.origin == "unspecified"
    assert report.industry_evidence.diagnostic_only is True


def test_every_report_is_diagnostic_material_with_no_approval_marker() -> None:
    """本阶段不许出现任何"已批准"标识，只有诊断标记与既有的"未批准"警戒语。"""
    report = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=(),
        factor_results=(),
        industry_map={"600001.SH": "银行"},
        industry_evidence=IndustryEvidence(origin="canonical", mapping_as_of=AS_OF),
    )
    payload = render_json(report)
    assert '"diagnostic_only": true' in payload
    assert CALIBRATION_WARNING in payload
    assert "NOT APPROVED" in payload
    for banned in ("已批准", "decision_grade", "approved_by", "sign_off"):
        assert banned not in payload, f"报告里出现了不该有的标识：{banned}"


# --- 2. 覆盖缺口就是集合差 -----------------------------------------------------


def test_missing_symbols_are_the_stable_set_difference() -> None:
    """缺口 = 参与计算标的 − 有行业归属标的，稳定排序，不用计数反推。"""
    strategies, factors = _inputs()
    report = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=strategies,
        factor_results=factors,
        industry_map={"600002.SH": "电子", "600004.SH": "医药"},
    )
    assert report.unknown_industry_symbols == ("600001.SH", "600003.SH")


def test_coverage_record_agrees_with_the_legacy_scalar_fields() -> None:
    """结构化的覆盖记录与既有的两个标量字段必须是同一件事。

    这三处一旦漂移，读者就会拿到两个互相矛盾的覆盖率；让它们同时出现在测试里，
    漂移就变成失败而不是"看运气"。
    """
    strategies, factors = _inputs()
    report = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=strategies,
        factor_results=factors,
        industry_map={"600002.SH": "电子"},
    )
    coverage = report.industry_coverage
    assert isinstance(coverage, IndustryCoverage)
    assert coverage.total_count == 4
    assert coverage.known_count == 1
    assert coverage.ratio == report.industry_coverage_ratio == 0.25
    assert len(coverage.missing_symbols) == report.unknown_industry_count == 3
    assert coverage.missing_symbols == report.unknown_industry_symbols


def test_a_symbol_with_a_blank_industry_counts_as_missing() -> None:
    """映射里给了空白行业字符串，等于没给——不许算作有归属。"""
    strategies, factors = _inputs()
    report = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=strategies,
        factor_results=factors,
        industry_map={
            "600001.SH": "银行",
            "600002.SH": "   ",
            "600003.SH": "电子",
            "600004.SH": "医药",
        },
    )
    assert report.unknown_industry_symbols == ("600002.SH",)


def test_full_coverage_is_required_only_when_asked() -> None:
    """`require_full_industry_coverage` 是唯一会拒绝的分支，且名字没变。"""
    strategies, factors = _inputs()
    kwargs = {
        "as_of": AS_OF,
        "strategy_results": strategies,
        "factor_results": factors,
        "industry_map": {"600001.SH": "银行"},
    }
    # 不要求完整覆盖：出诊断，缺口如实列出。
    diagnostic = generate_calibration_report(**kwargs)
    assert diagnostic.unknown_industry_count == 3

    with pytest.raises(IndustryCoverageUnavailable, match="3 of 4"):
        generate_calibration_report(**kwargs, require_full_industry_coverage=True)


# --- 3. 数值不许变 ------------------------------------------------------------


def test_industry_evidence_never_changes_a_single_computed_number() -> None:
    """证据是"附加说明"，不是"计算输入"：换掉它，其余字段必须逐字段相同。"""
    strategies, factors = _inputs()
    common = {
        "as_of": AS_OF,
        "strategy_results": strategies,
        "factor_results": factors,
        "industry_map": {"600001.SH": "银行", "600002.SH": "电子"},
    }
    plain = generate_calibration_report(**common).model_dump(mode="json")
    enriched = generate_calibration_report(
        **common,
        industry_evidence=IndustryEvidence(
            origin="external",
            source_ref="var/industry-map.csv",
            source_sha256="0" * 64,
            mapping_as_of=datetime(2026, 10, 1, 15, tzinfo=UTC),
        ),
    ).model_dump(mode="json")

    plain.pop("industry_evidence")
    enriched.pop("industry_evidence")
    assert plain == enriched


# --- 4. Markdown 必须把局限写在脸上 --------------------------------------------


def test_markdown_states_diagnostic_origin_and_an_unknown_date() -> None:
    strategies, factors = _inputs()
    report = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=strategies,
        factor_results=factors,
        industry_map={"600002.SH": "电子", "600004.SH": "医药"},
        industry_evidence=IndustryEvidence(origin="external", source_ref="sample.csv"),
    )
    markdown = render_markdown(report)
    assert "诊断材料" in markdown
    assert "external" in markdown
    assert "sample.csv" in markdown
    assert "日期未知" in markdown
    assert "mtime" in markdown
    assert "600001.SH" in markdown and "600003.SH" in markdown
    assert "600002.SH" in markdown


def test_markdown_flags_a_mapping_date_later_than_the_analysis_point() -> None:
    """晚于分析时点的映射只能展示，不能用它冒充该时点的正式行业证据。"""
    report = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=(),
        factor_results=(),
        industry_map={"600001.SH": "银行"},
        industry_evidence=IndustryEvidence(
            origin="canonical",
            source_ref="data/raw/westock/industry/2026-09-18.csv",
            mapping_as_of=datetime(2026, 9, 18, 15, 0, tzinfo=UTC),
        ),
    )
    markdown = render_markdown(report)
    assert "晚于分析时点" in markdown
    assert "2026-09-18T15:00:00+00:00" in markdown
    assert "canonical" in markdown


def test_markdown_declares_the_date_when_it_is_known() -> None:
    report = generate_calibration_report(
        as_of=AS_OF,
        strategy_results=(),
        factor_results=(),
        industry_map={"600001.SH": "银行"},
        industry_evidence=IndustryEvidence(
            origin="canonical",
            source_ref="data/raw/westock/industry/2026-09-17.csv",
            source_sha256="a" * 64,
            mapping_as_of=AS_OF,
        ),
    )
    markdown = render_markdown(report)
    assert "2026-09-17T15:00:00+00:00" in markdown
    assert "日期未知" not in markdown
    assert "a" * 64 in markdown
    assert "缺失行业代码（0）" in markdown


def test_markdown_is_still_byte_for_byte_deterministic_with_evidence() -> None:
    """加了证据之后，同一份输入仍然逐字节可复现。"""
    strategies, factors = _inputs()
    common = {
        "as_of": AS_OF,
        "factor_results": factors,
        "industry_map": {"600001.SH": "银行", "600002.SH": "电子"},
        "industry_evidence": IndustryEvidence(
            origin="external", source_ref="sample.csv", source_sha256="b" * 64
        ),
    }
    first = render_markdown(
        generate_calibration_report(strategy_results=strategies, **common)
    )
    second = render_markdown(
        generate_calibration_report(
            strategy_results=tuple(reversed(strategies)), **common
        )
    )
    assert first == second
