"""Universe construction.

Every exclusion must carry the rule that caused it. A snapshot that only listed
the survivors would make "why is this symbol missing?" unanswerable, which is
the failure mode the design's explainability principle is written against.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DailyBar, SecurityProfile, SnapshotLineage
from astock_lens.factors.contracts import FactorResult
from astock_lens.universe.builder import UniverseBuilder
from astock_lens.universe.config import UniverseConfig, load_universe_config
from astock_lens.universe.models import UniverseRule, UniverseSnapshot

ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)

# Every symbol in the fixture that has both a bar and a liquidity measure.
# 000007.SZ is deliberately absent from both, and 000005.SZ is present but poor.
MEASURED = (
    "000001.SZ",
    "000002.SZ",
    "000003.SZ",
    "000004.SZ",
    "000005.SZ",
    "000006.SZ",
    "600000.SH",
    "600519.SH",
    "300750.SZ",
    "830799.BJ",
    "900948.SH",
)

LOW_LIQUIDITY_SYMBOL = "000005.SZ"
LOW_LIQUIDITY_VALUE = 5_000_000.0
# 健康样本必须站在这条门槛之上：门槛由所有者决定（2026-09-18 起 1.5 亿），
# 测试不钉门槛的具体数值，只保证"明显高于它"，这样门槛调整不会把规则测试一起打翻。
HEALTHY_LIQUIDITY_VALUE = 200_000_000.0


def _config() -> UniverseConfig:
    return load_universe_config(ROOT / "configs" / "universe.yaml")


def _profiles() -> tuple[SecurityProfile, ...]:
    raw = LocalCsvProvider(CSV_ROOT).fetch(
        FetchRequest(dataset="securities", as_of=AS_OF)
    )
    return CsvSecurityNormalizer().normalize(raw, as_of=AS_OF).securities


def _bars() -> tuple[DailyBar, ...]:
    """One bar on the as-of date for every symbol except `000007.SZ`."""
    return tuple(
        DailyBar(symbol=symbol, trade_date=AS_OF.date(), close=10.0)
        for symbol in MEASURED
    )


def _liquidity() -> dict[str, FactorResult]:
    return {
        symbol: FactorResult(
            symbol=symbol,
            factor="avg_amount_20d",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=(
                LOW_LIQUIDITY_VALUE
                if symbol == LOW_LIQUIDITY_SYMBOL
                else HEALTHY_LIQUIDITY_VALUE
            ),
        )
        for symbol in MEASURED
    }


def _build(config: UniverseConfig | None = None) -> UniverseSnapshot:
    return UniverseBuilder(config or _config()).build(
        _profiles(),
        as_of=AS_OF,
        bars=_bars(),
        liquidity=_liquidity(),
    )


def _rules(snapshot: UniverseSnapshot, symbol: str) -> tuple[UniverseRule, ...]:
    return tuple(
        exclusion.rule
        for exclusion in snapshot.exclusions
        if exclusion.symbol == symbol
    )


def test_clean_symbols_survive_the_filters() -> None:
    assert _build().included == (
        "000001.SZ",
        "000006.SZ",
        "300750.SZ",
        "600000.SH",
        "600519.SH",
        "900948.SH",
    )


def test_the_snapshot_is_immutable() -> None:
    snapshot = _build()

    with pytest.raises(ValueError):
        snapshot.included = ()  # type: ignore[misc]


# 排除规则六行：前四行断言完整规则元组（原 `==` 语义），后两行断言规则命中
# （原 `in` 语义），low_liquidity 行另带排除理由里的实测值片段。
# 行序与原用例一致，label 即原测试名；原 docstring 与断言旁的理由注释逐字保留。
EXCLUSION_RULE_CASES = (
    # test_st_is_excluded_with_a_reason
    ("test_st_is_excluded_with_a_reason", "000002.SZ", (UniverseRule.ST,), None, ()),
    # test_delisting_board_is_excluded_with_a_reason
    (
        "test_delisting_board_is_excluded_with_a_reason",
        "000003.SZ",
        (UniverseRule.DELISTING_BOARD,),
        None,
        (),
    ),
    # test_short_listing_age_is_excluded_with_a_reason:
    #   Listed 2026-08-01, so 34 days old against a 120-day rule.
    (
        "test_short_listing_age_is_excluded_with_a_reason",
        "000004.SZ",
        (UniverseRule.SHORT_LISTING,),
        None,
        (),
    ),
    # test_low_liquidity_is_excluded_with_the_measured_value
    #   原断言消息：排除理由要写清实际门槛值，而门槛来自配置
    (
        "test_low_liquidity_is_excluded_with_the_measured_value",
        LOW_LIQUIDITY_SYMBOL,
        (UniverseRule.LOW_LIQUIDITY,),
        None,
        ("5000000.0", str(float(_config().min_average_turnover_20d))),
    ),
    # test_a_symbol_with_no_bar_on_the_as_of_date_is_excluded
    (
        "test_a_symbol_with_no_bar_on_the_as_of_date_is_excluded",
        "000007.SZ",
        None,
        UniverseRule.NO_MARKET_DATA,
        (),
    ),
    # test_a_symbol_with_no_liquidity_measure_is_excluded
    (
        "test_a_symbol_with_no_liquidity_measure_is_excluded",
        "000007.SZ",
        None,
        UniverseRule.NO_LIQUIDITY_MEASURE,
        (),
    ),
)


def test_every_exclusion_records_the_rule_that_removed_it() -> None:
    """每个被排除的标的都要带上导致排除的规则；流动性一行还要写出实测值与门槛。"""
    snapshot = _build()
    details = {exclusion.symbol: exclusion.detail for exclusion in snapshot.exclusions}
    wrong = []
    for label, symbol, expected_rules, required_rule, fragments in EXCLUSION_RULE_CASES:
        rules = _rules(snapshot, symbol)
        if expected_rules is not None and rules != expected_rules:
            wrong.append(
                f"{label}: {symbol} 的排除规则为 {rules!r}，期望 {expected_rules!r}"
            )
        if required_rule is not None and required_rule not in rules:
            wrong.append(
                f"{label}: {symbol} 的排除规则 {rules!r} 未包含 {required_rule!r}"
            )
        detail = details.get(symbol, "")
        for fragment in fragments:
            if fragment not in detail:
                wrong.append(
                    f"{label}: {symbol} 的排除理由 {detail!r} 缺少 {fragment!r}"
                )
    assert not wrong, "排除规则未按标的记录:\n" + "\n".join(wrong)


def test_a_symbol_that_breaks_two_rules_records_both() -> None:
    """000007.SZ has neither a bar nor a measure; both are reported."""
    assert _rules(_build(), "000007.SZ") == (
        UniverseRule.NO_MARKET_DATA,
        UniverseRule.NO_LIQUIDITY_MEASURE,
    )


def test_long_suspension_is_deferred_and_excludes_nobody() -> None:
    """The rule is switched on but has no reviewed day count (D2)."""
    snapshot = _build()

    assert "000006.SZ" in snapshot.included
    assert UniverseRule.LONG_SUSPENSION not in {
        exclusion.rule for exclusion in snapshot.exclusions
    }
    assert [rule.rule for rule in snapshot.deferred_rules] == [
        UniverseRule.LONG_SUSPENSION
    ]
    assert "long_suspension_days" in snapshot.deferred_rules[0].reason


def test_a_reviewed_suspension_threshold_does_exclude() -> None:
    """Supplying the number turns the same rule on, with no code change."""
    config = _config().model_copy(update={"long_suspension_days": 60})

    snapshot = _build(config)

    assert _rules(snapshot, "000006.SZ") == (UniverseRule.LONG_SUSPENSION,)
    assert snapshot.deferred_rules == ()


def test_exchanges_outside_the_configuration_are_excluded() -> None:
    config = _config().model_copy(update={"exchanges": ("SSE",)})

    snapshot = _build(config)

    assert "830799.BJ" in [e.symbol for e in snapshot.exclusions]
    assert UniverseRule.EXCHANGE in _rules(snapshot, "830799.BJ")
    assert "600000.SH" in snapshot.included


def test_the_market_data_requirement_can_be_switched_off() -> None:
    config = _config().model_copy(update={"require_valid_market_data": False})

    assert "000007.SZ" in _build(config).included


def test_snapshot_id_is_stable_and_content_sensitive() -> None:
    snapshot = _build()
    same = _build()
    other = _build(_config().model_copy(update={"min_listing_days": 121}))

    assert snapshot.snapshot_id == same.snapshot_id
    assert snapshot.snapshot_id != other.snapshot_id
    assert snapshot.snapshot_id.startswith("2026-09-04:")


def test_lineage_carries_the_snapshot_id() -> None:
    snapshot = _build()

    assert snapshot.lineage.universe_snapshot == snapshot.snapshot_id


def test_exclusions_are_ordered_by_symbol_for_readable_diffs() -> None:
    symbols = [exclusion.symbol for exclusion in _build().exclusions]

    assert symbols == sorted(symbols)


def test_is_st_filtering_can_be_switched_off() -> None:
    config = _config().model_copy(update={"exclude_st": False})

    assert "000002.SZ" in _build(config).included


def test_bars_after_the_as_of_date_are_not_used_as_presence() -> None:
    """A bar dated tomorrow does not make a symbol tradeable today."""
    future = date(2026, 9, 7)
    bars = tuple(
        DailyBar(symbol=symbol, trade_date=future, close=10.0) for symbol in MEASURED
    )

    snapshot = UniverseBuilder(_config()).build(
        _profiles(),
        as_of=AS_OF,
        bars=bars,
        liquidity=_liquidity(),
    )

    assert UniverseRule.NO_MARKET_DATA in _rules(snapshot, "600000.SH")


def test_an_unknown_suspension_count_does_not_trip_the_rule() -> None:
    """A source that reports no suspension count must not be excluded by a
    value it never had. Setting `long_suspension_days` therefore requires a
    source that actually reports the count — recorded as a pending dependency
    in the slice ledger."""
    config = UniverseConfig(
        exchanges=("SSE", "SZSE", "BSE"),
        min_average_turnover_20d=20_000_000.0,
        min_listing_days=120,
        long_suspension_days=60,
    )
    profile = SecurityProfile(
        symbol="600000.SH",
        name="浦发银行",
        exchange="SSE",
        list_date=date(1999, 11, 10),
        suspended_trading_days=None,
    )
    liquidity = {
        "600000.SH": FactorResult(
            symbol="600000.SH",
            factor="avg_amount_20d",
            as_of=AS_OF,
            status=DataStatus.VALUE,
            factor_version="v1",
            lineage=SnapshotLineage(factor_version="v1"),
            raw_value=HEALTHY_LIQUIDITY_VALUE,
        )
    }

    snapshot = UniverseBuilder(config).build(
        (profile,),
        as_of=AS_OF,
        bars=(DailyBar(symbol="600000.SH", trade_date=AS_OF.date(), close=10.0),),
        liquidity=liquidity,
    )

    assert UniverseRule.LONG_SUSPENSION not in _rules(snapshot, "600000.SH")
    assert "600000.SH" in snapshot.included


def test_a_duplicated_instrument_is_excluded_rather_than_admitted_twice() -> None:
    """A listing that repeats an instrument must not duplicate a cross-section.

    The end-to-end scan crashed on exactly this before the rule existed: two
    profiles for one symbol produced two contexts, and cross-sectional scoring
    refuses a population with a repeated member. Excluding the duplicate keeps
    the scan running *and* keeps the reason visible.
    """
    profile = next(item for item in _profiles() if item.symbol == "600000.SH")

    snapshot = _build_with((profile, profile))

    assert snapshot.included == ("600000.SH",)
    assert _rules(snapshot, "600000.SH") == (UniverseRule.DUPLICATE_SECURITY,)


def _build_with(profiles: tuple[SecurityProfile, ...]) -> UniverseSnapshot:
    return UniverseBuilder(_config()).build(
        profiles,
        as_of=AS_OF,
        bars=(DailyBar(symbol="600000.SH", trade_date=AS_OF.date(), close=10.0),),
        liquidity={
            "600000.SH": FactorResult(
                symbol="600000.SH",
                factor="avg_amount_20d",
                as_of=AS_OF,
                status=DataStatus.VALUE,
                factor_version="v1",
                lineage=SnapshotLineage(factor_version="v1"),
                raw_value=HEALTHY_LIQUIDITY_VALUE,
            )
        },
    )


def test_a_non_trading_day_as_of_aligns_with_latest_effective_trade_date() -> None:
    """当 as_of 是休市日（当天全市场无 bar）时，对齐不晚于 as_of 的最新有效交易日。"""
    builder = UniverseBuilder(_config())
    saturday_as_of = datetime(2026, 9, 5, 15, 0, tzinfo=UTC)
    snapshot = builder.build(
        _profiles(),
        as_of=saturday_as_of,
        bars=_bars(),
        liquidity=_liquidity(),
    )
    assert "600000.SH" in snapshot.included
    assert UniverseRule.NO_MARKET_DATA not in _rules(snapshot, "600000.SH")
