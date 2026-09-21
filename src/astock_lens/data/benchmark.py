"""基准指数日线只读加载契约（任务 3）。

严格遵循无静默兜底、fail-closed 和第一性原理：
- 不依赖 pandas/polars 等重型库，使用标准库 csv 模块流式解析；
- 严格校验必填列与数值合法性，缺失列或畸形行直接阻断抛出异常；
- 严格进行非基准代码过滤（wrong-symbol exclusion）与未来行过滤（future-row exclusion）；
- 按 trade_date 升序排列返回不可变 DailyBar 元组。
"""

import csv
import math
import os
from datetime import date, datetime
from pathlib import Path

from astock_lens.domain.models import DailyBar

BENCHMARK_BARS_ENV = "ASTOCK_BENCHMARK_BARS_PATH"
DEFAULT_BENCHMARK_BARS_PATH = Path("data/raw/benchmark_bars.csv")

EXPECTED_COLUMNS: tuple[str, ...] = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
)

NUMERIC_COLUMNS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
)


def resolve_benchmark_bars_path(env_var: str = BENCHMARK_BARS_ENV) -> Path:
    """解析基准指数日线文件路径，优先使用环境变量覆盖。"""
    value = os.environ.get(env_var)
    if value:
        return Path(value)
    return DEFAULT_BENCHMARK_BARS_PATH


def read_benchmark_bars(
    *,
    path: Path,
    benchmark_id: str,
    as_of: datetime,
) -> tuple[DailyBar, ...]:
    """只读加载基准指数日线数据。

    Args:
        path: 基准日线 CSV 路径
        benchmark_id: 期望的基准代码（如 '000985.CSI'）
        as_of: 截止时间戳（必须带时区）

    Returns:
        按 trade_date 升序排列的 DailyBar 元组

    Raises:
        ValueError: as_of 无时区、CSV 表头缺少必须列或数据行格式畸形
        FileNotFoundError: 数据文件不存在
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    if not path.is_file():
        raise FileNotFoundError(f"Benchmark bars file not found: {path}")

    cutoff_date = as_of.date()

    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"Benchmark bars CSV file is empty: {path}")

        missing_columns = [
            col for col in EXPECTED_COLUMNS if col not in reader.fieldnames
        ]
        if missing_columns:
            raise ValueError(
                f"Benchmark bars CSV {path} is missing required columns: {missing_columns}. "
                f"Expected columns: {EXPECTED_COLUMNS}"
            )

        bars: list[DailyBar] = []
        for line_no, row in enumerate(reader, start=2):
            if any(k is None for k in row) or any(
                v is None for col, v in row.items() if col in EXPECTED_COLUMNS
            ):
                raise ValueError(
                    f"Malformed row at line {line_no} in {path}: unexpected field count"
                )

            raw_symbol = row["symbol"]
            if raw_symbol is None:
                raise ValueError(f"Missing symbol at line {line_no} in {path}")
            symbol = raw_symbol.strip()
            if not symbol:
                raise ValueError(f"Empty symbol at line {line_no} in {path}")

            # 排除非目标基准代码行（wrong-symbol exclusion）
            if symbol != benchmark_id:
                continue

            raw_date = row["trade_date"]
            if raw_date is None:
                raise ValueError(f"Missing trade_date at line {line_no} in {path}")
            raw_date_str = raw_date.strip()
            try:
                trade_date = date.fromisoformat(raw_date_str)
            except ValueError as exc:
                raise ValueError(
                    f"Malformed trade_date {raw_date_str!r} at line {line_no} in {path}"
                ) from exc

            # 排除未来时间行（future-row exclusion）
            if trade_date > cutoff_date:
                continue

            numeric_values: dict[str, float | None] = {}
            for col in NUMERIC_COLUMNS:
                raw_num = row[col]
                if raw_num is None or raw_num.strip() == "":
                    numeric_values[col] = None
                    continue
                trimmed = raw_num.strip()
                try:
                    val = float(trimmed)
                except ValueError as exc:
                    raise ValueError(
                        f"Malformed numeric column {col!r} with value {raw_num!r} at line {line_no} in {path}"
                    ) from exc
                if not math.isfinite(val):
                    raise ValueError(
                        f"Non-finite numeric column {col!r} with value {raw_num!r} at line {line_no} in {path}"
                    )
                numeric_values[col] = val

            bars.append(
                DailyBar(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=numeric_values["open"],
                    high=numeric_values["high"],
                    low=numeric_values["low"],
                    close=numeric_values["close"],
                    volume=numeric_values["volume"],
                    amount=numeric_values["amount"],
                )
            )

    bars.sort(key=lambda b: b.trade_date)
    return tuple(bars)
