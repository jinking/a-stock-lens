"""估值补抓与覆盖报告的 CLI 集成测试。

这条链路存在的理由：源端一批只回 1–2 只，2,303 只研究池必须多轮补齐。
所以四件事必须钉住：

1. 多轮补抓是合并的——后一轮不冲掉前一轮；
2. 第二轮只请求仍然缺的标的，已覆盖的不重复问；
3. 缺口没补完时退出码 1，缺口清单落盘；全覆盖时退出码 0；
4. 覆盖报告的分母是显式研究池，不是"已落地的标的"。

全程不联网：provider 由假源替换，只回放构造的内容块。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

import astock_lens.cli.app as app_module
from astock_lens.cli.app import app
from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.data.providers.neodata import PAYLOAD_COLUMNS
from astock_lens.domain.enums import DataStatus

AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
DAY = "2026-09-17"
ROOT = Path(__file__).resolve().parents[2]
NEODATA_FIXTURES = ROOT / "tests" / "fixtures" / "neodata"


def valuation_block(symbol: str, pe: str) -> tuple[str, str, str]:
    return (
        "统一估值查询",
        "统一估值查询",
        f"**标的代码（统一输出字段名）**: {symbol}\n\n  **滚动市盈率（倍）**: {pe}\n",
    )


class UnlockingSource:
    """每被调用一次才解锁一只标的，模拟"一批只回一两块"。"""

    def __init__(self, symbols: Sequence[str]) -> None:
        self._pending = list(symbols)
        self.requests: list[tuple[str, ...]] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="neodata",
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=AS_OF,
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        asked = tuple(request.symbols or ())
        self.requests.append(asked)
        unlocked = self._pending.pop(0) if self._pending else None
        rows = (valuation_block(unlocked, "10.00"),) if unlocked else ()
        missing = tuple(symbol for symbol in asked if symbol != unlocked)
        return RawDataset(
            provider="neodata",
            dataset=request.dataset,
            fetched_at=AS_OF,
            provider_version="v1",
            status=DataStatus.VALUE,
            row_count=len(rows),
            missing_symbols=missing,
            payload=RawPayload(columns=PAYLOAD_COLUMNS, rows=rows),
        )


class CompleteSource(UnlockingSource):
    """一次就把被问到的标的全部返回。"""

    def __init__(self) -> None:
        super().__init__(())

    def fetch(self, request: FetchRequest) -> RawDataset:
        asked = tuple(request.symbols or ())
        self.requests.append(asked)
        rows = tuple(valuation_block(symbol, "10.00") for symbol in asked)
        return RawDataset(
            provider="neodata",
            dataset=request.dataset,
            fetched_at=AS_OF,
            provider_version="v1",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=PAYLOAD_COLUMNS, rows=rows),
        )


def _write_universe(root: Path, symbols: Sequence[str]) -> Path:
    path = root / "research-universe.json"
    path.write_text(
        json.dumps({"as_of": AS_OF.isoformat(), "research_symbols": list(symbols)}),
        encoding="utf-8",
    )
    return path


def _invoke(
    local_tmp: Path,
    monkeypatch: object,
    source: object,
    *args: str,
) -> object:
    monkeypatch.setattr(app_module, "_neodata_provider", lambda: source)  # type: ignore[attr-defined]
    return CliRunner().invoke(
        app,
        list(args),
        env={"ASTOCK_CSV_ROOT": str(local_tmp)},
    )


def test_rounds_merge_and_every_round_only_asks_what_is_missing(
    local_tmp: Path, monkeypatch: object
) -> None:
    universe = _write_universe(local_tmp, ("600519.SH", "000001.SZ", "000568.SZ"))
    source = UnlockingSource(("600519.SH", "000001.SZ", "000568.SZ"))

    result = _invoke(
        local_tmp,
        monkeypatch,
        source,
        "sync-valuation",
        "--as-of",
        DAY,
        "--universe",
        str(universe),
        "--max-rounds",
        "3",
        "--output",
        str(local_tmp / "missing.json"),
    )

    assert result.exit_code == 0, result.output
    # 第一轮问全部 3 只，第二轮只问剩下的 2 只，第三轮只问剩下的 1 只。
    assert [len(asked) for asked in source.requests] == [3, 2, 1]
    landed = (local_tmp / "neodata" / "valuation" / f"{DAY}.csv").read_text(
        encoding="utf-8"
    )
    for symbol in ("600519.SH", "000001.SZ", "000568.SZ"):
        assert symbol in landed
    report = json.loads((local_tmp / "missing.json").read_text(encoding="utf-8"))
    assert report["missing_symbols"] == []
    assert report["stop_reason"] == "max_rounds"


def test_a_gap_that_does_not_close_stops_and_exits_non_zero(
    local_tmp: Path, monkeypatch: object
) -> None:
    universe = _write_universe(local_tmp, ("600519.SH", "000001.SZ"))
    source = UnlockingSource(("600519.SH",))  # 只解得到一只，另一只永远回不来

    result = _invoke(
        local_tmp,
        monkeypatch,
        source,
        "sync-valuation",
        "--as-of",
        DAY,
        "--universe",
        str(universe),
        "--max-rounds",
        "3",
        "--output",
        str(local_tmp / "missing.json"),
    )

    assert result.exit_code == 1
    # 第二轮没有带来新标的就停下，不会有第三轮空转。
    assert len(source.requests) == 2
    report = json.loads((local_tmp / "missing.json").read_text(encoding="utf-8"))
    assert report["missing_symbols"] == ["000001.SZ"]
    assert report["stop_reason"] == "no_progress"
    assert report["rounds"][0]["landed"] == 1
    assert report["rounds"][1]["landed"] == 0


def test_a_covered_symbol_is_not_asked_again(
    local_tmp: Path, monkeypatch: object
) -> None:
    universe = _write_universe(local_tmp, ("600519.SH", "000001.SZ"))
    source = CompleteSource()

    first = _invoke(
        local_tmp,
        monkeypatch,
        source,
        "sync-valuation",
        "--as-of",
        DAY,
        "--universe",
        str(universe),
    )
    second = _invoke(
        local_tmp,
        monkeypatch,
        source,
        "sync-valuation",
        "--as-of",
        DAY,
        "--universe",
        str(universe),
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert len(source.requests) == 1
    assert "已全覆盖" in second.output


def test_a_missing_universe_file_is_an_error_not_an_empty_run(
    local_tmp: Path, monkeypatch: object
) -> None:
    result = _invoke(
        local_tmp,
        monkeypatch,
        CompleteSource(),
        "sync-valuation",
        "--as-of",
        DAY,
        "--universe",
        str(local_tmp / "nope.json"),
    )

    assert result.exit_code == 1
    assert "研究池名单不存在" in result.output


def test_the_coverage_command_reports_the_universe_as_the_denominator(
    local_tmp: Path, monkeypatch: object
) -> None:
    blocks = tuple(
        (
            str(block.get("type") or ""),
            str(block.get("desc") or ""),
            str(block.get("content") or ""),
        )
        for block in json.loads(
            (NEODATA_FIXTURES / "valuation.json").read_text(encoding="utf-8")
        )["data"]["apiData"]["apiRecall"]
    )
    universe = _write_universe(local_tmp, ("000568.SZ", "600519.SH"))
    # 直接铺一份录制回放，不经过假源：这份测试只问"报告的分母与口径对不对"。
    _write_blocks(local_tmp / "neodata" / "valuation" / f"{DAY}.csv", blocks)

    result = _invoke(
        local_tmp,
        monkeypatch,
        CompleteSource(),
        "valuation-coverage",
        "--as-of",
        DAY,
        "--universe",
        str(universe),
        "--output",
        str(local_tmp / "coverage.json"),
    )

    assert result.exit_code == 0, result.output
    report = json.loads((local_tmp / "coverage.json").read_text(encoding="utf-8"))
    assert report["universe_size"] == 2
    assert report["covered_symbols"] == ["000568.SZ"]
    assert report["uncovered_symbols"] == ["600519.SH"]
    by_strategy = {item["strategy_id"]: item for item in report["strategies"]}
    # 000568.SZ 的 PE/PB/PS/分位/市现率齐全，只有 PEG 是负值。
    assert by_strategy["value"]["scoreable_symbols"] == ["000568.SZ"]
    assert by_strategy["garp"]["scoreable_symbols"] == []
    assert by_strategy["garp"]["non_valuation_factors"] == [
        "revenue_cagr_3y",
        "net_profit_parent_cagr_3y",
        "roe_ttm",
    ]


def _write_blocks(path: Path, blocks: Sequence[tuple[str, str, str]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(PAYLOAD_COLUMNS)
        writer.writerows(blocks)


def test_the_coverage_command_refuses_an_empty_universe(
    local_tmp: Path, monkeypatch: object
) -> None:
    path = local_tmp / "empty.json"
    path.write_text("{}", encoding="utf-8")

    result = _invoke(
        local_tmp,
        monkeypatch,
        CompleteSource(),
        "valuation-coverage",
        "--as-of",
        DAY,
        "--universe",
        str(path),
    )

    assert result.exit_code == 1
    assert "research_symbols" in result.output
