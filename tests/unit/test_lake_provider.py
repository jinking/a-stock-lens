"""数据湖日线 Provider：把本地 parquet 接成 `daily_bars` 与批量补缺来源。

这些测试不依赖真实的 `a-share-data-lake_v1`（几百 MB）：绝大多数用例在
`tmp_path` 里写一份合成 parquet，把契约钉死——列映射、单位、缺失即缺失、
状态三分（VALUE / NULL / SOURCE_ERROR）。最后一条集成测试只在真实湖存在时
跑，用它把 Provider 和线上数据对一次账（close、amount 与既往实测吻合）。
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.bootstrap_sources import BootstrapBatchRequest
from astock_lens.data.contracts import FetchRequest
from astock_lens.domain.enums import DataStatus

AS_OF = datetime(2026, 9, 22, 15, 0, tzinfo=UTC)

BAR_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
)

LAKE_ROOT = Path("/Users/huangjinjin/Documents/ChatGPT/a-share-data-lake_v1")
LAKE_DAILY = LAKE_ROOT / "data" / "bronze" / "daily_raw" / "daily_raw_all.parquet"


def _write_lake(tmp_path: Path) -> Path:
    """写一份最小可用的合成日线 parquet：列名、单位、code 格式都对齐真实湖。"""

    import pyarrow as pa
    import pyarrow.parquet as pq

    # volume 用「股」（与真实 iFinD 湖一致），amount 用「元」。
    rows = {
        "code": [
            "600519.SH",
            "600519.SH",
            "000001.SZ",
            "000001.SZ",
            "600519.SH",  # 2026-09-23：窗口内第二天
            "000001.SZ",
        ],
        "date": [
            "2026-09-22",
            "2026-09-21",
            "2026-09-22",
            "2026-09-21",
            "2026-09-23",
            "2026-09-23",
        ],
        "open": [1250.0, 1240.0, 11.0, 10.9, 1260.0, 11.2],
        "high": [1265.0, 1245.0, 11.3, 11.1, 1270.0, 11.5],
        "low": [1248.0, 1235.0, 10.8, 10.7, 1255.0, 11.0],
        "close": [1253.8, 1242.0, 11.1, 11.0, 1263.0, 11.3],
        "volume": [2457300.0, 2300000.0, 153023187.0, 150000000.0, 2500000.0, 1.6e8],
        "amount": [
            3088526148.0,
            2900000000.0,
            2571196000.0,
            2500000000.0,
            3100000000.0,
            2600000000.0,
        ],
    }
    table = pa.table(
        {
            "code": pa.array(rows["code"], type=pa.string()),
            "date": pa.array(rows["date"], type=pa.string()),
            "open": pa.array(rows["open"], type=pa.float64()),
            "high": pa.array(rows["high"], type=pa.float64()),
            "low": pa.array(rows["low"], type=pa.float64()),
            "close": pa.array(rows["close"], type=pa.float64()),
            "volume": pa.array(rows["volume"], type=pa.float64()),
            "amount": pa.array(rows["amount"], type=pa.float64()),
        }
    )
    path = tmp_path / "daily_raw_all.parquet"
    pq.write_table(table, path)
    return path


def _lake(path: Path):
    from astock_lens.data.providers.lake import LakeProvider

    return LakeProvider(path)


# --- health ---------------------------------------------------------------


def test_health_reports_absent_file_as_source_error(tmp_path: Path) -> None:
    health = _lake(tmp_path / "missing.parquet").health()

    assert health.healthy is False
    assert health.status is DataStatus.SOURCE_ERROR
    assert health.provider == "lake"


def test_health_reports_present_file_without_reading_it(tmp_path: Path) -> None:
    path = _write_lake(tmp_path)

    health = _lake(path).health()

    assert health.healthy is True
    assert health.status is DataStatus.VALUE


# --- single-day fetch (the drop-in `daily_bars` contract) -----------------


def test_fetch_maps_columns_preserves_units_and_leaves_turnover_absent(
    tmp_path: Path,
) -> None:
    result = _lake(_write_lake(tmp_path)).fetch(
        FetchRequest(
            dataset="daily_bars", as_of=AS_OF, symbols=("600519.SH", "000001.SZ")
        )
    )

    assert result.status is DataStatus.VALUE
    assert result.missing_symbols == ()
    assert result.trade_date == date(2026, 9, 22)
    assert result.payload is not None
    assert result.payload.columns == BAR_COLUMNS
    # 每一格都是字符串（Raw 保持源形状，换算交给归一层）。
    assert all(isinstance(cell, str) for row in result.payload.rows for cell in row)
    by_symbol = {row[0]: row for row in result.payload.rows}
    moutai = by_symbol["600519.SH"]
    assert moutai[1] == "2026-09-22"  # trade_date
    assert float(moutai[6]) == 2457300.0  # volume 原样是「股」，不 ÷100
    assert float(moutai[7]) == 3088526148.0  # amount 原样是「元」
    assert moutai[8] == ""  # 数据湖没有换手率 → 缺失，绝不填 0


def test_fetch_only_returns_the_requested_trade_date(tmp_path: Path) -> None:
    result = _lake(_write_lake(tmp_path)).fetch(
        FetchRequest(
            dataset="daily_bars",
            as_of=datetime(2026, 9, 23, 15, 0, tzinfo=UTC),
            symbols=("600519.SH",),
        )
    )

    assert result.payload is not None
    assert {row[1] for row in result.payload.rows} == {"2026-09-23"}


def test_fetch_names_symbols_the_lake_has_for_that_date(tmp_path: Path) -> None:
    # 300750.SZ 不在湖里 → 显式缺口，而不是被静默丢弃或补零。
    result = _lake(_write_lake(tmp_path)).fetch(
        FetchRequest(
            dataset="daily_bars",
            as_of=AS_OF,
            symbols=("600519.SH", "300750.SZ"),
        )
    )

    assert result.status is DataStatus.VALUE
    assert result.missing_symbols == ("300750.SZ",)
    assert result.payload is not None
    assert [row[0] for row in result.payload.rows] == ["600519.SH"]


def test_fetch_with_no_rows_for_date_is_null(tmp_path: Path) -> None:
    result = _lake(_write_lake(tmp_path)).fetch(
        FetchRequest(
            dataset="daily_bars",
            as_of=datetime(2026, 1, 5, 15, 0, tzinfo=UTC),
            symbols=("600519.SH",),
        )
    )

    assert result.status is DataStatus.NULL
    assert result.row_count == 0
    assert result.payload is None
    assert result.missing_symbols == ("600519.SH",)


def test_fetch_on_missing_file_is_source_error_not_empty(tmp_path: Path) -> None:
    result = _lake(tmp_path / "missing.parquet").fetch(
        FetchRequest(dataset="daily_bars", as_of=AS_OF, symbols=("600519.SH",))
    )

    assert result.status is DataStatus.SOURCE_ERROR
    assert result.row_count == 0
    assert result.payload is None
    assert result.missing_symbols == ("600519.SH",)
    assert result.message is not None


def test_fetch_rejects_unknown_dataset(tmp_path: Path) -> None:
    provider = _lake(_write_lake(tmp_path))

    with pytest.raises(ValueError, match="daily_bars"):
        provider.fetch(FetchRequest(dataset="securities", as_of=AS_OF, symbols=()))


def test_fetch_requires_explicit_symbols(tmp_path: Path) -> None:
    provider = _lake(_write_lake(tmp_path))

    with pytest.raises(ValueError, match="标的名单"):
        provider.fetch(FetchRequest(dataset="daily_bars", as_of=AS_OF, symbols=None))
    with pytest.raises(ValueError, match="标的名单"):
        provider.fetch(FetchRequest(dataset="daily_bars", as_of=AS_OF, symbols=()))


# --- batch source (unlocks the cold-start / research bootstrap) -----------


def test_fetch_recent_bars_returns_the_whole_window_grouped_by_symbol(
    tmp_path: Path,
) -> None:
    result = _lake(_write_lake(tmp_path)).fetch_recent_bars(
        BootstrapBatchRequest(
            symbols=("600519.SH", "000001.SZ"),
            start_date=date(2026, 9, 21),
            end_date=date(2026, 9, 23),
            as_of=AS_OF,
        )
    )

    assert result.source_name == "lake"
    assert result.missing_symbols == ()
    assert len(result.datasets) == 1
    dataset = result.datasets[0]
    assert dataset.status is DataStatus.VALUE
    assert dataset.payload is not None
    assert dataset.payload.columns == BAR_COLUMNS
    days = {row[0] for row in dataset.payload.rows}
    assert days == {"600519.SH", "000001.SZ"}
    # 窗口内每只标的都拿到 3 天（21/22/23）。
    counts: dict[str, int] = {}
    for row in dataset.payload.rows:
        counts[row[0]] = counts.get(row[0], 0) + 1
    assert counts == {"600519.SH": 3, "000001.SZ": 3}


def test_fetch_recent_bars_reports_missing_symbol_without_fabricating(
    tmp_path: Path,
) -> None:
    result = _lake(_write_lake(tmp_path)).fetch_recent_bars(
        BootstrapBatchRequest(
            symbols=("600519.SH", "300750.SZ"),
            start_date=date(2026, 9, 21),
            end_date=date(2026, 9, 23),
            as_of=AS_OF,
        )
    )

    assert result.missing_symbols == ("300750.SZ",)
    dataset = result.datasets[0]
    assert dataset.payload is not None
    assert {row[0] for row in dataset.payload.rows} == {"600519.SH"}


def test_fetch_recent_bars_with_nothing_to_land_is_not_value(tmp_path: Path) -> None:
    result = _lake(_write_lake(tmp_path)).fetch_recent_bars(
        BootstrapBatchRequest(
            symbols=("300750.SZ",),
            start_date=date(2026, 9, 21),
            end_date=date(2026, 9, 23),
            as_of=AS_OF,
        )
    )

    # 空结果绝不能伪装成 VALUE（BatchFetchResult 的校验器会拒绝空 VALUE）。
    assert result.missing_symbols == ("300750.SZ",)
    assert all(
        dataset.status is not DataStatus.VALUE
        or bool(dataset.payload and dataset.payload.rows)
        for dataset in result.datasets
    )


def test_fetch_recent_bars_on_missing_file_is_source_error(tmp_path: Path) -> None:
    result = _lake(tmp_path / "missing.parquet").fetch_recent_bars(
        BootstrapBatchRequest(
            symbols=("600519.SH",),
            start_date=date(2026, 9, 21),
            end_date=date(2026, 9, 23),
            as_of=AS_OF,
        )
    )

    assert result.missing_symbols == ("600519.SH",)
    assert all(dataset.status is DataStatus.SOURCE_ERROR for dataset in result.datasets)
    assert all(dataset.payload is None for dataset in result.datasets)


# --- CLI wiring -----------------------------------------------------------


def test_bulk_provider_selects_lake(monkeypatch: pytest.MonkeyPatch) -> None:
    from astock_lens.cli.runtime import _bulk_provider
    from astock_lens.data.providers.lake import LakeProvider

    monkeypatch.setenv("ASTOCK_LAKE_DAILY_PATH", str(LAKE_DAILY))
    monkeypatch.setenv("ASTOCK_BULK_PROVIDER", "lake")

    assert isinstance(_bulk_provider(), LakeProvider)


def test_lake_listing_still_routes_to_akshare(monkeypatch: pytest.MonkeyPatch) -> None:
    # 数据湖主档给不出 PIT 的 is_st / is_delisting_board，名单必须仍走 AkShare。
    from astock_lens.cli.runtime import _listing_provider
    from astock_lens.data.providers.akshare_provider import AkShareProvider
    from astock_lens.data.providers.lake import LakeProvider

    provider = LakeProvider(LAKE_DAILY)

    assert isinstance(_listing_provider(provider), AkShareProvider)


def test_lake_is_wired_as_the_bootstrap_batch_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from astock_lens.cli import runtime
    from astock_lens.data.providers.lake import LakeProvider

    monkeypatch.setenv("ASTOCK_LAKE_DAILY_PATH", str(LAKE_DAILY))
    lake = LakeProvider(LAKE_DAILY)

    assert runtime._batch_source(lake) is lake
    # westock / akshare 没有批量契约 → 诚实的 None（不发明、不退化成逐只假批量）。
    assert runtime._batch_source(object()) is None


# --- real-lake integration (skipped unless the data lake is present) ------


@pytest.mark.skipif(not LAKE_DAILY.is_file(), reason="真实数据湖不在本机")
def test_lake_matches_recorded_close_and_amount_on_a_known_day() -> None:
    result = _lake(LAKE_DAILY).fetch(
        FetchRequest(
            dataset="daily_bars",
            as_of=datetime(2024, 1, 2, 15, 0, tzinfo=UTC),
            symbols=("600519.SH",),
        )
    )

    assert result.status is DataStatus.VALUE
    assert result.payload is not None
    row = result.payload.rows[0]
    assert float(row[5]) == pytest.approx(1685.01)  # close
    assert float(row[7]) == pytest.approx(5440082548.0, rel=1e-6)  # amount 元
