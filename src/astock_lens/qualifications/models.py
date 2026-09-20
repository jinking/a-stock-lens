"""Strategy qualification models."""

from astock_lens.domain.models import DomainRecord
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult


class AbsoluteQualificationVerdict(DomainRecord):
    """Result of evaluating an absolute qualification rule."""

    passed: bool
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


class QualificationContext(DomainRecord):
    """资格判定所需的完整证据。

    刻意把两类证据分开（见 2026-09-20 资格正确性加固规格 §4）：

    - ``strategy_result``：该策略的 score / rank / eligibility；
    - ``factors``：该股票在正式 FACTOR Snapshot 中的**完整** FactorResult 集合。

    ``StrategyResult.factor_snapshot`` 表达的是策略评分因子，不等于资格规则
    的全部证据。资格判定必须读取 ``factors``，否则一个获批但非评分用途的因子
    （例如 Growth 的 ``roe_ttm``）将无法被取到，逼迫实现者替换业务指标。
    """

    strategy_result: StrategyResult
    factors: tuple[FactorResult, ...] = ()


class StrategyQualification(DomainRecord):
    """Result of evaluating a symbol against a strategy's dual qualification gate."""

    symbol: str
    strategy_id: str
    strategy_version: str
    qualification_version: str
    qualified: bool
    percentile_pass: bool
    absolute_pass: bool
    rank_percentile: float
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
