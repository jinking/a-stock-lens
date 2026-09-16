"""CSV-to-canonical normalization for daily bars.

The normalizer converts types and nothing else. It never decides whether a
value is *acceptable* — that is the Data Quality Gate's job — so a negative
close passes through unchanged and is judged later, where the verdict is
visible.

Two absences stay distinct:

- an empty or placeholder cell is an absent value, and produces no record;
- text that cannot be read as a number is an absent value *and* a
  `ParseFailure` naming the row, the column, and the raw text.
"""

from collections.abc import Mapping
from datetime import date, datetime
from math import isfinite

from astock_lens.data.contracts import (
    NormalizedDataset,
    ParseFailure,
    RawDataset,
)
from astock_lens.domain.models import DailyBar

Row = tuple[str, ...]
ColumnIndex = dict[str, int]

NUMERIC_FIELDS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "volume",
    "amount",
    "turnover_rate",
    "pct_change",
    "adj_factor",
)

CANONICAL_FIELDS: tuple[str, ...] = ("symbol", "trade_date", *NUMERIC_FIELDS)

# Spelled-out absences seen in public datasets. Note that "nan" is here on
# purpose: `float("nan")` succeeds, and a NaN would poison every later average.
ABSENT_CELLS: frozenset[str] = frozenset(
    {"", "-", "--", "n/a", "na", "none", "null", "nan"}
)


def _to_float(cell: str) -> tuple[float | None, str | None]:
    """Return `(value, reason)`; `reason` is `None` when the cell was usable."""
    text = cell.strip()
    if text.lower() in ABSENT_CELLS:
        return None, None
    try:
        value = float(text)
    except ValueError:
        return None, f"not a number: {cell!r}"
    if not isfinite(value):
        return None, f"not a finite number: {cell!r}"
    return value, None


class CsvDailyBarNormalizer:
    """Map source-shaped rows onto the canonical `DailyBar`."""

    def __init__(self, *, column_map: Mapping[str, str] | None = None) -> None:
        """`column_map` maps a source column name onto a canonical field name."""
        mapping = dict(column_map or {})
        self._source_columns: dict[str, str] = {
            canonical: _reverse_lookup(mapping, canonical)
            for canonical in CANONICAL_FIELDS
        }

    def normalize(self, dataset: RawDataset, *, as_of: datetime) -> NormalizedDataset:
        """Convert one raw dataset, rejecting rows whose keys cannot be read."""
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError(
                "as_of must be timezone-aware so a point-in-time computation "
                "cannot hide behind an implicit offset"
            )

        if dataset.payload is None:
            return NormalizedDataset(dataset=dataset.dataset, as_of=as_of)

        index_of: ColumnIndex = {
            name: position for position, name in enumerate(dataset.payload.columns)
        }
        bars: list[DailyBar] = []
        failures: list[ParseFailure] = []

        for row_index, row in enumerate(dataset.payload.rows):
            symbol = self._cell(row, index_of, "symbol").strip()
            if not symbol:
                failures.append(
                    ParseFailure(
                        row_index=row_index,
                        column="symbol",
                        raw_value=self._cell(row, index_of, "symbol"),
                        reason="row has no symbol, so it cannot be keyed",
                    )
                )
                continue

            raw_date = self._cell(row, index_of, "trade_date")
            try:
                trade_date = date.fromisoformat(raw_date.strip())
            except ValueError:
                failures.append(
                    ParseFailure(
                        row_index=row_index,
                        column="trade_date",
                        raw_value=raw_date,
                        reason="trade_date is not an ISO date",
                    )
                )
                continue

            parsed: dict[str, float | None] = {}
            for field_name in NUMERIC_FIELDS:
                raw_value = self._cell(row, index_of, field_name)
                value, reason = _to_float(raw_value)
                parsed[field_name] = value
                if reason is not None:
                    failures.append(
                        ParseFailure(
                            row_index=row_index,
                            column=field_name,
                            raw_value=raw_value,
                            reason=reason,
                        )
                    )

            bars.append(
                DailyBar(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=parsed["open"],
                    high=parsed["high"],
                    low=parsed["low"],
                    close=parsed["close"],
                    pre_close=parsed["pre_close"],
                    volume=parsed["volume"],
                    amount=parsed["amount"],
                    turnover_rate=parsed["turnover_rate"],
                    pct_change=parsed["pct_change"],
                    adj_factor=parsed["adj_factor"],
                )
            )

        return NormalizedDataset(
            dataset=dataset.dataset,
            as_of=as_of,
            daily_bars=tuple(bars),
            parse_failures=tuple(failures),
        )

    def _cell(self, row: Row, index_of: ColumnIndex, canonical: str) -> str:
        """Return the source cell for a canonical field, or `""` when absent.

        A column the source does not provide is not a parse failure: the field
        is simply missing, and the gate is what reports a dataset with no
        usable values.
        """
        position = index_of.get(self._source_columns[canonical])
        if position is None or position >= len(row):
            return ""
        return row[position]


def _reverse_lookup(column_map: Mapping[str, str], canonical: str) -> str:
    """Find the source column that maps onto `canonical`, else `canonical`."""
    for source, target in column_map.items():
        if target == canonical:
            return source
    return canonical
