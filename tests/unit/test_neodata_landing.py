"""neodata 落地测试。

落地的形状决定了时点能不能复现，因此这里钉住三件事：

- 文件按"数据集 + 取数日"命名，同一天重跑按块身份合并、不同天各自留档；
- 内容是逐字文本块，读回来一模一样（含多行）；
- 未来日期的文件不会被选到——"今天看不见明天的答案"由文件选择保证。

为什么同一天从"整天覆盖"改成"按块身份合并"：批量补抓必然分多轮执行
（实测源端一批只回 1–2 只），整天覆盖会让后一轮冲掉前一轮已落地的标的。
合并后仍然幂等——同一标的/板块当天重抓，旧块被新块替换，不会出现两份。
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.data.providers.neodata import PAYLOAD_COLUMNS
from astock_lens.data.sync import (
    land_neodata_blocks,
    latest_neodata_file,
    read_raw_rows,
)
from astock_lens.domain.enums import DataStatus

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "neodata"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


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
    """按需回放内容块，或报告失败。"""

    def __init__(
        self, rows: Sequence[tuple[str, str, str]], *, status: DataStatus | None = None
    ) -> None:
        self.rows = tuple(rows)
        self.status = status

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="neodata",
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=AS_OF,
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        if self.status is not None:
            return RawDataset(
                provider="neodata",
                dataset=request.dataset,
                fetched_at=AS_OF,
                provider_version="v1",
                status=self.status,
                row_count=0,
                missing_symbols=tuple(request.symbols or ()),
                message="服务端返回 code=1001 msg=未命中意图",
            )
        return RawDataset(
            provider="neodata",
            dataset=request.dataset,
            fetched_at=AS_OF,
            provider_version="v1",
            status=DataStatus.VALUE,
            row_count=len(self.rows),
            payload=RawPayload(columns=PAYLOAD_COLUMNS, rows=self.rows),
        )


def _land(root: Path, rows: Sequence[tuple[str, str, str]], **kwargs: object) -> object:
    status = kwargs.pop("status", None)
    return land_neodata_blocks(
        provider=Stub(rows, status=status),  # type: ignore[arg-type]
        root=root,
        dataset="valuation",
        values=("600519.SH",),
        as_of=AS_OF,
    )


def test_blocks_land_verbatim_under_a_dated_file(local_tmp: Path) -> None:
    rows = _blocks("valuation")

    landing = _land(local_tmp, rows)

    assert landing.status is DataStatus.VALUE
    assert landing.path == local_tmp / "neodata" / "valuation" / "2026-09-17.csv"
    columns, landed = read_raw_rows(landing.path)
    assert columns == PAYLOAD_COLUMNS
    assert landed == rows
    # 多行内容读回来仍然是同一段文本。
    assert "滚动市盈率（倍）" in landed[0][2]
    assert landed[0][2].count("\n") > 5


def test_the_same_day_replaces_and_another_day_is_kept(local_tmp: Path) -> None:
    _land(local_tmp, _blocks("valuation"))
    _land(local_tmp, _blocks("industry"))

    _, rows = read_raw_rows(local_tmp / "neodata" / "valuation" / "2026-09-17.csv")

    # 两块身份不同（标的 000568.SZ / 板块 01801125.PT），因此是并集而不是覆盖。
    assert len(rows) == len(_blocks("valuation")) + len(_blocks("industry"))
    assert latest_neodata_file(
        local_tmp, "valuation", as_of=datetime(2026, 9, 18, 15, 0, tzinfo=UTC)
    ) == (local_tmp / "neodata" / "valuation" / "2026-09-17.csv")


def _valuation_block(symbol: str, pe: str) -> tuple[str, str, str]:
    """一条最小可辨识的估值内容块：身份由标的代码决定。"""
    return (
        "统一估值查询",
        "统一估值查询",
        f"**标的代码（统一输出字段名）**: {symbol}\n\n  **滚动市盈率（倍）**: {pe}\n",
    )


def test_a_second_landing_the_same_day_keeps_the_first_batch(local_tmp: Path) -> None:
    """多轮补抓：第二轮只带来自己的标的，第一轮的标的必须还在。"""
    _land(local_tmp, (_valuation_block("600519.SH", "19.31"),))
    _land(local_tmp, (_valuation_block("000001.SZ", "5.18"),))

    _, rows = read_raw_rows(local_tmp / "neodata" / "valuation" / "2026-09-17.csv")

    symbols = {row[2].split("**:", 1)[1].split("\n", 1)[0].strip() for row in rows}
    assert symbols == {"600519.SH", "000001.SZ"}
    assert len(rows) == 2


def test_relanging_the_same_symbol_replaces_only_its_own_block(
    local_tmp: Path,
) -> None:
    """同一天对同一标的重抓：旧块被替换，别的标的块不受影响。"""
    _land(local_tmp, (_valuation_block("600519.SH", "19.31"),))
    _land(
        local_tmp,
        (_valuation_block("600519.SH", "20.00"), _valuation_block("000001.SZ", "5.18")),
    )

    _, rows = read_raw_rows(local_tmp / "neodata" / "valuation" / "2026-09-17.csv")
    by_symbol = {
        row[2].split("**:", 1)[1].split("\n", 1)[0].strip(): row for row in rows
    }

    assert len(rows) == 2
    assert "20.00" in by_symbol["600519.SH"][2]
    assert "19.31" not in by_symbol["600519.SH"][2]


def test_replaying_the_same_blocks_does_not_double_count(local_tmp: Path) -> None:
    """重放同一份响应是幂等的：块身份相同，行数不变。"""
    rows = _blocks("valuation")
    _land(local_tmp, rows)
    _land(local_tmp, rows)

    _, landed = read_raw_rows(local_tmp / "neodata" / "valuation" / "2026-09-17.csv")

    assert landed == rows


def test_a_failed_fetch_writes_nothing_and_names_the_gap(local_tmp: Path) -> None:
    landing = _land(local_tmp, (), status=DataStatus.SOURCE_ERROR)

    assert landing.status is DataStatus.SOURCE_ERROR
    assert not landing.path.exists()
    assert landing.symbols_missing == ("600519.SH",)
    assert landing.note is not None
    assert "1001" in landing.note


def test_landing_needs_at_least_one_value(local_tmp: Path) -> None:
    with pytest.raises(ValueError, match="至少一个查询值"):
        land_neodata_blocks(
            provider=Stub(()),
            root=local_tmp,
            dataset="valuation",
            values=(),
            as_of=AS_OF,
        )


def test_the_latest_file_at_or_before_the_point_in_time_is_used(
    local_tmp: Path,
) -> None:
    _land(local_tmp, _blocks("valuation"))
    later = local_tmp / "neodata" / "valuation" / "2026-09-19.csv"
    later.write_text("type,desc,content\n未来,未来,答案\n", encoding="utf-8")

    assert (
        latest_neodata_file(local_tmp, "valuation", as_of=AS_OF)
        == local_tmp / "neodata" / "valuation" / "2026-09-17.csv"
    )
    assert (
        latest_neodata_file(
            local_tmp, "valuation", as_of=datetime(2026, 9, 20, 15, 0, tzinfo=UTC)
        )
        == later
    )
    # 早于所有落地日期的时点什么都读不到，而不是读到"最近的那份"。
    assert (
        latest_neodata_file(
            local_tmp, "valuation", as_of=datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
        )
        is None
    )


def test_junk_filenames_are_not_treated_as_data(local_tmp: Path) -> None:
    directory = local_tmp / "neodata" / "valuation"
    directory.mkdir(parents=True)
    (directory / "notes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (directory / "2026-09-17.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    assert (
        latest_neodata_file(local_tmp, "valuation", as_of=AS_OF)
        == directory / "2026-09-17.csv"
    )


def test_a_missing_directory_reads_as_nothing(local_tmp: Path) -> None:
    assert latest_neodata_file(local_tmp, "valuation", as_of=AS_OF) is None


def test_blocks_from_a_different_dataset_land_in_their_own_file(
    local_tmp: Path,
) -> None:
    """行业与估值分开落地：读的时候才能各自做时点选择。"""
    provider = Stub(_blocks("industry"))
    landing = land_neodata_blocks(
        provider=provider,
        root=local_tmp,
        dataset="industry",
        values=("白酒Ⅱ",),
        as_of=AS_OF,
    )

    assert landing.path.parent.name == "industry"
    assert latest_neodata_file(local_tmp, "valuation", as_of=AS_OF) is None
    assert latest_neodata_file(local_tmp, "industry", as_of=AS_OF) == landing.path
