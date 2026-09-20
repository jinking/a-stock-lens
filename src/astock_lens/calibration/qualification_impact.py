"""只读的六策略资格规则影响审计（Qualification Impact Audit）。

本模块把生产资格口径（``qualification_stage``）**原样复用**后再聚合计数，绝不
另起一套阈值评估；因此审计口径与生产口径物理上不可能漂移。

口径事实（务必知悉）：

- FACTOR 快照是**全市场**口径（每只标的所有因子）；
- STRATEGY 快照是**研究池**口径（仅研究池标的的策略结果）。

``FactorResultIndex`` 只构建一次，避免把整张因子表按 symbol 反复全扫。

"代表性边界样本"的确定性定义（并列时按 ``symbol`` 升序）：

- 相对边界 margin = 该策略各阈值边界上 ``|value - bound| / |bound|`` 的最小值；
- 双通过样本取 margin 最小的最多 5 只；
- 绝对失败样本取 margin 最小的最多 5 只。
"""

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines.stages import FactorResultIndex, qualification_stage
from astock_lens.qualifications.config import FactorThreshold
from astock_lens.qualifications.contracts import StrategyQualifier
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult

IMPACT_WARNING = "READ-ONLY AUDIT — NO CANDIDATE IS PUBLISHED"
_BOUNDARY_SAMPLE_LIMIT = 5
_QUALIFIED_SYMBOL_LIMIT = 20
_FACTOR_RISK_PATTERN = re.compile(r"factor '([^']+)'")


class QualificationImpactUnsupportedQualifier(RuntimeError):
    """Raised when a qualifier cannot expose absolute thresholds for the audit.

    只读审计为了挑选"最接近边界的样本"，需要每个策略 qualifier 的已批准绝对因子
    阈值。一个只满足公开 ``StrategyQualifier`` 协议（没有可用的
    ``absolute_rule.thresholds`` 映射）的 qualifier 无法被审计；此时**绝不**把
    "读不到阈值"静默降级成"边界样本为空"，而是点名 ``strategy_id`` 与 qualifier
    类型，响亮失败。
    """


class StrategyQualificationImpact(DomainRecord):
    """单一策略的资格影响聚合。"""

    strategy_id: str
    strategy_eligible_count: int
    ranked_count: int
    top_ten_count: int
    absolute_pass_count: int
    dual_pass_count: int
    failure_reasons: tuple[tuple[str, int], ...]
    qualified_symbols: tuple[str, ...]
    closest_dual_pass_symbols: tuple[str, ...] = ()
    closest_absolute_fail_symbols: tuple[str, ...] = ()


class QualificationImpactReport(DomainRecord):
    """一次只读资格影响审计的完整报告。"""

    as_of: datetime
    strategies: tuple[StrategyQualificationImpact, ...]


def _factor_of_risk(risk: str) -> str | None:
    """从 risk 串中提取因子名（``factor '<name>' ...``）。"""
    match = _FACTOR_RISK_PATTERN.search(risk)
    return match.group(1) if match else None


def _absolute_thresholds(
    qualifier: StrategyQualifier | None, strategy_id: str
) -> Mapping[str, FactorThreshold]:
    """Read a qualifier's approved absolute thresholds, or fail loudly.

    ``StrategyQualifier`` 协议本身只声明 ``strategy_id`` / ``qualification_version``
    / ``qualify``，并不声明 ``absolute_rule``；六个生产 qualifier 都在具体实现上
    暴露 ``absolute_rule.thresholds``。这里做**显式运行时校验**而非无检查的
    ``cast``：读不到阈值映射即抛 ``QualificationImpactUnsupportedQualifier``
    （可诊断），绝不把"读不到阈值"静默降级成"边界样本为空"。
    """
    rule = getattr(qualifier, "absolute_rule", None)
    thresholds = getattr(rule, "thresholds", None)
    if not isinstance(thresholds, Mapping):
        raise QualificationImpactUnsupportedQualifier(
            f"Qualifier for strategy '{strategy_id}' "
            f"(type={type(qualifier).__name__}) does not expose an "
            f"'absolute_rule.thresholds' mapping; the read-only audit cannot "
            f"select boundary samples without approved thresholds"
        )
    return thresholds


def _symbol_margin(
    thresholds: Mapping[str, FactorThreshold],
    factors_by_name: Mapping[str, FactorResult],
) -> float | None:
    """该标的相对策略阈值的相对边界 margin；无可比较边界返回 None。"""
    margins: list[float] = []
    for factor_name, threshold in thresholds.items():
        factor_res = factors_by_name.get(factor_name)
        if (
            factor_res is None
            or factor_res.raw_value is None
            or factor_res.status != DataStatus.VALUE
        ):
            continue
        value = factor_res.raw_value
        for bound in (threshold.min, threshold.max):
            if bound is None or bound == 0:
                continue
            margins.append(abs(value - bound) / abs(bound))
    return min(margins) if margins else None


def _boundary_symbols(
    qualifications: Sequence[StrategyQualification],
    *,
    want_dual_pass: bool,
    thresholds: Mapping[str, FactorThreshold],
    index: FactorResultIndex,
) -> tuple[str, ...]:
    """取最接近边界的样本；并列按 symbol 升序。"""
    scored: list[tuple[float, str]] = []
    for qualification in qualifications:
        predicate = (
            qualification.qualified
            if want_dual_pass
            else not qualification.absolute_pass
        )
        if not predicate:
            continue
        factors_by_name = {
            factor.factor: factor for factor in index.for_symbol(qualification.symbol)
        }
        margin = _symbol_margin(thresholds, factors_by_name)
        if margin is None:
            continue
        scored.append((margin, qualification.symbol))
    scored.sort(key=lambda item: (item[0], item[1]))
    return tuple(symbol for _, symbol in scored[:_BOUNDARY_SAMPLE_LIMIT])


def build_qualification_impact(
    *,
    factor_results: Sequence[FactorResult],
    strategy_results: Sequence[StrategyResult],
    qualifiers: Mapping[str, StrategyQualifier],
    as_of: datetime,
) -> QualificationImpactReport:
    """Build the read-only qualification impact report.

    复用 ``qualification_stage`` 得到 ``StrategyQualification``，再从它聚合计数，
    因此审计口径与生产口径完全一致。
    """
    index = FactorResultIndex(factor_results)
    qualifications = qualification_stage(
        strategy_results=strategy_results,
        factor_results=factor_results,
        qualifiers=qualifiers,
    )

    eligible_counts: Counter[str] = Counter(
        result.strategy_id for result in strategy_results if result.eligible
    )
    by_strategy: dict[str, list[StrategyQualification]] = {}
    for qualification in qualifications:
        by_strategy.setdefault(qualification.strategy_id, []).append(qualification)

    strategies: list[StrategyQualificationImpact] = []
    for strategy_id in sorted(eligible_counts):
        strategy_qualifications = by_strategy.get(strategy_id, [])
        ranked = [q for q in strategy_qualifications if q.rank_percentile is not None]

        reason_counter: Counter[str] = Counter()
        for qualification in strategy_qualifications:
            for risk in qualification.risks:
                factor_name = _factor_of_risk(risk)
                # 抠得出因子名就用因子名；抠不出就用 risk 原文作键——任何一条
                # risk 都不得被静默丢弃（AGENTS.md 禁止静默兜底）。这样文案一旦
                # 变形，未识别的文案仍会以其原文出现在 failure_reasons 中。
                reason_counter[factor_name if factor_name is not None else risk] += 1
        failure_reasons = tuple(
            sorted(reason_counter.items(), key=lambda item: (-item[1], item[0]))
        )

        qualified_symbols = tuple(
            sorted({q.symbol for q in strategy_qualifications if q.qualified})
        )

        thresholds = _absolute_thresholds(qualifiers.get(strategy_id), strategy_id)

        strategies.append(
            StrategyQualificationImpact(
                strategy_id=strategy_id,
                strategy_eligible_count=eligible_counts[strategy_id],
                ranked_count=len(ranked),
                top_ten_count=sum(
                    1 for q in strategy_qualifications if q.percentile_pass
                ),
                absolute_pass_count=sum(
                    1 for q in strategy_qualifications if q.absolute_pass
                ),
                dual_pass_count=sum(1 for q in strategy_qualifications if q.qualified),
                failure_reasons=failure_reasons,
                qualified_symbols=qualified_symbols,
                closest_dual_pass_symbols=_boundary_symbols(
                    strategy_qualifications,
                    want_dual_pass=True,
                    thresholds=thresholds,
                    index=index,
                ),
                closest_absolute_fail_symbols=_boundary_symbols(
                    strategy_qualifications,
                    want_dual_pass=False,
                    thresholds=thresholds,
                    index=index,
                ),
            )
        )

    return QualificationImpactReport(as_of=as_of, strategies=tuple(strategies))


def render_impact_json(report: QualificationImpactReport) -> str:
    """Render the impact report as pretty-printed deterministic JSON."""
    return json.dumps(
        report.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False
    )


def render_impact_markdown(report: QualificationImpactReport) -> str:
    """Render the impact report as deterministic GitHub-flavored Markdown."""
    lines: list[str] = [
        "# Qualification Impact Audit (read-only)",
        "",
        f"> **WARNING: {IMPACT_WARNING}**",
        "",
        f"- **As of:** {report.as_of.isoformat()}",
        (
            "- **Scope:** FACTOR 快照为全市场口径，STRATEGY 快照为研究池口径；"
            "本命令只读已存快照，不重算、不写 Snapshot/Candidate。"
        ),
        "",
        "## 1. Strategy Summary",
        "",
        "| strategy | eligible | ranked | top10 | absolute-pass | dual-pass |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for strategy in report.strategies:
        lines.append(
            f"| {strategy.strategy_id} | {strategy.strategy_eligible_count} | "
            f"{strategy.ranked_count} | {strategy.top_ten_count} | "
            f"{strategy.absolute_pass_count} | {strategy.dual_pass_count} |"
        )

    lines.extend(["", "## 2. Per-Strategy Detail", ""])
    for strategy in report.strategies:
        lines.append(f"### Strategy: `{strategy.strategy_id}`")
        if strategy.failure_reasons:
            reasons = ", ".join(
                f"{factor}={count}" for factor, count in strategy.failure_reasons
            )
        else:
            reasons = "None"
        lines.append(f"- **Top failure reasons:** {reasons}")

        if strategy.qualified_symbols:
            shown = list(strategy.qualified_symbols[:_QUALIFIED_SYMBOL_LIMIT])
            more = len(strategy.qualified_symbols) - len(shown)
            suffix = f" (+{more} more)" if more > 0 else ""
            symbols = ", ".join(shown) + suffix
        else:
            symbols = "None"
        lines.append(
            f"- **Qualified symbols ({len(strategy.qualified_symbols)}):** {symbols}"
        )

        dual_boundary = ", ".join(strategy.closest_dual_pass_symbols) or "None"
        fail_boundary = ", ".join(strategy.closest_absolute_fail_symbols) or "None"
        lines.append(f"- **Boundary samples (closest dual-pass):** {dual_boundary}")
        lines.append(f"- **Boundary samples (closest absolute-fail):** {fail_boundary}")
        lines.append("")

    lines.append("")
    return "\n".join(lines)
