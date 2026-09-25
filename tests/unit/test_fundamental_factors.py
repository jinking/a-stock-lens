"""Fundamental factor tests.

The rule these tests exist for is the one that distinguishes a fundamental
factor from any other: its value depends on *when* it is asked. A factor must
use the newest report already published at `as_of`, and a report the market had
not received yet must be invisible to it — including when that report is the
one that would look best.

The second half of the file pins the missing-evidence vocabulary: a line the
instrument never reports (`NOT_APPLICABLE`) is not the same fact as a line it
reports without a value (`NULL`), which is not the same as a value too old for
a reviewed freshness bound (`STALE`), which is not the same as a divisor of
zero (`INVALID`). None of them becomes a number.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import NormalizedDataset
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import FinancialObservation
from astock_lens.factors.builtin import build_factor
from astock_lens.factors.config import FactorConfig, load_factor_config
from astock_lens.factors.contracts import FactorContext
from astock_lens.factors.fundamental import RATIO_DEFINITIONS

ROOT = Path(__file__).resolve().parents[2]
FACTOR_CONFIG_DIR = ROOT / "configs" / "factors"

AS_OF = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)
SYMBOL = "600519.SH"


def _config(name: str, **overrides: object) -> FactorConfig:
    definition = RATIO_DEFINITIONS.get(name)
    payload: dict[str, object] = {
        "name": name,
        "domain": "QUALITY",
        "description": name,
        "inputs": [definition.numerator, definition.denominator] if definition else [],
        "frequency": "QUARTERLY",
        "direction": "DESCRIBES_THE_MEASUREMENT",
        "null_policy": "NULL_UNLESS_BOTH_INPUTS_HAVE_A_PUBLISHED_VALUE",
        "version": "v1",
        "params": {"stale_after_days": None},
    }
    payload.update(overrides)
    return FactorConfig.model_validate(payload)


def _observation(
    metric: str,
    value: float | None,
    *,
    report_period: date = date(2026, 6, 30),
    announce_date: date = date(2026, 8, 15),
    symbol: str = SYMBOL,
) -> FinancialObservation:
    return FinancialObservation(
        symbol=symbol,
        metric=metric,
        report_period=report_period,
        announce_date=announce_date,
        available_at=datetime(
            announce_date.year,
            announce_date.month,
            announce_date.day,
            15,
            tzinfo=UTC,
        ),
        as_of=AS_OF,
        source="westock-cli",
        value=value,
        unit="CNY",
    )


def _context(
    observations: tuple[FinancialObservation, ...],
    *,
    as_of: datetime = AS_OF,
    symbol: str = SYMBOL,
) -> FactorContext:
    return FactorContext(
        symbol=symbol,
        as_of=as_of,
        dataset=NormalizedDataset(
            dataset="financials", as_of=as_of, observations=observations
        ),
    )


def test_a_ratio_is_computed_from_the_newest_published_period() -> None:
    factor = build_factor(_config("ocf_to_net_profit"))
    context = _context(
        (
            _observation("net_operating_cashflow_ttm", 120.0),
            _observation("net_profit_parent_ttm", 100.0),
        )
    )

    result = factor.compute(context)

    assert result.status is DataStatus.VALUE
    assert result.raw_value == pytest.approx(1.2)
    assert result.factor == "ocf_to_net_profit"
    assert result.factor_version == "v1"
    assert {item.metric for item in result.inputs} == {
        "net_operating_cashflow_ttm",
        "net_profit_parent_ttm",
    }
    assert {item.report_period for item in result.inputs} == {date(2026, 6, 30)}
    assert {item.announce_date for item in result.inputs} == {date(2026, 8, 15)}
    # 证据必须带上它真正可用的时刻，而不是被计算时刻顶替：快照要能**独立**
    # 证明自己没有前视，所以可用时间不能只存在于计算过程里。
    assert {item.available_at for item in result.inputs} == {
        datetime(2026, 8, 15, 15, tzinfo=UTC)
    }


def test_the_availability_time_is_the_observation_not_the_scan() -> None:
    """`available_at` 不是 `as_of` 的复制品——那等于自己给自己发前视许可。"""
    factor = build_factor(_config("ocf_to_net_profit"))
    context = _context(
        (
            _observation("net_operating_cashflow_ttm", 120.0),
            _observation("net_profit_parent_ttm", 100.0),
        )
    )

    result = factor.compute(context)

    assert all(item.available_at != context.as_of for item in result.inputs)
    assert all(item.available_at is not None for item in result.inputs)
    assert all(item.available_at <= context.as_of for item in result.inputs)


def test_a_report_published_after_the_scan_is_invisible() -> None:
    """The look-ahead test: the newest report must not be visible early."""
    factor = build_factor(_config("ocf_to_net_profit"))
    observations = (
        _observation(
            "net_operating_cashflow_ttm",
            120.0,
            report_period=date(2026, 3, 31),
            announce_date=date(2026, 4, 25),
        ),
        _observation(
            "net_profit_parent_ttm",
            100.0,
            report_period=date(2026, 3, 31),
            announce_date=date(2026, 4, 25),
        ),
        # The H1 report, announced after the scan's point in time.
        _observation(
            "net_operating_cashflow_ttm",
            999.0,
            report_period=date(2026, 6, 30),
            announce_date=date(2026, 8, 15),
        ),
        _observation(
            "net_profit_parent_ttm",
            1.0,
            report_period=date(2026, 6, 30),
            announce_date=date(2026, 8, 15),
        ),
    )
    early = datetime(2026, 6, 1, 15, 0, tzinfo=UTC)

    result = factor.compute(_context(observations, as_of=early))

    assert result.status is DataStatus.VALUE
    assert result.raw_value == pytest.approx(1.2)
    assert {item.report_period for item in result.inputs} == {date(2026, 3, 31)}


def test_the_newest_period_wins_once_it_is_published() -> None:
    factor = build_factor(_config("ocf_to_net_profit"))
    observations = (
        _observation(
            "net_operating_cashflow_ttm",
            120.0,
            report_period=date(2026, 3, 31),
            announce_date=date(2026, 4, 25),
        ),
        _observation(
            "net_profit_parent_ttm",
            100.0,
            report_period=date(2026, 3, 31),
            announce_date=date(2026, 4, 25),
        ),
        _observation("net_operating_cashflow_ttm", 45.0),
        _observation("net_profit_parent_ttm", 90.0),
    )

    result = factor.compute(_context(observations))

    assert result.raw_value == pytest.approx(0.5)
    assert {item.report_period for item in result.inputs} == {date(2026, 6, 30)}


def test_a_line_the_statement_does_not_carry_is_not_applicable() -> None:
    factor = build_factor(_config("goodwill_to_equity"))
    context = _context((_observation("total_equity", 100.0),))

    result = factor.compute(context)

    assert result.status is DataStatus.NOT_APPLICABLE
    assert result.raw_value is None


def test_a_line_that_exists_without_a_value_is_null() -> None:
    factor = build_factor(_config("goodwill_to_equity"))
    context = _context(
        (_observation("goodwill", None), _observation("total_equity", 100.0))
    )

    result = factor.compute(context)

    assert result.status is DataStatus.NULL
    assert result.raw_value is None
    # The reference still names the period, so a reader can see which report
    # was short of the value.
    assert {item.report_period for item in result.inputs if item.report_period} == {
        date(2026, 6, 30)
    }


def test_a_newer_period_without_a_value_keeps_the_last_known_one() -> None:
    """报表不是每期都发布每个字段，最新一期为空不该丢掉已知的测量。

    实测：源站只在年报发布 `DividendPaidRatio`，半年报该格为空。若"最新一期为空 → NULL"，
    分红策略可评分标的会从 3,689 掉到 734。这里改为取最近的非空观测，并在 `inputs` 里
    如实写明它属于哪一期；是否太旧由 `STALE` 与新鲜度上限决定。
    """
    factor = build_factor(_config("dividend_payout_ttm"))
    observations = (
        # 年报口径：有值
        _observation(
            "dividend_ttm",
            100.0,
            report_period=date(2025, 12, 31),
            announce_date=date(2026, 4, 17),
        ),
        _observation(
            "net_profit_parent_ttm",
            200.0,
            report_period=date(2025, 12, 31),
            announce_date=date(2026, 4, 17),
        ),
        # 半年报：该字段为空
        _observation("dividend_ttm", None),
        _observation("net_profit_parent_ttm", 250.0),
    )

    result = factor.compute(_context(observations))

    assert result.status is DataStatus.VALUE
    # 分子分母各自回退到各自最近一次带值的观测：分子 100（年报），分母 250（半年报），
    # 因此是 0.4。混用期次本身是事实，`inputs` 会把两个期次都写出来供人核对。
    assert result.raw_value == pytest.approx(0.4)
    periods = {item.report_period for item in result.inputs}
    assert date(2026, 6, 30) in periods  # 分母用了最新一期
    assert date(2025, 12, 31) in periods  # 分子回退到最近一次带值的那期


def test_a_reported_line_that_is_not_yet_available_is_null_not_not_applicable() -> None:
    """The instrument reports the line; this point in time simply cannot see it."""
    factor = build_factor(_config("goodwill_to_equity"))
    observations = (
        _observation("total_equity", 100.0),
        _observation("goodwill", 5.0),  # announced 2026-08-15
    )
    early = datetime(2026, 5, 1, 15, 0, tzinfo=UTC)

    result = factor.compute(_context(observations, as_of=early))

    assert result.status is DataStatus.NULL


def test_not_applicable_outranks_null() -> None:
    factor = build_factor(_config("goodwill_to_equity"))
    context = _context((_observation("total_equity", None),))

    assert factor.compute(context).status is DataStatus.NOT_APPLICABLE


def test_a_non_positive_divisor_is_not_applicable() -> None:
    """分母非正时比值不存在：不是"很低"，也不是无穷大。

    负现金流、负净资产、亏损都会走到这里。原来的实现把它判成 `INVALID`，
    但那个值本身是合法的（公司确实亏损），不适用的是"这个比值"。
    """
    factor = build_factor(_config("goodwill_to_equity"))
    context = _context(
        (_observation("goodwill", 5.0), _observation("total_equity", 0.0))
    )

    result = factor.compute(context)

    assert result.status is DataStatus.NOT_APPLICABLE
    assert result.raw_value is None

    negative = factor.compute(
        _context((_observation("goodwill", 5.0), _observation("total_equity", -1.0)))
    )
    assert negative.status is DataStatus.NOT_APPLICABLE


def test_a_reviewed_freshness_bound_switches_stale_on() -> None:
    """The mechanism is ready; the number is the configuration's business."""
    factor = build_factor(
        _config("ocf_to_net_profit", params={"stale_after_days": 120})
    )
    observations = (
        _observation(
            "net_operating_cashflow_ttm",
            120.0,
            report_period=date(2025, 3, 31),
            announce_date=date(2025, 4, 25),
        ),
        _observation(
            "net_profit_parent_ttm",
            100.0,
            report_period=date(2025, 3, 31),
            announce_date=date(2025, 4, 25),
        ),
    )

    result = factor.compute(_context(observations))

    assert result.status is DataStatus.STALE
    assert result.raw_value is None


def test_without_a_reviewed_bound_a_old_report_is_still_a_value() -> None:
    factor = build_factor(_config("ocf_to_net_profit"))
    observations = (
        _observation(
            "net_operating_cashflow_ttm",
            120.0,
            report_period=date(2025, 3, 31),
            announce_date=date(2025, 4, 25),
        ),
        _observation(
            "net_profit_parent_ttm",
            100.0,
            report_period=date(2025, 3, 31),
            announce_date=date(2025, 4, 25),
        ),
    )

    assert factor.compute(_context(observations)).status is DataStatus.VALUE


def test_the_configuration_must_state_the_freshness_key() -> None:
    with pytest.raises(ValueError, match="stale_after_days"):
        build_factor(_config("ocf_to_net_profit", params={}))


def test_the_configuration_must_declare_the_inputs_the_code_uses() -> None:
    with pytest.raises(ValueError, match="must declare inputs"):
        build_factor(_config("ocf_to_net_profit", inputs=["revenue", "net_profit"]))


def test_a_ratio_that_is_not_implemented_is_refused() -> None:
    from astock_lens.factors.fundamental import FundamentalRatioFactor

    with pytest.raises(ValueError, match="not a fundamental ratio factor"):
        FundamentalRatioFactor(
            FactorConfig.model_validate(
                {
                    "name": "made_up_ratio",
                    "domain": "QUALITY",
                    "description": "x",
                    "inputs": ["a", "b"],
                    "frequency": "QUARTERLY",
                    "direction": "d",
                    "null_policy": "p",
                    "version": "v1",
                    "params": {"stale_after_days": None},
                }
            )
        )


def test_every_configured_fundamental_factor_has_an_implementation() -> None:
    """A config nobody implemented would leave every symbol ineligible."""
    names = {
        load_factor_config(path).name
        for path in sorted(FACTOR_CONFIG_DIR.glob("*.yaml"))
    }

    for name in sorted(RATIO_DEFINITIONS):
        assert name in names, name
        factor = build_factor(load_factor_config(FACTOR_CONFIG_DIR / f"{name}.yaml"))
        assert factor.metadata.name == name
        assert factor.metadata.inputs == (
            RATIO_DEFINITIONS[name].numerator,
            RATIO_DEFINITIONS[name].denominator,
        )
