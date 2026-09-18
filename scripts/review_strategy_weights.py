"""Review candidate weight sets against real whole-market data.

`docs/STRATEGY_SYSTEM.md` §5 defers every scanner's weights and score
thresholds, so the numbers below are **candidates for review, not decisions**:
they exist to make the decision concrete. The script shows what each candidate
would select, how the selection changes when the weights change, and whether
the top quintile actually exhibits the phenotype the strategy is supposed to
describe (§20.4).

Nothing here writes a configuration. When a weight set is approved, its numbers
go into `configs/strategies/<id>.yaml` and `WeightedPercentileScanner` starts
scoring with them — no code change.

Usage:

    uv run python scripts/review_strategy_weights.py --root /path/to/raw
    uv run python scripts/review_strategy_weights.py --strategy quality --top 15
"""

import argparse
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astock_lens.strategies.weighted import WeightedPercentileScanner

from astock_lens.data.contracts import FetchRequest, NormalizedDataset
from astock_lens.data.normalize.valuations import NeodataValuationNormalizer
from astock_lens.data.providers.neodata import NeodataProvider
from astock_lens.domain.models import ValuationObservation
from astock_lens.factors.builtin import build_factor
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.factors.contracts import FactorContext, FactorResult
from astock_lens.pipelines import stages
from astock_lens.strategies.config import StrategyConfig, load_strategy_config
from astock_lens.strategies.contracts import StrategyContext, StrategyResult

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "configs" / "strategies"
FACTOR_DIR = ROOT / "configs" / "factors"


class Candidate:
    """One weight set, with the reasoning a reviewer is being asked to judge."""

    def __init__(self, name: str, weights: Mapping[str, float], rationale: str) -> None:
        self.name = name
        self.weights = dict(weights)
        self.rationale = rationale


# The design's own language, turned into concrete alternatives. Each candidate
# answers "what would change if we believed this emphasis?", so the differences
# are attributable rather than arbitrary.
CANDIDATES: Mapping[str, tuple[Candidate, ...]] = {
    "value": (
        Candidate(
            "equal",
            {
                "pe_ttm": -1.0,
                "pb": -1.0,
                "ps_ttm": -1.0,
                "pe_percentile": -1.0,
                "pcf_operating_ttm": -1.0,
                "roe_ttm": 1.0,
            },
            "中性基线：便宜程度（PE/PB/PS/市现率/历史分位）与质量等权",
        ),
        Candidate(
            "cheapness_first",
            {
                "pe_ttm": -1.5,
                "pb": -1.0,
                "ps_ttm": -0.5,
                "pe_percentile": -1.5,
                "pcf_operating_ttm": -1.0,
                "roe_ttm": 0.5,
            },
            "便宜优先：PE 与自身历史分位为主，质量只作否决线",
        ),
        Candidate(
            "quality_bargain",
            {
                "pe_ttm": -1.0,
                "pb": -0.5,
                "ps_ttm": -0.5,
                "pe_percentile": -1.0,
                "pcf_operating_ttm": -1.0,
                "roe_ttm": 1.5,
            },
            "便宜但要能赚钱：ROE 加重，避免只捡便宜货",
        ),
    ),
    "garp": (
        Candidate(
            "equal",
            {
                "peg": -1.0,
                "pe_percentile": -1.0,
                "revenue_cagr_3y": 1.0,
                "net_profit_parent_cagr_3y": 1.0,
                "roe_ttm": 1.0,
            },
            "中性基线：成长、估值匹配（PEG/分位）与质量等权",
        ),
        Candidate(
            "growth_first",
            {
                "peg": -1.0,
                "pe_percentile": -0.5,
                "revenue_cagr_3y": 1.5,
                "net_profit_parent_cagr_3y": 1.5,
                "roe_ttm": 0.5,
            },
            "成长优先：3 年复合增速为主，估值分位只作约束",
        ),
        Candidate(
            "valuation_match_first",
            {
                "peg": -1.5,
                "pe_percentile": -1.5,
                "revenue_cagr_3y": 0.5,
                "net_profit_parent_cagr_3y": 0.5,
                "roe_ttm": 1.0,
            },
            "匹配优先：PEG 与历史分位为主，成长只要不差即可",
        ),
    ),
    "quality": (
        Candidate(
            "equal",
            {
                "roe_ttm": 1.0,
                "gross_margin": 1.0,
                "debt_to_asset": -1.0,
                "ocf_to_net_profit": 1.0,
            },
            "neutral baseline: every dimension counts the same",
        ),
        Candidate(
            "return_and_cash_first",
            {
                "roe_ttm": 1.5,
                "gross_margin": 1.0,
                "debt_to_asset": -0.5,
                "ocf_to_net_profit": 1.5,
            },
            "durable profitability and cash conversion matter more than leverage",
        ),
        Candidate(
            "balance_sheet_first",
            {
                "roe_ttm": 1.0,
                "gross_margin": 0.5,
                "debt_to_asset": -2.0,
                "ocf_to_net_profit": 1.0,
            },
            "solvency first: a leveraged balance sheet dominates the ranking",
        ),
    ),
    "growth": (
        Candidate(
            "equal",
            {
                "revenue_yoy": 1.0,
                "revenue_cagr_3y": 1.0,
                "net_profit_parent_yoy": 1.0,
                "net_profit_parent_cagr_3y": 1.0,
            },
            "neutral baseline: latest print and three-year persistence weigh the same",
        ),
        Candidate(
            "persistence_first",
            {
                "revenue_yoy": 0.5,
                "revenue_cagr_3y": 1.5,
                "net_profit_parent_yoy": 0.5,
                "net_profit_parent_cagr_3y": 1.5,
            },
            "three-year persistence above the latest quarter's print",
        ),
        Candidate(
            "latest_print_first",
            {
                "revenue_yoy": 1.5,
                "revenue_cagr_3y": 0.5,
                "net_profit_parent_yoy": 1.5,
                "net_profit_parent_cagr_3y": 0.5,
            },
            "the newest quarter's growth above the long record",
        ),
    ),
    "dividend": (
        Candidate(
            "equal",
            {"dividend_paid_ratio": 1.0, "ocf_to_net_profit": 1.0},
            "neutral baseline: payout and cash coverage weigh the same",
        ),
        Candidate(
            "coverage_first",
            {"dividend_paid_ratio": 0.5, "ocf_to_net_profit": 1.5},
            "the design's emphasis: coverage before headline payout",
        ),
        Candidate(
            "retention_first",
            {"dividend_paid_ratio": -0.5, "ocf_to_net_profit": 1.5},
            "payout inverted: prefer companies that keep more cash in the business",
        ),
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data/raw", type=Path)
    parser.add_argument(
        "--as-of",
        default=None,
        help="Trade date YYYY-MM-DD; defaults to today's A-share close.",
    )
    parser.add_argument("--strategy", default="all")
    parser.add_argument("--top", default=15, type=int)
    parser.add_argument("--quintile", default=0.2, type=float)
    parser.add_argument(
        "--valuation-sample",
        default=0,
        type=int,
        help=(
            "取这么多只标的的真实估值（等距抽样、每批 10 只）。"
            "全市场估值落地尚未接入，评审因此先用抽样数据。"
        ),
    )
    args = parser.parse_args()

    as_of = _as_of(args.as_of)
    strategies = list(CANDIDATES) if args.strategy == "all" else [args.strategy]

    inputs = stages.financial_inputs(args.root, as_of=as_of)
    print(
        f"data: {len(inputs.observations):,} observations, "
        f"{len({item.symbol for item in inputs.observations}):,} symbols, "
        f"absent datasets: {list(inputs.absent_datasets) or 'none'}"
    )
    if not inputs.observations:
        print("no observations landed under this root; run `astock sync --financials`")
        return 1

    valuations = ()
    if args.valuation_sample:
        symbols = _sample(
            sorted({item.symbol for item in inputs.observations}),
            args.valuation_sample,
        )
        valuations = _fetch_valuations(symbols, as_of)
        print(
            f"估值抽样：请求 {len(symbols)} 只，取到 "
            f"{len({item.symbol for item in valuations})} 只、"
            f"{len(valuations):,} 条观测"
        )

    dataset = NormalizedDataset(
        dataset="financials",
        as_of=as_of,
        observations=inputs.observations,
        valuations=valuations,
    )
    factors = _factor_cache(dataset, as_of)

    for strategy_id in strategies:
        config = load_strategy_config(STRATEGY_DIR / f"{strategy_id}.yaml")
        contexts = _contexts(config, factors, as_of)
        print(
            f"\n=== {strategy_id} ({len(contexts):,} symbols with every required factor)"
        )
        if not contexts:
            print("  no symbol carries all required factors; nothing to rank")
            continue
        _review(config, contexts, args.top, args.quintile)
    return 0


def _review(
    config: StrategyConfig,
    contexts: Sequence[StrategyContext],
    top: int,
    quintile: float,
) -> None:
    """Print what each candidate would select, and how they differ."""
    _evidence_availability(config, contexts)
    selections: dict[str, tuple[StrategyResult, ...]] = {}
    for candidate in CANDIDATES[config.id]:
        weighted = config.model_copy(update={"weights": candidate.weights})
        scanner = WeightedPercentileScanner(weighted)
        ranked = sorted(
            (
                result
                for result in scanner.score_cross_section(contexts)
                if result.score
            ),
            key=lambda result: result.score or 0.0,
            reverse=True,
        )
        selections[candidate.name] = tuple(ranked)
        print(f"\n-- candidate {candidate.name}: {candidate.rationale}")
        print(f"   weights: {candidate.weights}")
        print(f"   scored: {len(ranked):,}")
        for result in ranked[:top]:
            print(f"     {result.symbol:12s} {result.score:6.2f}  {_evidence(result)}")
        _phenotype(ranked, config, quintile)

    names = list(selections)
    baseline = {result.symbol for result in selections[names[0]][:top]}
    for name in names[1:]:
        overlap = baseline & {result.symbol for result in selections[name][:top]}
        print(
            f"\n   top-{top} overlap between {names[0]!r} and {name!r}: "
            f"{len(overlap)}/{top} ({len(overlap) / top:.0%})"
        )


def _evidence_availability(
    config: StrategyConfig, contexts: Sequence[StrategyContext]
) -> None:
    """逐因子报告可用性：资格为 0 时，第一个要看的就是"哪一项永远缺"。

    这条诊断来自一次真实的空结果——某因子在源站整列为 `--`，导致资格恒为假，
    而当时的输出只有"scored: 0"，看不出是数据缺还是权重差。
    """
    print("   证据可用性（VALUE/其他）：")
    for name in config.required_factors:
        counts: dict[str, int] = {}
        for context in contexts:
            status = next(
                (item.status.value for item in context.factors if item.factor == name),
                "缺失",
            )
            counts[status] = counts.get(status, 0) + 1
        detail = ", ".join(f"{key} {value}" for key, value in sorted(counts.items()))
        print(f"     {name:24s} {detail}")


def _phenotype(
    ranked: Sequence[StrategyResult], config: StrategyConfig, quintile: float
) -> None:
    """Compare the top slice against the rest, per factor (§20.4).

    A strategy is supposed to describe something. If the top slice is not
    stronger on the factors it claims to weigh, the weights are describing
    something else — which is worth knowing before they are approved.
    """
    if len(ranked) < 5:
        return
    cut = max(1, int(len(ranked) * quintile))
    head, tail = ranked[:cut], ranked[cut:]
    for name in config.required_factors:
        head_mean = _mean(head, name)
        tail_mean = _mean(tail, name)
        if head_mean is None or tail_mean is None:
            continue
        print(
            f"     phenotype {name:32s} top quintile {head_mean:9.3f} "
            f"vs rest {tail_mean:9.3f}"
        )


def _mean(results: Sequence[StrategyResult], factor: str) -> float | None:
    values = [
        item.raw_value
        for result in results
        for item in result.factor_snapshot
        if item.factor == factor and item.raw_value is not None
    ]
    return sum(values) / len(values) if values else None


def _evidence(result: StrategyResult) -> str:
    """The factor values behind one score, so a reader can check it."""
    return "  ".join(
        f"{item.factor}={item.raw_value:.3f}"
        if item.raw_value is not None
        else f"{item.factor}={item.status}"
        for item in result.factor_snapshot
    )


def _contexts(
    config: StrategyConfig,
    cache: Mapping[tuple[str, str], FactorResult],
    as_of: datetime,
) -> tuple[StrategyContext, ...]:
    """One context per symbol that has every factor the strategy requires."""
    symbols = sorted({symbol for symbol, _ in cache})
    contexts: list[StrategyContext] = []
    for symbol in symbols:
        factors = tuple(
            cache[(symbol, name)]
            for name in config.required_factors
            if (symbol, name) in cache
        )
        if len(factors) == len(config.required_factors):
            contexts.append(
                StrategyContext(symbol=symbol, as_of=as_of, factors=factors)
            )
    return tuple(contexts)


def _factor_cache(
    dataset: NormalizedDataset, as_of: datetime
) -> dict[tuple[str, str], FactorResult]:
    """Compute every factor a candidate strategy might need, once per symbol."""
    configs: tuple[FactorConfig, ...] = tuple(
        load_factor_config(path) for path in sorted(FACTOR_DIR.glob("*.yaml"))
    )
    wanted = {
        name
        for config in CANDIDATES.values()
        for item in config
        for name in item.weights
    }
    registry = [build_factor(config) for config in configs if config.name in wanted]
    index = stages.DatasetIndex(dataset)

    symbols = sorted({item.symbol for item in dataset.observations})
    cache: dict[tuple[str, str], FactorResult] = {}
    for symbol in symbols:
        context = FactorContext(
            symbol=symbol, as_of=as_of, dataset=index.for_symbol(symbol)
        )
        for factor in registry:
            cache[(symbol, factor.metadata.name)] = factor.compute(context)
    return cache


def _as_of(value: str | None) -> datetime:
    """A bare date means the A-share close, as every other entry point does.

    Same convention as `astock --as-of`: 15:00 Asia/Shanghai, so a review looks
    at exactly the point in time the CLI would.
    """
    shanghai = ZoneInfo("Asia/Shanghai")
    day: date = date.fromisoformat(value) if value else datetime.now(shanghai).date()
    return datetime(day.year, day.month, day.day, 15, 0, tzinfo=shanghai)


def _sample(symbols: Sequence[str], size: int) -> tuple[str, ...]:
    """等距抽样：覆盖整个名单，而不是只取前 N 只（后者会集中在一个交易所/板块）。"""
    if size >= len(symbols):
        return tuple(symbols)
    stride = len(symbols) / size
    return tuple(symbols[int(index * stride)] for index in range(size))


def _fetch_valuations(
    symbols: Sequence[str], as_of: datetime
) -> tuple[ValuationObservation, ...]:
    """按批取真实估值并归一化。

    全市场估值落地（按板块迭代）尚未接入，评审先用抽样证明权重选择的效果；
    抽样会打印命中数，避免把"样本小"误读成"数据没有"。

    **逐标的取。** 实测（2026-09-17）：10 只一批的估值查询只回 1–2 只
    （120 只抽样只回 23 只），而单标的查询稳定返回。财报查询的批量覆盖是 2/3，
    估值不是——两者的批量能力不同，因此这里按 1 只一批调用。
    """
    provider = NeodataProvider()
    health = provider.health()
    if not health.healthy:
        print(f"neodata 不可用：{health.message}")
        return ()

    normalizer = NeodataValuationNormalizer()
    collected: list[ValuationObservation] = []
    missing: list[str] = []
    for index, symbol in enumerate(symbols, start=1):
        raw = provider.fetch(
            FetchRequest(dataset="valuation", as_of=as_of, symbols=(symbol,))
        )
        if raw.payload is None or raw.missing_symbols:
            missing.append(symbol)
            continue
        collected.extend(normalizer.normalize(raw, as_of=as_of).observations)
        if index % 10 == 0:
            print(f"  …已取 {index}/{len(symbols)} 只")
    if missing:
        print(f"  源站未返回的标的 {len(missing)} 只（计入缺失，不补零）")
    return tuple(collected)


if __name__ == "__main__":
    raise SystemExit(main())
