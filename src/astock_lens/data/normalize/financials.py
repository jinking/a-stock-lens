"""Normalize WeStock financial statements into canonical observations.

The raw layer holds the CLI's table verbatim, in the source's own English
column names. This module is where those columns become the system's canonical
`FinancialObservation` records, and it is the only place that knows the
mapping — a source-column mapping is integration detail, not a threshold, so
it lives in code next to the provider that produced the columns (the same rule
`akshare_provider.BAR_COLUMN_MAP` follows).

Three rules from the design are enforced here rather than downstream:

1. `spec §5.1` — every observation carries `report_period`, `announce_date` and
   `available_at`. A row whose `InfoPublDate` cannot be read produces no
   observations at all, because `DATA_MODEL.md` §2 says such a record cannot
   enter a point-in-time factor.
2. `available_at <= as_of`. The publication date alone does not say *when* on
   that day the numbers existed, so availability is taken at the A-share close
   (`15:00 +08:00`) of the publication date: the conservative reading, and the
   same convention the CLI uses for a bare `--as-of` date. Rows published after
   the requested `as_of` are counted, not silently dropped.
3. No silent fallback. A cell the source left empty stays a missing *value*
   (`None`), and a cell that cannot be read produces a failure record naming
   the symbol, the metric and the raw text. Nothing becomes zero.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from astock_lens.data.contracts import RawDataset
from astock_lens.data.providers.westock import from_westock_code
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import DomainRecord, FinancialObservation

SHANGHAI = ZoneInfo("Asia/Shanghai")
A_SHARE_CLOSE_HOUR = 15

SYMBOL_COLUMN = "code"
REPORT_PERIOD_COLUMN = "EndDate"
ANNOUNCE_COLUMN = "InfoPublDate"

# Markers the source uses for "there is no value here". They are values of a
# kind — the statement has nothing for this cell — not parse failures.
MISSING_MARKERS: frozenset[str] = frozenset({"-", "--", "", "null", "nan", "none"})

# Columns that carry identity or timing rather than a measurement.
STRUCTURAL_COLUMNS: frozenset[str] = frozenset(
    {
        SYMBOL_COLUMN,
        REPORT_PERIOD_COLUMN,
        ANNOUNCE_COLUMN,
        "SecuCode",
        "_type",
        "EnterpriseType",
    }
)


@dataclass(frozen=True)
class FinancialMetric:
    """One canonical metric and the source column it comes from.

    `unit` is carried so a reader never has to guess whether `17.7179` is a
    ratio or a percentage: it is percent, and the source says so by column.
    """

    metric: str
    column: str
    unit: str


# The V1 metric set: the design's factor domains (quality, growth, valuation,
# dividend, cash flow) restricted to fields this source actually publishes.
# Percent-valued columns are marked `%`, multiples `x`, per-share amounts
# `CNY/share`, and amounts `CNY`.
FINANCIAL_METRICS: tuple[FinancialMetric, ...] = (
    # Income statement — scale and growth.
    FinancialMetric("revenue", "OperatingRevenue", "CNY"),
    FinancialMetric("revenue_ttm", "OperatingRevenueTTM", "CNY"),
    FinancialMetric("revenue_yoy", "OperatingRevenueGrowRate", "%"),
    FinancialMetric("revenue_cagr_3y", "ORComGrowRate3Y", "%"),
    FinancialMetric("operating_cost", "OperatingCost", "CNY"),
    FinancialMetric("gross_profit_ttm", "GrossProfitTTM", "CNY"),
    FinancialMetric("net_profit_parent", "NPParentCompanyOwners", "CNY"),
    FinancialMetric("net_profit_parent_ttm", "NPParentCompanyOwnersTTM", "CNY"),
    FinancialMetric("net_profit_parent_yoy", "NPParentCompanyYOY", "%"),
    FinancialMetric("net_profit_parent_cagr_3y", "NPPCCGrowRate3Y", "%"),
    FinancialMetric("total_profit", "TotalProfit", "CNY"),
    FinancialMetric("ebit", "EBIT", "CNY"),
    # Income statement — quality and per-share figures.
    FinancialMetric("gross_margin", "GrossIncomeRatio", "%"),
    FinancialMetric("net_margin", "NetProfitRatio", "%"),
    FinancialMetric("roe", "ROE", "%"),
    FinancialMetric("roe_ttm", "ROETTM", "%"),
    FinancialMetric("roe_weighted", "ROEWeighted", "%"),
    FinancialMetric("roa", "ROA", "%"),
    FinancialMetric("roic", "ROIC", "%"),
    FinancialMetric("r_and_d", "RAndD", "CNY"),
    FinancialMetric("eps", "EPS", "CNY/share"),
    FinancialMetric("eps_ttm", "EPSTTM", "CNY/share"),
    FinancialMetric("dividend_per_share", "DividendPS", "CNY/share"),
    FinancialMetric("dividend_ttm", "DividendTTM", "CNY"),
    # Balance sheet — leverage, liquidity and capital.
    FinancialMetric("total_equity", "TotalShareholderEquity", "CNY"),
    FinancialMetric("total_liabilities", "TotalLiability", "CNY"),
    FinancialMetric("total_current_assets", "TotalCurrentAssets", "CNY"),
    FinancialMetric("total_current_liabilities", "TotalCurrentLiability", "CNY"),
    FinancialMetric("debt_to_asset", "DebtAssetsRatio", "%"),
    FinancialMetric("debt_to_equity", "DebtEquityRatio", "%"),
    FinancialMetric("equity_multiplier", "EquityMultipler", "x"),
    FinancialMetric("current_ratio", "CurrentRatio", "x"),
    FinancialMetric("quick_ratio", "QuickRatio", "x"),
    FinancialMetric("working_capital", "WorkingCapital", "CNY"),
    FinancialMetric("cash_and_equivalents", "CashEquivalents", "CNY"),
    FinancialMetric("interest_bearing_debt", "InterestBearDebt", "CNY"),
    FinancialMetric("inventories", "Inventories", "CNY"),
    FinancialMetric("goodwill", "GoodWill", "CNY"),
    FinancialMetric("net_asset_per_share", "NAPS", "CNY/share"),
    # Cash flow — conversion and coverage.
    FinancialMetric("net_operating_cashflow", "NetOperateCashFlow", "CNY"),
    FinancialMetric("net_operating_cashflow_ttm", "NetOperateCashFlowTTM", "CNY"),
    FinancialMetric("net_operating_cashflow_yoy", "NetOperateCashFlowYOY", "%"),
    FinancialMetric("cash_from_sales", "GoodsSaleServiceRenderCash", "CNY"),
    FinancialMetric("net_investing_cashflow", "NetInvestCashFlow", "CNY"),
    FinancialMetric("net_financing_cashflow", "NetFinanceCashFlow", "CNY"),
    FinancialMetric("fcff", "FCFF", "CNY"),
    FinancialMetric("fcfe", "FCFE", "CNY"),
    FinancialMetric("operating_cashflow_per_share", "OperCashFlowPS", "CNY/share"),
)

METRIC_BY_COLUMN: Mapping[str, FinancialMetric] = {
    item.column: item for item in FINANCIAL_METRICS
}


class FinancialNormalizeFailure(DomainRecord):
    """One cell or row this normalizer could not turn into an observation.

    Cell-level failures carry the metric; row-level failures leave it `None`
    and explain what was wrong with the row itself (an unreadable report period
    or publication date).
    """

    column: str
    raw_value: str
    reason: str
    symbol: str | None = None
    metric: str | None = None
    report_period: date | None = None


class FinancialNormalizeOutcome(DomainRecord):
    """What one statement's normalization produced."""

    dataset: str
    as_of: datetime
    source_status: DataStatus
    observations: tuple[FinancialObservation, ...] = ()
    absent_columns: tuple[str, ...] = ()
    failures: tuple[FinancialNormalizeFailure, ...] = ()
    not_yet_available: int = 0


class FinancialStatementNormalizer:
    """Convert one raw WeStock statement table into canonical observations."""

    def __init__(self, source: str = "westock-cli") -> None:
        self._source = source

    def normalize(
        self, dataset: RawDataset, *, as_of: datetime
    ) -> FinancialNormalizeOutcome:
        """Read one statement, keeping every gap visible."""
        payload = dataset.payload
        if payload is None or not payload.rows:
            # The raw status already says why there is nothing; repeating it as
            # observations would invent data, and dropping it would hide it.
            return FinancialNormalizeOutcome(
                dataset=dataset.dataset,
                as_of=as_of,
                source_status=dataset.status,
            )

        columns = payload.columns
        absent = tuple(
            metric.column
            for metric in FINANCIAL_METRICS
            if metric.column not in columns
        )
        positions = {column: index for index, column in enumerate(columns)}

        observations: list[FinancialObservation] = []
        failures: list[FinancialNormalizeFailure] = []
        not_yet_available = 0

        for row_index, row in enumerate(payload.rows):
            symbol = self._symbol(row, positions, row_index, failures)
            if symbol is None:
                continue
            report_period = self._date(
                row, positions, REPORT_PERIOD_COLUMN, row_index, failures, symbol
            )
            announce_date = self._date(
                row, positions, ANNOUNCE_COLUMN, row_index, failures, symbol
            )
            if report_period is None or announce_date is None:
                continue

            available_at = datetime(
                announce_date.year,
                announce_date.month,
                announce_date.day,
                A_SHARE_CLOSE_HOUR,
                tzinfo=SHANGHAI,
            )
            if available_at > as_of:
                not_yet_available += 1
                continue

            for metric in FINANCIAL_METRICS:
                index = positions.get(metric.column)
                if index is None:
                    continue
                observations.append(
                    FinancialObservation(
                        symbol=symbol,
                        metric=metric.metric,
                        report_period=report_period,
                        announce_date=announce_date,
                        available_at=available_at,
                        as_of=as_of,
                        source=self._source,
                        value=_value(
                            row[index], failures, symbol, metric, report_period
                        ),
                        unit=metric.unit,
                    )
                )

        return FinancialNormalizeOutcome(
            dataset=dataset.dataset,
            as_of=as_of,
            source_status=dataset.status,
            observations=tuple(observations),
            absent_columns=absent,
            failures=tuple(failures),
            not_yet_available=not_yet_available,
        )

    def _symbol(
        self,
        row: tuple[str, ...],
        positions: Mapping[str, int],
        row_index: int,
        failures: list[FinancialNormalizeFailure],
    ) -> str | None:
        index = positions.get(SYMBOL_COLUMN)
        raw = row[index] if index is not None and index < len(row) else ""
        if not raw:
            failures.append(
                FinancialNormalizeFailure(
                    column=SYMBOL_COLUMN,
                    raw_value=raw,
                    reason=f"row {row_index} carries no instrument code",
                )
            )
            return None
        try:
            return from_westock_code(raw)
        except ValueError as error:
            failures.append(
                FinancialNormalizeFailure(
                    column=SYMBOL_COLUMN,
                    raw_value=raw,
                    reason=str(error),
                )
            )
            return None

    @staticmethod
    def _date(
        row: tuple[str, ...],
        positions: Mapping[str, int],
        column: str,
        row_index: int,
        failures: list[FinancialNormalizeFailure],
        symbol: str,
    ) -> date | None:
        index = positions.get(column)
        if index is None or index >= len(row):
            failures.append(
                FinancialNormalizeFailure(
                    column=column,
                    raw_value="",
                    reason=(
                        f"row {row_index} has no {column} column, so this record "
                        "cannot be placed in time"
                    ),
                    symbol=symbol,
                )
            )
            return None
        raw = row[index]
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            failures.append(
                FinancialNormalizeFailure(
                    column=column,
                    raw_value=raw,
                    reason=(
                        f"row {row_index} carries an unreadable {column}; without "
                        "it the record cannot enter a point-in-time factor"
                    ),
                    symbol=symbol,
                )
            )
            return None


def _value(
    cell: str,
    failures: list[FinancialNormalizeFailure],
    symbol: str,
    metric: FinancialMetric,
    report_period: date,
) -> float | None:
    """Read one measurement, never turning a gap into a number."""
    text = cell.strip()
    if text.lower() in MISSING_MARKERS:
        return None
    try:
        return float(text)
    except ValueError:
        failures.append(
            FinancialNormalizeFailure(
                column=metric.column,
                raw_value=text,
                reason=f"{text!r} is not a number",
                symbol=symbol,
                metric=metric.metric,
                report_period=report_period,
            )
        )
        return None
