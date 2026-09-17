"""估值数据进入管线的端到端测试。

这条链路此前只到归一化层就断了：`scan` / `daily` 读不到估值，于是 Value / GARP
在真实运行里永远"缺证据"。这里钉住接好之后的四件事：

1. 落地的估值能被管线按取数日选出来；
2. 未来日期的落地文件不可见（时点由文件选择保证）；
3. 归一化后的估值观测进入因子上下文，且每个因子只看到自己标的的行；
4. 估值因子因此能给出 `VALUE`，而不是 `NOT_APPLICABLE`。
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.data.providers.neodata import PAYLOAD_COLUMNS
from astock_lens.data.sync import land_neodata_blocks
from astock_lens.domain.enums import DataStatus
from astock_lens.factors.builtin import build_factor
from astock_lens.factors.config import load_factor_config
from astock_lens.factors.contracts import FactorContext
from astock_lens.pipelines import stages

ROOT = Path(__file__).resolve().parents[2]
CSV_FIXTURES = ROOT / "tests" / "fixtures" / "csv"
FIXTURES = ROOT / "tests" / "fixtures" / "neodata"
CONFIGS = ROOT / "configs"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
LONG_DATASET = "daily_bars_long"


def _blocks(dataset: str) -> tuple[tuple[str, str, str], ...]:
    payload = json.loads((FIXTURES / f"{dataset}.json").read_text(encoding="utf-8"))
    return tuple(
        (
            str(b.get("type") or ""),
            str(b.get("desc") or ""),
            str(b.get("content") or ""),
        )
        for b in payload["data"]["apiData"]["apiRecall"]
    )


class Stub:
    """回放录制的估值响应。"""

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="neodata",
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=AS_OF,
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        rows = _blocks("valuation")
        return RawDataset(
            provider="neodata",
            dataset=request.dataset,
            fetched_at=AS_OF,
            provider_version="v1",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=PAYLOAD_COLUMNS, rows=rows),
        )


def _root(local_tmp: Path, *, landed: bool = True) -> Path:
    for name in ("daily_bars_long.csv", "securities.csv"):
        shutil.copyfile(CSV_FIXTURES / name, local_tmp / name)
    if landed:
        land_neodata_blocks(
            provider=Stub(),
            root=local_tmp,
            dataset="valuation",
            values=("000568.SZ",),
            as_of=AS_OF,
        )
    return local_tmp


def test_a_scan_without_landed_valuations_says_so(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root(local_tmp, landed=False),
        as_of=AS_OF,
        dataset=LONG_DATASET,
    )

    assert outcome.valuations is not None
    assert outcome.valuations.source_file is None
    assert outcome.valuations.observations == ()
    assert outcome.bars.valuations == ()


def test_landed_valuations_reach_the_factor_context(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root(local_tmp), as_of=AS_OF, dataset=LONG_DATASET
    )

    assert outcome.valuations is not None
    assert outcome.valuations.source_file is not None
    assert outcome.valuations.source_file.name == "2026-09-17.csv"
    assert outcome.bars.valuations
    assert {item.symbol for item in outcome.bars.valuations} == {"000568.SZ"}

    pe = build_factor(load_factor_config(CONFIGS / "factors" / "pe_ttm.yaml")).compute(
        FactorContext(symbol="000568.SZ", as_of=AS_OF, dataset=outcome.bars)
    )
    assert pe.status is DataStatus.VALUE
    assert pe.raw_value is not None
    assert pe.unit == "x"


def test_a_future_landing_is_invisible_at_the_point_in_time(local_tmp: Path) -> None:
    root = _root(local_tmp, landed=False)
    land_neodata_blocks(
        provider=Stub(),
        root=root,
        dataset="valuation",
        values=("000568.SZ",),
        as_of=datetime(2026, 9, 25, 15, 0, tzinfo=UTC),
    )

    outcome = stages.normalize_stage(csv_root=root, as_of=AS_OF, dataset=LONG_DATASET)

    assert outcome.valuations is not None
    assert outcome.valuations.source_file is None
    assert outcome.valuations.observations == ()


def test_each_factor_sees_only_its_own_symbol_valuations(local_tmp: Path) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root(local_tmp), as_of=AS_OF, dataset=LONG_DATASET
    )
    index = stages.DatasetIndex(outcome.bars)

    view = index.for_symbol("000568.SZ")
    other = index.for_symbol("600519.SH")

    assert view.valuations
    assert other.valuations == ()
    assert all(item.symbol == "000568.SZ" for item in view.valuations)


def test_the_reported_metrics_match_what_the_response_carried(
    local_tmp: Path,
) -> None:
    outcome = stages.normalize_stage(
        csv_root=_root(local_tmp), as_of=AS_OF, dataset=LONG_DATASET
    )

    assert outcome.valuations is not None
    metrics = {item.metric for item in outcome.valuations.observations}
    assert {"pe_ttm", "pb", "peg", "pcf_operating_ttm"} <= metrics
    # 该响应里每一格都读得出来，因此没有失败记录。
    assert outcome.valuations.failures == ()


def test_reading_valuations_twice_gives_the_same_answer(local_tmp: Path) -> None:
    root = _root(local_tmp)

    first = stages.valuation_inputs(root, as_of=AS_OF)
    second = stages.valuation_inputs(root, as_of=AS_OF)

    assert first.source_file == second.source_file
    assert len(first.observations) == len(second.observations)
