"""校准总体必须等于研究池。

所有者批准的语义是"校准的总体必须与正式策略扫描一致"。这条测试用 100 只宽名单 /
40 只研究池的合成数据把它钉住：校准结果里**不允许**出现任何一个被前置筛选或 Universe
规则排除的宽名单标的，报告还要如实写出它算在哪个总体之上。

后半部分钉住行业映射这份证据：外部映射缺标的时仍出诊断并如实列出缺口，仓库规范
映射缺标的一律拒绝；映射日期只能来自命令行声明或数据本身，**绝不来自文件 mtime，
也绝不把分析时点顶替上去**。
"""

import csv
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from astock_lens.calibration.candidate_report import IndustryCoverageUnavailable
from astock_lens.cli.app import app
from astock_lens.factors.config import load_factor_config
from astock_lens.pipelines.analysis import run_research_analysis
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config

ROOT = Path(__file__).resolve().parents[2]
AS_OF_TEXT = "2026-09-18"
AS_OF = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)
BROAD = 100
RESEARCH = 40
# 规范映射文件里成员自己声明的取数时点；它早于 AS_OF，所以对分析时点可见。
MEMBERSHIP_AS_OF = "2026-09-18T15:00:00+08:00"
FUTURE_AS_OF = "2026-10-01T15:00:00+08:00"
INDUSTRY_COLUMNS = (
    "symbol",
    "industry_id",
    "industry_name",
    "as_of",
    "provider",
    "source_ref",
)


def _write_fixture(root: Path) -> tuple[str, ...]:
    """100 只宽名单，其中 40 只通过前置筛选（其余是 ST 或刚上市）。"""
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
        # 300 根 bar 让"最长窗口"的因子（proximity_52w_high 要 252 根）可算。
        for offset in range(300):
            day = date(2026, 9, 18) - timedelta(days=offset)
            price = 10 + step * 0.05 + offset * 0.001
            bars.append(
                f"{symbol},{day.isoformat()},{price:.4f},{price + 0.1:.4f},"
                f"{price - 0.1:.4f},{price:.4f},1000,200000000,0.01"
            )
    (root / "daily_bars.csv").write_text("\n".join(bars) + "\n", encoding="utf-8")
    return tuple(surviving)


def _factor_configs():
    directory = ROOT / "configs" / "factors"
    return tuple(load_factor_config(path) for path in sorted(directory.glob("*.yaml")))


def test_the_canonical_research_analysis_never_scores_an_excluded_symbol(
    local_tmp: Path,
) -> None:
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)

    population, analysis = run_research_analysis(
        csv_root=csv_root,
        as_of=AS_OF,
        universe_config=load_universe_config(ROOT / "configs" / "universe.yaml"),
        factor_configs=_factor_configs(),
        scanners=load_scanners(ROOT / "configs" / "strategies"),
    )

    assert len(analysis.outcome.securities) == BROAD
    assert set(population.research_symbols) == set(surviving)
    scored = {result.symbol for result in analysis.strategy_results}
    assert scored == set(surviving), (
        "the calibration population must be the Research Universe, not the broad "
        f"listing; unexpected symbols: {sorted(scored - set(surviving))}"
    )


def test_the_calibration_command_reports_the_population_it_used(
    local_tmp: Path,
) -> None:
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)
    industry_map = local_tmp / "industry.csv"
    industry_map.write_text(
        "symbol,industry\n"
        + "\n".join(f"{symbol},股份制银行Ⅱ" for symbol in surviving)
        + "\n",
        encoding="utf-8",
    )
    output_dir = local_tmp / "reports"

    result = CliRunner().invoke(
        app,
        [
            "calibrate",
            "candidates",
            "--as-of",
            AS_OF_TEXT,
            "--output-dir",
            str(output_dir),
            "--industry-map",
            str(industry_map),
        ],
        env={"ASTOCK_CSV_ROOT": str(csv_root)},
    )

    assert result.exit_code == 0, result.output
    report = (output_dir / f"{AS_OF_TEXT}-candidate-calibration.json").read_text(
        encoding="utf-8"
    )
    assert '"broad_listing_count": 100' in report
    assert '"research_count": 40' in report
    assert "CALIBRATION ONLY" in report
    for index in range(RESEARCH, BROAD):
        assert f"{index:06d}.SZ" not in report, (
            "an excluded broad symbol must not appear anywhere in the report"
        )


# --- 行业映射这份证据 ----------------------------------------------------------


def _write_canonical(
    csv_root: Path,
    symbols: tuple[str, ...],
    *,
    future: tuple[tuple[str, str], ...] = (),
) -> Path:
    """落一份仓库规范形状的行业成员文件。

    `future` 里的记录晚于分析时点，用来证明它们**不会**进入历史正式口径。
    """
    path = csv_root / "westock" / "industry" / f"{AS_OF_TEXT}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(INDUSTRY_COLUMNS)
        for index, symbol in enumerate(symbols):
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
        for symbol, industry in future:
            writer.writerow(
                (symbol, "pt99999999", industry, FUTURE_AS_OF, "westock-cli", "future")
            )
    return path


def _write_external(path: Path, symbols: tuple[str, ...]) -> Path:
    path.write_text(
        "symbol,industry\n"
        + "\n".join(f"{symbol},股份制银行Ⅱ" for symbol in symbols)
        + "\n",
        encoding="utf-8",
    )
    return path


def _run(local_tmp: Path, csv_root: Path, *extra: str):
    return CliRunner().invoke(
        app,
        [
            "calibrate",
            "candidates",
            "--as-of",
            AS_OF_TEXT,
            "--output-dir",
            str(local_tmp / "reports"),
            *extra,
        ],
        env={"ASTOCK_CSV_ROOT": str(csv_root)},
    )


def _report(local_tmp: Path) -> dict:
    path = local_tmp / "reports" / f"{AS_OF_TEXT}-candidate-calibration.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_an_external_map_missing_one_symbol_still_produces_the_diagnostic(
    local_tmp: Path,
) -> None:
    """外部映射缺一只：报告照出，缺口恰好是那一只，不许悄悄换成 0。"""
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)
    missing = surviving[-1]
    industry_map = _write_external(
        local_tmp / "industry.csv", tuple(s for s in surviving if s != missing)
    )

    result = _run(local_tmp, csv_root, "--industry-map", str(industry_map))

    assert result.exit_code == 0, result.output
    payload = _report(local_tmp)
    assert payload["unknown_industry_symbols"] == [missing]
    assert payload["unknown_industry_count"] == 1
    assert payload["industry_coverage_ratio"] == round(39 / 40, 4)
    assert payload["industry_evidence"]["origin"] == "external"
    assert payload["industry_evidence"]["mapping_as_of"] is None
    assert payload["industry_evidence"]["diagnostic_only"] is True
    assert payload["industry_coverage"]["missing_symbols"] == [missing]
    for index in range(RESEARCH, BROAD):
        assert f"{index:06d}.SZ" not in json.dumps(payload)


def test_the_canonical_map_missing_one_symbol_is_still_refused(
    local_tmp: Path,
) -> None:
    """仓库规范映射缺一只：仍然拒绝。缺一整项证据的材料不是可批复的材料。"""
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)
    _write_canonical(csv_root, tuple(s for s in surviving if s != surviving[-1]))

    result = _run(local_tmp, csv_root)

    assert result.exit_code == 1
    assert isinstance(result.exception, IndustryCoverageUnavailable)
    assert "1 of 40" in str(result.exception)


def test_a_complete_canonical_map_records_its_own_date_and_origin(
    local_tmp: Path,
) -> None:
    """规范映射完整时：来源标 canonical，日期取成员自己声明的取数时点。"""
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)
    canonical_path = _write_canonical(csv_root, surviving)

    result = _run(local_tmp, csv_root)

    assert result.exit_code == 0, result.output
    payload = _report(local_tmp)
    evidence = payload["industry_evidence"]
    assert evidence["origin"] == "canonical"
    assert evidence["mapping_as_of"] == MEMBERSHIP_AS_OF
    assert evidence["source_ref"] == str(canonical_path)
    assert len(evidence["source_sha256"]) == 64
    assert payload["unknown_industry_symbols"] == []
    assert payload["industry_coverage_ratio"] == 1.0


def test_future_membership_records_never_enter_the_historical_canonical_map(
    local_tmp: Path,
) -> None:
    """晚于分析时点的成员记录不可见：它既不改行业，也不改映射日期。"""
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)
    # 同一只标的在将来换了一个行业；历史口径必须仍然看到 MEMBERSHIP_AS_OF 那一条。
    _write_canonical(
        csv_root,
        surviving,
        future=((surviving[0], "另一行业"),),
    )

    result = _run(local_tmp, csv_root)

    assert result.exit_code == 0, result.output
    payload = _report(local_tmp)
    assert payload["industry_evidence"]["mapping_as_of"] == MEMBERSHIP_AS_OF
    industries = {
        name
        for strategy in payload["strategies"]
        for name, _count in strategy["industry_counts"]
    }
    assert "另一行业" not in industries


def test_a_declared_mapping_date_is_recorded_verbatim(local_tmp: Path) -> None:
    """外部映射声明了日期就原样记录；不声明就是 null，绝不用 mtime 顶替。"""
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)
    industry_map = _write_external(local_tmp / "industry.csv", surviving)

    declared = "2026-09-16T15:00:00+08:00"
    result = _run(
        local_tmp,
        csv_root,
        "--industry-map",
        str(industry_map),
        "--industry-map-as-of",
        declared,
    )

    assert result.exit_code == 0, result.output
    assert _report(local_tmp)["industry_evidence"]["mapping_as_of"] == declared
    assert Path(industry_map).stat().st_mtime > 0  # 文件有 mtime，但它不是证据


def _flat(output: str) -> str:
    """把 CLI 的方框排版压成一行，好让断言只关心内容、不关心换行位置。"""
    return " ".join(output.split())


def test_a_mapping_date_without_a_timezone_is_refused(local_tmp: Path) -> None:
    """裸时间不是事实：没有时区的映射日期被拒绝。"""
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)
    industry_map = _write_external(local_tmp / "industry.csv", surviving)

    result = _run(
        local_tmp,
        csv_root,
        "--industry-map",
        str(industry_map),
        "--industry-map-as-of",
        "2026-09-16T15:00:00",
    )

    assert result.exit_code == 2  # Click 的用法错误码：拒绝就是拒绝
    assert "timezone" in _flat(result.output)


def test_a_mapping_date_without_an_external_map_is_refused(local_tmp: Path) -> None:
    """映射日期描述的是一份外部映射；没有那份映射时它无话可说。"""
    csv_root = local_tmp / "csv"
    csv_root.mkdir()
    surviving = _write_fixture(csv_root)
    _write_canonical(csv_root, surviving)

    result = _run(
        local_tmp,
        csv_root,
        "--industry-map-as-of",
        MEMBERSHIP_AS_OF,
    )

    assert result.exit_code == 2
    assert "--industry-map" in _flat(result.output)
