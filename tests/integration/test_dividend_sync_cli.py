"""`astock sync-dividends` 命令集成测试 (Plan B Task 3).

验证：
- 第一轮部分返回时，第二轮仅请求仍然缺失的标的 (partial-response resume)；
- 当一轮没有带来任何新标的时停止继续请求 (no-progress stop)；
- 块身份合并：后一轮落地的数据不会冲掉前一轮已落地的标的 (survive later rounds)；
- 目标路径严格为 data/raw/neodata/dividend_history/YYYY-MM-DD.csv。
"""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astock_lens.cli.app import app
from astock_lens.data.contracts import (
    DataProvider,
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.domain.enums import DataStatus

AS_OF = "2026-09-19"
DAY = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


class FakeNeodataDividendProvider(DataProvider):
    """支持多轮响应控制的分红派息 Provider 替身。"""

    def __init__(
        self, responses: Sequence[Mapping[str, list[tuple[str, str, str]]]]
    ) -> None:
        self._provider = "neodata"
        self._version = "v1"
        self.requests: list[FetchRequest] = []
        self._responses = list(responses)

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self._provider,
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=datetime.now(UTC),
            message="healthy",
        )

    def fetch(self, request: FetchRequest) -> RawDataset:
        self.requests.append(request)
        round_idx = min(len(self.requests) - 1, len(self._responses) - 1)
        resp_map = self._responses[round_idx]

        rows: list[tuple[str, str, str]] = []
        missing: list[str] = []
        for symbol in request.symbols or ():
            if symbol in resp_map:
                rows.extend(resp_map[symbol])
            else:
                missing.append(symbol)

        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=datetime.now(UTC),
            provider_version=self._version,
            status=DataStatus.VALUE if rows else DataStatus.NULL,
            row_count=len(rows),
            missing_symbols=tuple(missing),
            payload=RawPayload(columns=("type", "desc", "content"), rows=tuple(rows)),
        )


def _dividend_block(symbol: str, name: str) -> tuple[str, str, str]:
    content = (
        f"## {name}（标的代码：{symbol}）\n\n"
        "| 公告日期 | 分红方案 | 股权登记日 | 除权除息日 | 方案进度 |\n"
        "| :---: | :---: | :---: | :---: | :---: |\n"
        "| 2026-06-20 | 10派10.00元 | 2026-07-05 | 2026-07-06 | 实施 |\n"
    )
    return ("分红送配详细", "分红送配详细", content)


def test_sync_dividends_partial_response_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 1: Round 1 返回子集，Round 2 只问缺失的标的。"""
    csv_root = tmp_path / "csv"
    csv_root.mkdir(parents=True)
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(csv_root))

    universe_file = tmp_path / "universe.json"
    universe_file.write_text(
        json.dumps({"research_symbols": ["600519.SH", "000858.SZ", "000568.SZ"]}),
        encoding="utf-8",
    )

    # 第一轮只回 600519.SH；第二轮补充回 000858.SZ 与 000568.SZ
    resp_round_1 = {"600519.SH": [_dividend_block("600519.SH", "贵州茅台")]}
    resp_round_2 = {
        "000858.SZ": [_dividend_block("000858.SZ", "五粮液")],
        "000568.SZ": [_dividend_block("000568.SZ", "泸州老窖")],
    }
    fake_provider = FakeNeodataDividendProvider([resp_round_1, resp_round_2])
    monkeypatch.setattr(
        "astock_lens.cli.app._neodata_provider", lambda **kwargs: fake_provider
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "sync-dividends",
            "--as-of",
            AS_OF,
            "--universe",
            str(universe_file),
            "--max-rounds",
            "3",
            "--batch-size",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    # 验证请求历史：第一轮请求 3 只，第二轮只请求缺失的 2 只
    assert len(fake_provider.requests) == 2
    assert set(fake_provider.requests[0].symbols or ()) == {
        "600519.SH",
        "000858.SZ",
        "000568.SZ",
    }
    assert set(fake_provider.requests[1].symbols or ()) == {"000858.SZ", "000568.SZ"}

    # 验证落地文件
    target_csv = csv_root / "neodata" / "dividend_history" / f"{AS_OF}.csv"
    assert target_csv.is_file()
    content = target_csv.read_text(encoding="utf-8")
    assert "600519.SH" in content
    assert "000858.SZ" in content
    assert "000568.SZ" in content


def test_sync_dividends_stops_on_no_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 2: 当某轮没有带来任何新标的时停止后续请求，并报告剩余缺口。"""
    csv_root = tmp_path / "csv"
    csv_root.mkdir(parents=True)
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(csv_root))

    universe_file = tmp_path / "universe.json"
    universe_file.write_text(
        json.dumps({"research_symbols": ["600519.SH", "000858.SZ"]}),
        encoding="utf-8",
    )

    # 第一轮回 600519.SH；第二轮返回空字典（无新标的）
    resp_round_1 = {"600519.SH": [_dividend_block("600519.SH", "贵州茅台")]}
    resp_round_2: dict[str, list[tuple[str, str, str]]] = {}
    fake_provider = FakeNeodataDividendProvider([resp_round_1, resp_round_2])
    monkeypatch.setattr(
        "astock_lens.cli.app._neodata_provider", lambda **kwargs: fake_provider
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "sync-dividends",
            "--as-of",
            AS_OF,
            "--universe",
            str(universe_file),
            "--max-rounds",
            "5",
            "--batch-size",
            "5",
        ],
    )

    # 停在第 2 轮，没有打满 5 轮
    assert len(fake_provider.requests) == 2
    assert (
        "本轮没有带来任何新标的，停止继续请求" in result.output
        or "no_progress" in result.output
    )
    assert "000858.SZ" in result.output


def test_sync_dividends_landed_blocks_survive_later_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 3: 先前轮次落地的分红块必须在后续轮次中得以保留。"""
    csv_root = tmp_path / "csv"
    csv_root.mkdir(parents=True)
    monkeypatch.setenv("ASTOCK_CSV_ROOT", str(csv_root))

    universe_file = tmp_path / "universe.json"
    universe_file.write_text(
        json.dumps({"research_symbols": ["600519.SH", "000858.SZ"]}),
        encoding="utf-8",
    )

    resp_round_1 = {"600519.SH": [_dividend_block("600519.SH", "贵州茅台")]}
    resp_round_2 = {"000858.SZ": [_dividend_block("000858.SZ", "五粮液")]}
    fake_provider = FakeNeodataDividendProvider([resp_round_1, resp_round_2])
    monkeypatch.setattr(
        "astock_lens.cli.app._neodata_provider", lambda **kwargs: fake_provider
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "sync-dividends",
            "--as-of",
            AS_OF,
            "--universe",
            str(universe_file),
            "--max-rounds",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    target_csv = csv_root / "neodata" / "dividend_history" / f"{AS_OF}.csv"
    lines = target_csv.read_text(encoding="utf-8").splitlines()
    # 验证 header + 两条独立内容行
    assert len(lines) >= 3
    assert any("600519.SH" in l for l in lines)
    assert any("000858.SZ" in l for l in lines)
