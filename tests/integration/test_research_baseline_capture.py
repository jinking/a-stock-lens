"""一份离线的、可逐字节复算的研究诊断。

迁移前要有基线，基线必须是一次**只读**的运行：一次 `run_research_analysis`，
多产物渲染，不碰正式快照 / Watchlist / Job，也不重跑任何外部抓取。否则"迁移前
的样子"就成了一次会漂移的快照，而不是证据。

本文件钉住五件事：

1. `capture()` 返回 manifest 路径，六个产物齐全；
2. 只调用一次 canonical 分析（不是一次报告一次交换文件）；
3. 数据源只有本地 CSV Provider，三个外部 Provider 的 `fetch` 一律抛异常；
4. 除输出目录外，工作区里没有多出任何文件（正式状态零改动）；
5. JSONL 排序键明确、数值原样落盘（不四舍五入），两次运行逐字节一致。
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

import scripts.capture_research_baseline as capture_module
from astock_lens.data.contracts import FetchRequest, RawDataset
from astock_lens.data.providers.akshare_provider import AkShareProvider
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.providers.neodata import NeodataProvider
from astock_lens.data.providers.westock import WestockCliProvider
from astock_lens.factors.contracts import FactorResult
from astock_lens.strategies.contracts import StrategyResult
from scripts.capture_research_baseline import capture

ROOT = Path(__file__).resolve().parents[2]
AS_OF_TEXT = "2026-09-18"
AS_OF = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)
BROAD = 100
RESEARCH = 40
MEMBERSHIP_AS_OF = "2026-09-18T15:00:00+08:00"
INDUSTRY_COLUMNS = (
    "symbol",
    "industry_id",
    "industry_name",
    "as_of",
    "provider",
    "source_ref",
)
MANIFEST = "manifest.json"
ARTIFACTS = (
    "factors.jsonl",
    "strategies.jsonl",
    "research-universe.json",
    "calibration.json",
    "calibration.md",
)


def _write_fixture(root: Path) -> tuple[str, ...]:
    """100 只宽名单，其中 40 只通过前置筛选（其余是 ST 或刚上市）。

    与 `tests/integration/test_calibration_readiness_cli.py::_write_fixture` 同源；
    按计划要求在本文件里保留私有副本，避免两个套件互相牵连。
    """
    header = (
        "symbol,name,exchange,list_date,is_st,is_delisting_board,suspended_trading_days"
    )
    listing = [header]
    surviving: list[str] = []
    for index in range(BROAD):
        symbol = f"{index:06d}.SZ"
        if index < RESEARCH:
            surviving.append(symbol)
            listing.append(f"{symbol},n{index},SZSE,2015-01-05,False,False,")
        elif index % 2 == 0:
            listing.append(f"{symbol},n{index},SZSE,2015-01-05,True,False,")
        else:
            listing.append(f"{symbol},n{index},SZSE,2026-09-10,False,False,")
    (root / "securities.csv").write_text("\n".join(listing) + "\n", encoding="utf-8")

    bars = ["symbol,trade_date,open,high,low,close,volume,amount,turnover_rate"]
    for step, symbol in enumerate(surviving):
        for offset in range(300):
            day = date(2026, 9, 18) - timedelta(days=offset)
            price = 10 + step * 0.05 + offset * 0.001
            bars.append(
                f"{symbol},{day.isoformat()},{price:.4f},{price + 0.1:.4f},"
                f"{price - 0.1:.4f},{price:.4f},1000,200000000,0.01"
            )
    (root / "daily_bars.csv").write_text("\n".join(bars) + "\n", encoding="utf-8")
    return tuple(surviving)


def _write_industry(path: Path, symbols: tuple[str, ...]) -> Path:
    """落一份仓库规范形状的行业成员 CSV，故意漏掉最后一只。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(INDUSTRY_COLUMNS)
        for index, symbol in enumerate(symbols[:-1]):
            writer.writerow(
                (
                    symbol,
                    f"pt{index:08d}",
                    "股份制银行Ⅱ",
                    MEMBERSHIP_AS_OF,
                    "westock-cli",
                    f"n{index}",
                )
            )
    return path


def _prepare(local_tmp: Path) -> tuple[Path, Path, Path]:
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)
    industry_path = _write_industry(
        local_tmp / "industry" / "2026-09-18.csv", surviving
    )
    output_dir = local_tmp / "analysis"
    return csv_root, industry_path, output_dir


def _run(local_tmp: Path) -> tuple[Path, Path, Path]:
    csv_root, industry_path, output_dir = _prepare(local_tmp)
    manifest = capture(
        csv_root=csv_root,
        as_of=AS_OF,
        output_dir=output_dir,
        config_root=ROOT / "configs",
        industry_path=industry_path,
    )
    return manifest, output_dir, industry_path


def _files_under(root: Path) -> set[Path]:
    return {path for path in root.rglob("*") if path.is_file()}


# --- 1. 六个产物 -------------------------------------------------------------


def test_capture_returns_the_manifest_and_writes_six_artifacts(
    local_tmp: Path,
) -> None:
    csv_root, industry_path, output_dir = _prepare(local_tmp)
    before = _files_under(local_tmp)

    manifest = capture(
        csv_root=csv_root,
        as_of=AS_OF,
        output_dir=output_dir,
        config_root=ROOT / "configs",
        industry_path=industry_path,
    )

    assert manifest == output_dir / MANIFEST
    assert manifest.is_file()
    written = {
        path.relative_to(output_dir).as_posix() for path in _files_under(output_dir)
    }
    assert written == {MANIFEST, *ARTIFACTS}

    # 除输出目录之外，工作区里没有多出任何文件：正式状态零改动。
    created = _files_under(local_tmp) - before
    assert {path for path in created} == {
        output_dir / MANIFEST,
        *(output_dir / name for name in ARTIFACTS),
    }


def test_the_manifest_names_its_kind_and_its_inputs(local_tmp: Path) -> None:
    import json

    manifest, output_dir, industry_path = _run(local_tmp)
    document = json.loads(manifest.read_text(encoding="utf-8"))

    assert document["artifact_kind"] == "research_diagnostic"
    assert document["as_of"] == AS_OF.isoformat()
    # 它不是 SnapshotStore 的产物，也不许被登记成业务状态。
    assert document["registered_as_business_state"] is False
    sources = {item["path"] for item in document["inputs"]}
    assert str(industry_path) in sources
    for artifact in document["artifacts"]:
        path = output_dir / artifact["name"]
        assert path.is_file()
        assert artifact["sha256"] and artifact["bytes"] == path.stat().st_size
    assert [item["name"] for item in document["artifacts"]] == list(ARTIFACTS)


# --- 2. 只跑一次分析 ---------------------------------------------------------


def test_the_canonical_analysis_runs_exactly_once(local_tmp: Path, monkeypatch) -> None:
    csv_root, industry_path, output_dir = _prepare(local_tmp)
    real = capture_module.run_research_analysis
    calls: list[dict[str, object]] = []

    def counting(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(capture_module, "run_research_analysis", counting)
    capture(
        csv_root=csv_root,
        as_of=AS_OF,
        output_dir=output_dir,
        config_root=ROOT / "configs",
        industry_path=industry_path,
    )

    assert len(calls) == 1


# --- 3. 离线：只有本地 CSV Provider -------------------------------------------


def test_only_the_local_csv_provider_is_ever_consulted(
    local_tmp: Path, monkeypatch
) -> None:
    """三个外部 Provider 的 fetch 一律抛异常；本地 CSV 的调用被记账。

    这条守卫防的是回归：一旦 capture 开始依赖外部抓取，"迁移前基线"就成了
    网络状况的函数，而不是某个固定输入的函数。
    """

    def forbidden(self, request: FetchRequest) -> RawDataset:
        raise AssertionError(f"an offline capture must not fetch: {request!r}")

    monkeypatch.setattr(AkShareProvider, "fetch", forbidden)
    monkeypatch.setattr(WestockCliProvider, "fetch", forbidden)
    monkeypatch.setattr(NeodataProvider, "fetch", forbidden)

    local_fetches: list[FetchRequest] = []
    real_local = LocalCsvProvider.fetch

    def counting_local(self, request: FetchRequest) -> RawDataset:
        local_fetches.append(request)
        return real_local(self, request)

    monkeypatch.setattr(LocalCsvProvider, "fetch", counting_local)

    manifest, _, _ = _run(local_tmp)

    assert manifest.is_file()
    assert local_fetches, "本地 CSV Provider 才是唯一的数据入口"


# --- 4. JSONL：排序与不四舍五入 ------------------------------------------------


def test_factor_jsonl_is_sorted_by_symbol_then_factor(local_tmp: Path) -> None:
    _, output_dir, _ = _run(local_tmp)
    lines = (output_dir / "factors.jsonl").read_text(encoding="utf-8").splitlines()
    records = [FactorResult.model_validate_json(line) for line in lines]
    keys = [(record.symbol, record.factor) for record in records]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys)), "同一 (symbol, factor) 不许出现两次"
    assert records, "夹具应当至少产出一条因子结果"


def test_strategy_jsonl_is_sorted_by_strategy_then_symbol(local_tmp: Path) -> None:
    _, output_dir, _ = _run(local_tmp)
    lines = (output_dir / "strategies.jsonl").read_text(encoding="utf-8").splitlines()
    records = [StrategyResult.model_validate_json(line) for line in lines]
    keys = [(record.strategy_id, record.symbol) for record in records]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
    assert records


def test_jsonl_values_are_not_rounded(local_tmp: Path) -> None:
    """数值原样落盘：只要有一处被四舍五入到 4 位，这条就红。"""
    import json

    _, output_dir, _ = _run(local_tmp)
    values = [
        json.loads(line)["raw_value"]
        for line in (output_dir / "factors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    floats = [value for value in values if isinstance(value, float)]
    assert floats
    assert any(value != round(value, 4) for value in floats), (
        "所有因子值都等于 round(value, 4)：JSONL 很可能被四舍五入过"
    )


def test_jsonl_round_trips_through_the_domain_record_verbatim(
    local_tmp: Path,
) -> None:
    """每一行都等于领域对象自己的序列化结果——没有二次编码、没有改写。"""
    _, output_dir, _ = _run(local_tmp)
    for name, model in (
        ("factors.jsonl", FactorResult),
        ("strategies.jsonl", StrategyResult),
    ):
        for line in (output_dir / name).read_text(encoding="utf-8").splitlines():
            assert model.model_validate_json(line).model_dump_json() == line


# --- 5. 可复现与缺口如实 -------------------------------------------------------


def test_two_runs_are_byte_for_byte_identical(local_tmp: Path) -> None:
    csv_root, industry_path, first_dir = _prepare(local_tmp)
    second_dir = local_tmp / "analysis-2"
    for target in (first_dir, second_dir):
        capture(
            csv_root=csv_root,
            as_of=AS_OF,
            output_dir=target,
            config_root=ROOT / "configs",
            industry_path=industry_path,
        )

    for name in ARTIFACTS:
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes(), name


def test_a_missing_industry_is_a_reported_gap_not_a_silent_pass(
    local_tmp: Path,
) -> None:
    """行业缺一只：诊断照出，缺口写在报告里，而且它既不是零也不是空。"""
    import json

    _, output_dir, _ = _run(local_tmp)
    payload = json.loads((output_dir / "calibration.json").read_text(encoding="utf-8"))
    assert len(payload["unknown_industry_symbols"]) == 1
    assert (
        payload["industry_coverage"]["missing_symbols"]
        == payload["unknown_industry_symbols"]
    )
    assert payload["industry_evidence"]["origin"] == "canonical"
    assert payload["industry_evidence"]["mapping_as_of"] == MEMBERSHIP_AS_OF
    assert payload["industry_evidence"]["diagnostic_only"] is True
    markdown = (output_dir / "calibration.md").read_text(encoding="utf-8")
    assert "缺失行业代码（1）" in markdown


def test_a_missing_industry_path_fails_explicitly(local_tmp: Path) -> None:
    """`--industry-path` 指向不存在的文件：显式失败，不产出一份空报告。"""
    csv_root, _, output_dir = _prepare(local_tmp)
    with pytest.raises(FileNotFoundError):
        capture(
            csv_root=csv_root,
            as_of=AS_OF,
            output_dir=output_dir,
            config_root=ROOT / "configs",
            industry_path=local_tmp / "does-not-exist.csv",
        )
    assert not output_dir.exists()
