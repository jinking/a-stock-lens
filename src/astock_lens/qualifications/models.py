"""Strategy qualification models."""

from astock_lens.domain.models import DomainRecord


class AbsoluteQualificationVerdict(DomainRecord):
    """Result of evaluating an absolute qualification rule."""

    passed: bool
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


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
