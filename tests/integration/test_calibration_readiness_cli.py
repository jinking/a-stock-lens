"""校准总体必须等于研究池。

所有者批准的语义是"校准的总体必须与正式策略扫描一致"。这条测试用 100 只宽名单 /
40 只研究池的合成数据把它钉住：校准结果里**不允许**出现任何一个被前置筛选或 Universe
规则排除的宽名单标的，报告还要如实写出它算在哪个总体之上。
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

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
