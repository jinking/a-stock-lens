"""估值归一化测试（回放 neodata 的真实响应）。

估值与财务的时点语义不同，所以这里钉住的是估值特有的事情：

- 逐日时序表里的指标**带估值日期**，可以直接做 point-in-time 选值；
- 键值头的"最新 PE/PB/分位"没有日期，日期取自时序表最新一天；
  没有时序表时（板块查询）以查询日为日期，并计数为 `dated_from_query`；
- `--` / `暂无数据` 是"没有值"，不是 0；
- 分类标签（"低于"）进 `text_value`，只作证据、不进排名。
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.data.normalize.valuations import (
    ALL_METRICS,
    NeodataValuationNormalizer,
)
from astock_lens.data.providers.neodata import PAYLOAD_COLUMNS
from astock_lens.domain.enums import DataStatus

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "neodata"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


def _raw(dataset: str) -> RawDataset:
    """把录制响应里 apiRecall 的内容块还原成 Provider 落地时的形状。"""
    payload = json.loads((FIXTURES / f"{dataset}.json").read_text(encoding="utf-8"))
    blocks = payload["data"]["apiData"]["apiRecall"]
    rows = tuple(
        (str(b.get("type") or ""), str(b.get("desc") or ""), str(b.get("content") or ""))
        for b in blocks
    )
    return RawDataset(
        provider="neodata",
        dataset=dataset,
        fetched_at=AS_OF,
        provider_version="v1",
        status=DataStatus.VALUE,
        row_count=len(rows),
        payload=RawPayload(columns=PAYLOAD_COLUMNS, rows=rows),
    )


def test_the_daily_series_becomes_dated_observations() -> None:
    outcome = NeodataValuationNormalizer().normalize(_raw("valuation"), as_of=AS_OF)
    series = [item for item in outcome.observations if item.metric == "peg"]

    assert series
    assert all(item.valuation_date == date(2026, 9, 16) for item in series[:1])
    sample = series[0]
    assert sample.symbol == "000568.SZ"
    assert sample.value == pytest.approx(-99.2619)
    assert sample.unit == "x"
    assert sample.available_at.tzinfo is not None


def test_the_header_metrics_borrow_the_newest_series_date() -> None:
    """键值头只有"最新"，日期取时序表最新一天——这样它也能参与时点选值。"""
    outcome = NeodataValuationNormalizer().normalize(_raw("valuation"), as_of=AS_OF)
    header = {
        item.metric: item
        for item in outcome.observations
        if item.metric in {"pe_ttm", "pb", "pe_percentile", "pb_percentile"}
    }

    assert header["pe_ttm"].value == pytest.approx(14.19)
    assert header["pb"].value == pytest.approx(2.33)
    assert header["pe_percentile"].unit == "%"
    assert {item.valuation_date for item in header.values()} == {date(2026, 9, 16)}
    assert outcome.dated_from_query == 0


def test_a_categorical_label_is_evidence_not_a_number() -> None:
    outcome = NeodataValuationNormalizer().normalize(_raw("valuation"), as_of=AS_OF)
    label = next(
        item
        for item in outcome.observations
        if item.metric == "industry_relative_label"
    )

    assert label.text_value == "低于"
    assert label.value is None


def test_missing_markers_never_become_zero() -> None:
    """时序表里大量 `--`，它们必须是"没有值"。"""
    outcome = NeodataValuationNormalizer().normalize(_raw("valuation"), as_of=AS_OF)
    static_pe = [
        item for item in outcome.observations if item.metric == "pe_static"
    ]

    # `静态市盈率（倍）` 这一列在录制响应里全部是 `--`，因此不产生任何指标，
    # 而不是产生一堆 0（该列没有映射到指标，因此这里断言它确实没出现）。
    assert static_pe == []
    absent_values = [
        item
        for item in outcome.observations
        if item.value is None and item.metric != "industry_relative_label"
    ]
    assert all(item.text_value is None for item in absent_values)


def test_every_metric_declares_a_unit_or_is_a_label() -> None:
    """单位必须齐备，指标名必须唯一：没有单位的值不可解释。"""
    assert all(item.unit for item in ALL_METRICS)
    assert len({item.metric for item in ALL_METRICS}) == len(ALL_METRICS)


def test_a_sector_block_without_a_series_is_dated_at_the_query_day() -> None:
    """板块估值没有逐日表，服务端给的是"最新"，因此以查询日为日期并计数。"""
    outcome = NeodataValuationNormalizer().normalize(_raw("industry"), as_of=AS_OF)

    assert outcome.observations
    assert outcome.dated_from_query > 0
    assert all(
        item.valuation_date == AS_OF.date() for item in outcome.observations
    )
    sector = outcome.observations[0]
    assert sector.symbol == "01801125.PT"
    assert sector.metric in {"pe_ttm", "pb"}


def test_an_empty_source_reports_its_status_instead_of_inventing_rows() -> None:
    raw = RawDataset(
        provider="neodata",
        dataset="valuation",
        fetched_at=AS_OF,
        provider_version="v1",
        status=DataStatus.NULL,
        row_count=0,
    )

    outcome = NeodataValuationNormalizer().normalize(raw, as_of=AS_OF)

    assert outcome.source_status is DataStatus.NULL
    assert outcome.observations == ()
    assert outcome.failures == ()


def test_a_block_without_an_instrument_is_reported_not_guessed() -> None:
    raw = RawDataset(
        provider="neodata",
        dataset="valuation",
        fetched_at=AS_OF,
        provider_version="v1",
        status=DataStatus.VALUE,
        row_count=1,
        payload=RawPayload(
            columns=PAYLOAD_COLUMNS,
            rows=(("统一估值查询", "统一估值查询", "**市净率（倍）**: 3.74"),),
        ),
    )

    outcome = NeodataValuationNormalizer().normalize(raw, as_of=AS_OF)

    assert outcome.observations == ()
    assert outcome.failures[0].label == "标的代码（统一输出字段名）"
