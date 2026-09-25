"""集成层 CLI 入口流程长尾用例。

本文件由 Task 12「文件合并」把以下 12 个同域小文件整体搬入：
    - tests/integration/test_calibration_readiness_cli.py（9 例）
    - tests/integration/test_candidate_calibration_cli.py（6 例）
    - tests/integration/test_candidates_cli.py（4 例）
    - tests/integration/test_command_snapshot_ownership.py（4 例）
    - tests/integration/test_dividend_sync_cli.py（3 例）
    - tests/integration/test_market_signal_readiness_cli.py（3 例）
    - tests/integration/test_qualification_impact_cli.py（2 例）
    - tests/integration/test_qualified_cli.py（9 例）
    - tests/integration/test_screen_cli.py（9 例）
    - tests/integration/test_today_cli.py（4 例）
    - tests/integration/test_trade_gate_cli.py（1 例）
    - tests/integration/test_valuation_backfill_cli.py（7 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from click.testing import Result
from typer.testing import CliRunner
from typer.testing import Result as TyperResult

import astock_lens.cli.app as app_module
from astock_lens.calibration.candidate_report import (
    CALIBRATION_WARNING,
    IndustryCoverageUnavailable,
)
from astock_lens.candidates.models import Candidate
from astock_lens.cli.app import _as_of, app
from astock_lens.data.contracts import (
    DataProvider,
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.data.providers.neodata import PAYLOAD_COLUMNS
from astock_lens.data.snapshots.resolve import resolve_snapshot_store
from astock_lens.data.snapshots.store import JsonSnapshotStore
from astock_lens.domain.enums import (
    DataStatus,
    MarketValidation,
    NextAction,
    Signal,
    SnapshotKind,
)
from astock_lens.domain.models import SnapshotLineage
from astock_lens.factors.config import load_factor_config
from astock_lens.factors.contracts import FactorResult
from astock_lens.pipelines.analysis import run_research_analysis
from astock_lens.qualifications.models import StrategyQualification
from astock_lens.strategies.contracts import StrategyResult
from astock_lens.strategies.registry import load_scanners
from astock_lens.universe.config import load_universe_config
from tests.support import strip_ansi

# ===========================================================================
# 来源：tests/integration/test_calibration_readiness_cli.py（9 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 校准总体必须等于研究池。
#
# 所有者批准的语义是"校准的总体必须与正式策略扫描一致"。这条测试用 100 只宽名单 /
# 40 只研究池的合成数据把它钉住：校准结果里**不允许**出现任何一个被前置筛选或 Universe
# 规则排除的宽名单标的，报告还要如实写出它算在哪个总体之上。
#
# 后半部分钉住行业映射这份证据：外部映射缺标的时仍出诊断并如实列出缺口，仓库规范
# 映射缺标的一律拒绝；映射日期只能来自命令行声明或数据本身，**绝不来自文件 mtime，
# 也绝不把分析时点顶替上去**。
#


ROOT = Path(__file__).resolve().parents[2]


AS_OF_TEXT = "2026-09-18"


READINESS_CLI_AS_OF = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)


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
        as_of=READINESS_CLI_AS_OF,
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
    return " ".join(strip_ansi(output).split())


def _external_map_with_bare_date(
    local_tmp: Path, csv_root: Path, surviving: tuple[str, ...]
) -> tuple[str, ...]:
    """裸时间不是事实：外部映射就位，但声明的时间没有时区。"""
    industry_map = _write_external(local_tmp / "industry.csv", surviving)
    return (
        "--industry-map",
        str(industry_map),
        "--industry-map-as-of",
        "2026-09-16T15:00:00",
    )


def _declared_date_without_external_map(
    local_tmp: Path, csv_root: Path, surviving: tuple[str, ...]
) -> tuple[str, ...]:
    """映射日期描述的是一份外部映射；没有那份映射时它无话可说。"""
    _write_canonical(csv_root, surviving)
    return ("--industry-map-as-of", MEMBERSHIP_AS_OF)


# 两行是「不可用的映射日期声明必须以 Click 用法错误拒绝」同一断言的参数枚举。
MAPPING_DATE_USAGE_ERROR_CASES: tuple[
    tuple[str, Callable[[Path, Path, tuple[str, ...]], tuple[str, ...]], str], ...
] = (
    (
        "test_a_mapping_date_without_a_timezone_is_refused",
        _external_map_with_bare_date,
        "timezone",
    ),
    (
        "test_a_mapping_date_without_an_external_map_is_refused",
        _declared_date_without_external_map,
        "--industry-map",
    ),
)


def test_unusable_mapping_date_declarations_are_refused(local_tmp: Path) -> None:
    wrong = []
    for label, prepare_args, expected_fragment in MAPPING_DATE_USAGE_ERROR_CASES:
        case_root = local_tmp / label
        case_root.mkdir()
        csv_root = case_root / "csv"
        csv_root.mkdir()
        surviving = _write_fixture(csv_root)
        extra = prepare_args(case_root, csv_root, surviving)

        result = _run(case_root, csv_root, *extra)

        if result.exit_code != 2:
            wrong.append(
                f"{label}: 期望 Click 用法错误码 2，实际 {result.exit_code}；"
                f"输出 {result.output!r}"
            )
            continue
        if expected_fragment not in _flat(result.output):
            wrong.append(
                f"{label}: 输出缺少 {expected_fragment!r}；"
                f"实际 {_flat(result.output)!r}"
            )
    assert not wrong, "映射日期用法错误未被拒绝:\n" + "\n".join(wrong)


# ===========================================================================
# 来源：tests/integration/test_candidate_calibration_cli.py（6 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Integration tests for the candidate calibration CLI command.
#
# Pins down:
# - The command executes canonical non-persistent analysis chain;
# - Generates deterministic JSON and Markdown reports with the calibration warning;
# - Guarantees zero production mutation across snapshot, watchlist, and job roots;
# - Fails loudly on invalid or corrupt industry maps.
#


CALIBRATION_CLI_ROOT = Path(__file__).resolve().parents[2]


CSV_ROOT = CALIBRATION_CLI_ROOT / "tests" / "fixtures" / "csv"


DAY = "2026-09-04"


LONG_DATASET = "daily_bars_long"


SYMBOLS = [
    "600000.SH",
    "000001.SZ",
    "600519.SH",
    "601398.SH",
    "300750.SZ",
    "002594.SZ",
    "601899.SH",
]


def _write_industry_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    content = "symbol,industry\n" + "\n".join(f"{s},{i}" for s, i in rows) + "\n"
    path.write_text(content, encoding="utf-8")


def test_calibrate_cli_help() -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["calibrate", "--help"])
    assert res.exit_code == 0
    assert "candidates" in res.stdout

    res2 = runner.invoke(app, ["calibrate", "candidates", "--help"])
    assert res2.exit_code == 0
    help_text = strip_ansi(res2.stdout)
    assert "--as-of" in help_text
    assert "--industry-map" in help_text
    assert "--output-dir" in help_text


def test_calibrate_candidates_generates_reports_without_production_mutation(
    tmp_path: Path,
) -> None:
    # 1. Arrange sentinels in production-like directories
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    output_dir = tmp_path / "calibration_out"

    snapshot_root.mkdir(parents=True)
    watchlist_root.mkdir(parents=True)
    job_root.mkdir(parents=True)

    snapshot_sentinel = snapshot_root / "SENTINEL.txt"
    snapshot_sentinel.write_text("snapshot untouched", encoding="utf-8")
    watchlist_sentinel = watchlist_root / "SENTINEL.txt"
    watchlist_sentinel.write_text("watchlist untouched", encoding="utf-8")
    job_sentinel = job_root / "SENTINEL.txt"
    job_sentinel.write_text("job untouched", encoding="utf-8")

    # 2. Arrange valid industry mapping
    industry_csv = tmp_path / "industry.csv"
    _write_industry_csv(
        industry_csv,
        [
            ("600000.SH", "银行"),
            ("000001.SZ", "银行"),
            ("600519.SH", "饮料"),
            ("601398.SH", "银行"),
            ("300750.SZ", "电力设备"),
            ("002594.SZ", "汽车"),
            ("601899.SH", "有色金属"),
        ],
    )

    # 3. Act: invoke CLI
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "candidates",
            "--as-of",
            DAY,
            "--industry-map",
            str(industry_csv),
            "--output-dir",
            str(output_dir),
        ],
        env={
            "ASTOCK_CSV_ROOT": str(CSV_ROOT),
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_WATCHLIST_ROOT": str(watchlist_root),
            "ASTOCK_JOB_ROOT": str(job_root),
            "ASTOCK_DATASET": LONG_DATASET,
        },
    )

    assert result.exit_code == 0, result.output
    assert "Calibration report written" in result.stdout

    # 4. Assert: output artifacts created
    json_path = output_dir / f"{DAY}-candidate-calibration.json"
    md_path = output_dir / f"{DAY}-candidate-calibration.md"
    assert json_path.is_file()
    assert md_path.is_file()

    json_content = json_path.read_text(encoding="utf-8")
    md_content = md_path.read_text(encoding="utf-8")
    assert CALIBRATION_WARNING in json_content
    assert CALIBRATION_WARNING in md_content

    # 5. Assert: production sentinels untouched and no new files in production roots
    assert list(snapshot_root.iterdir()) == [snapshot_sentinel]
    assert list(watchlist_root.iterdir()) == [watchlist_sentinel]
    assert list(job_root.iterdir()) == [job_sentinel]
    assert snapshot_sentinel.read_text(encoding="utf-8") == "snapshot untouched"
    assert watchlist_sentinel.read_text(encoding="utf-8") == "watchlist untouched"
    assert job_sentinel.read_text(encoding="utf-8") == "job untouched"


def _duplicate_symbol_industry_csv(tmp_path: Path) -> Path:
    industry_csv = tmp_path / "duplicate_industry.csv"
    _write_industry_csv(
        industry_csv,
        [
            ("600000.SH", "银行"),
            ("600000.SH", "非银金融"),
        ],
    )
    return industry_csv


def _missing_header_industry_csv(tmp_path: Path) -> Path:
    industry_csv = tmp_path / "bad_header.csv"
    industry_csv.write_text("code,sector\n600000.SH,银行\n", encoding="utf-8")
    return industry_csv


# 三行是「坏行业映射必须响亮失败」同一断言的参数枚举；行 label 为原用例名。
CALIBRATION_INDUSTRY_ERROR_CASES: tuple[
    tuple[str, Callable[[Path], Path], str], ...
] = (
    (
        "test_calibrate_candidates_fails_on_missing_industry_file",
        lambda tmp_path: tmp_path / "nonexistent.csv",
        "not found",
    ),
    (
        "test_calibrate_candidates_fails_on_duplicate_symbol_in_industry_csv",
        _duplicate_symbol_industry_csv,
        "duplicate symbol",
    ),
    (
        "test_calibrate_candidates_fails_on_missing_header_in_industry_csv",
        _missing_header_industry_csv,
        "columns",
    ),
)


def test_calibrate_candidates_fails_loudly_on_bad_industry_maps(tmp_path: Path) -> None:
    wrong = []
    for (
        label,
        prepare_industry_map,
        expected_message,
    ) in CALIBRATION_INDUSTRY_ERROR_CASES:
        case_root = tmp_path / label
        case_root.mkdir()
        industry_csv = prepare_industry_map(case_root)
        result = CliRunner().invoke(
            app,
            [
                "calibrate",
                "candidates",
                "--as-of",
                DAY,
                "--industry-map",
                str(industry_csv),
                "--output-dir",
                str(case_root / "out"),
            ],
            env={"ASTOCK_CSV_ROOT": str(CSV_ROOT)},
        )
        if result.exit_code == 0:
            wrong.append(
                f"{label}: 期望非零退出，实际 exit_code=0；输出 {result.output!r}"
            )
            continue
        if expected_message not in result.output.lower():
            wrong.append(
                f"{label}: 输出缺少 {expected_message!r}；实际 {result.output!r}"
            )
    assert not wrong, "坏行业映射未按预期失败:\n" + "\n".join(wrong)


def test_calibrate_candidates_canonical_merges_supplement(tmp_path: Path) -> None:
    import json
    import shutil

    # 1. Arrange csv root with securities and bars from fixtures
    csv_root = tmp_path / "csv"
    csv_root.mkdir(parents=True)
    shutil.copy(CSV_ROOT / "securities.csv", csv_root / "securities.csv")
    shutil.copy(CSV_ROOT / "daily_bars_long.csv", csv_root / "daily_bars_long.csv")

    # 2. Canonical industry file has 5 of the 6 universe symbols (missing 900948.SH)
    industry_dir = csv_root / "westock" / "industry"
    industry_dir.mkdir(parents=True)
    canonical_csv = industry_dir / f"{DAY}.csv"
    canonical_csv.write_text(
        "symbol,industry_id,industry_name,as_of,provider,source_ref\n"
        "600000.SH,pt01,银行,2026-09-04T15:00:00+08:00,westock-cli,\n"
        "000001.SZ,pt01,银行,2026-09-04T15:00:00+08:00,westock-cli,\n"
        "600519.SH,pt02,饮料,2026-09-04T15:00:00+08:00,westock-cli,\n"
        "300750.SZ,pt03,电力设备,2026-09-04T15:00:00+08:00,westock-cli,\n"
        "000006.SZ,pt04,房地产,2026-09-04T15:00:00+08:00,westock-cli,\n",
        encoding="utf-8",
    )

    # 3. Supplemental config supplies 900948.SH
    supplement_yaml = tmp_path / "supplement.yaml"
    supplement_yaml.write_text(
        "supplements:\n"
        "  - symbol: 900948.SH\n"
        "    industry_id: sw2_coal\n"
        "    industry_name: 煤炭开采\n"
        "    provider: sws-official\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "candidates",
            "--as-of",
            DAY,
            "--output-dir",
            str(output_dir),
        ],
        env={
            "ASTOCK_CSV_ROOT": str(csv_root),
            "ASTOCK_DATASET": LONG_DATASET,
            "ASTOCK_INDUSTRY_SUPPLEMENT_PATH": str(supplement_yaml),
        },
    )
    assert result.exit_code == 0, result.output
    report = json.loads(
        (output_dir / f"{DAY}-candidate-calibration.json").read_text(encoding="utf-8")
    )
    assert report["industry_evidence"]["origin"] == "canonical"
    assert report["industry_coverage"]["ratio"] == 1.0
    assert len(report["industry_coverage"]["missing_symbols"]) == 0
    assert (
        report["industry_coverage"]["known_count"]
        == report["industry_coverage"]["total_count"]
    )


# ===========================================================================
# 来源：tests/integration/test_candidates_cli.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Integration tests for `astock candidates` CLI command.
#
# Plan: docs/superpowers/plans/2026-09-21-candidate-today-query-experience.md Task 2
# Spec: docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md
#


runner = CliRunner()


CANDIDATES_CLI_AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


def _make_candidate(
    symbol: str,
    *,
    primary_strategy_id: str = "momentum",
    qualified_strategies: tuple[str, ...] = ("momentum",),
    market_validation: MarketValidation | None = MarketValidation.CONFIRMED,
    signal: Signal | None = Signal.BREAKOUT,
    next_action: NextAction = NextAction.WATCH,
    risks: tuple[str, ...] = (),
) -> Candidate:
    quals = tuple(
        StrategyQualification(
            symbol=symbol,
            strategy_id=s_id,
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=0.95,
            as_of=CANDIDATES_CLI_AS_OF,
        )
        for s_id in qualified_strategies
    )
    s_results = tuple(
        StrategyResult(
            symbol=symbol,
            strategy_id=s_id,
            strategy_version="v1",
            as_of=CANDIDATES_CLI_AS_OF,
            eligible=True,
            score=88.0,
            rank_percentile=0.95,
            lineage=SnapshotLineage(strategy_version="v1"),
        )
        for s_id in qualified_strategies
    )
    return Candidate(
        symbol=symbol,
        as_of=CANDIDATES_CLI_AS_OF,
        next_action=next_action,
        lineage=SnapshotLineage(
            strategy_version="v1",
            qualification_version="v1",
            candidate_policy_version="v1",
            regime_version="v1",
            market_validation_version="v1",
            signal_version="v1",
            universe_snapshot="2026-09-19:u1",
        ),
        primary_strategy_id=primary_strategy_id,
        strategy_qualifications=quals,
        strategy_results=s_results,
        market_validation=market_validation,
        signal=signal,
        reasons=(f"qualified for {primary_strategy_id}",),
        risks=risks,
    )


def test_candidates_cli_missing_snapshot_fails_explicitly(
    local_tmp: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(local_tmp / "snapshots"))
    result = runner.invoke(app, ["candidates", "--as-of", "2026-09-01"])
    assert result.exit_code != 0
    assert "no CANDIDATE snapshot for 2026-09-01" in result.output


def test_candidates_cli_published_empty_snapshot_exits_zero(
    local_tmp: Path, monkeypatch
) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)
    # 写入空快照
    store.write(SnapshotKind.CANDIDATE, CANDIDATES_CLI_AS_OF, [])
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))

    result = runner.invoke(app, ["candidates", "--as-of", "2026-09-19"])
    assert result.exit_code == 0
    assert "candidates: 0" in result.output


def test_candidates_cli_displays_expected_columns_in_stored_order(
    local_tmp: Path, monkeypatch
) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)

    c1 = _make_candidate(
        "600519.SH",
        primary_strategy_id="quality",
        qualified_strategies=("quality", "value"),
        market_validation=MarketValidation.CONFIRMED,
        signal=Signal.BREAKOUT,
        next_action=NextAction.WATCH,
    )
    c2 = _make_candidate(
        "000001.SZ",
        primary_strategy_id="momentum",
        qualified_strategies=("momentum",),
        market_validation=MarketValidation.NEUTRAL,
        signal=Signal.TREND_CONTINUE,
        next_action=NextAction.WATCH,
    )
    store.write(SnapshotKind.CANDIDATE, CANDIDATES_CLI_AS_OF, [c1, c2])
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))

    result = runner.invoke(app, ["candidates", "--as-of", "2026-09-19", "--top", "20"])
    assert result.exit_code == 0

    # 验证输出包含关键信息
    assert "600519.SH" in result.output
    assert "000001.SZ" in result.output
    assert "quality" in result.output
    assert "momentum" in result.output
    assert "CONFIRMED" in result.output
    assert "BREAKOUT" in result.output

    # 验证 top 参数生效
    top1_result = runner.invoke(
        app, ["candidates", "--as-of", "2026-09-19", "--top", "1"]
    )
    assert top1_result.exit_code == 0
    assert "600519.SH" in top1_result.output
    assert "000001.SZ" not in top1_result.output


def test_candidates_cli_is_strictly_read_only(local_tmp: Path, monkeypatch) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)
    c = _make_candidate("600519.SH")
    store.write(SnapshotKind.CANDIDATE, CANDIDATES_CLI_AS_OF, [c])
    snap_file = store.path_for(SnapshotKind.CANDIDATE, CANDIDATES_CLI_AS_OF)
    initial_bytes = snap_file.read_bytes()
    initial_mtime = snap_file.stat().st_mtime_ns

    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))
    result = runner.invoke(app, ["candidates", "--as-of", "2026-09-19"])
    assert result.exit_code == 0

    assert snap_file.read_bytes() == initial_bytes
    assert snap_file.stat().st_mtime_ns == initial_mtime


# ===========================================================================
# 来源：tests/integration/test_command_snapshot_ownership.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 正式快照的写入权只属于 `daily`。
#
# 本文件钉住两个 P0 问题：
#
# 1. `astock factors compute` 走的是 first slice 那条旧链路，它会写 FACTOR 与
#    CANDIDATE 两份正式快照。于是"只算因子"的只读命令会覆盖当天已经落好的正式
#    候选结果——一个哨兵值就能证明这件事。
# 2. `astock scan` 同样会写正式快照。它只跑一个 Scanner，却能让当天由 `daily`
#    写出的完整候选结果消失，读者无从知道哪一份才是当天的正式产物。
#
# 目标行为写在计划 `a-stock-lens-core-hardening-plan.md` Task 1 / Task 3：
# `factors compute` 与 `strategy run` 是纯计算，`scan` 是预览，`daily` 是唯一
# 正式 Snapshot writer。测试先失败，实现随后跟上。
#


SNAPSHOT_OWNERSHIP_ROOT = Path(__file__).resolve().parents[2]


SNAPSHOT_OWNERSHIP_CSV_ROOT = SNAPSHOT_OWNERSHIP_ROOT / "tests" / "fixtures" / "csv"


SNO_DAY = "2026-09-04"


SNAPSHOT_OWNERSHIP_LONG_DATASET = "daily_bars_long"


CANDIDATE_JSON = Path(SnapshotKind.CANDIDATE.value) / f"{SNO_DAY}.json"


SENTINEL_MARKER = "sentinel-candidate-written-by-another-run"


def _snapshot_root(local_tmp: Path) -> Path:
    return local_tmp / "snapshots"


def _invoke(snapshot_root: Path, *args: str) -> Result:
    """Run the CLI against the fixture data and a scratch snapshot root."""
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_CSV_ROOT": str(SNAPSHOT_OWNERSHIP_CSV_ROOT),
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_JOB_ROOT": str(snapshot_root.parent / "jobs"),
            "ASTOCK_WATCHLIST_ROOT": str(snapshot_root.parent / "watchlist"),
            "ASTOCK_DATASET": SNAPSHOT_OWNERSHIP_LONG_DATASET,
        },
    )


def _write_sentinel(snapshot_root: Path) -> str:
    """落一份当天已经存在的正式 CANDIDATE，内容一眼可辨。"""
    path = snapshot_root / CANDIDATE_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": SnapshotKind.CANDIDATE.value,
        "as_of": datetime(2026, 9, 4, 15, 0, tzinfo=UTC).isoformat(),
        "records": [{"symbol": "600519.SH", "marker": SENTINEL_MARKER}],
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path.read_text(encoding="utf-8")


def _candidate_text(snapshot_root: Path) -> str:
    return (snapshot_root / CANDIDATE_JSON).read_text(encoding="utf-8")


def _written_snapshots(snapshot_root: Path) -> tuple[str, ...]:
    """每份正式快照文件，按相对路径排序。"""
    if not snapshot_root.is_dir():
        return ()
    return tuple(
        sorted(
            str(path.relative_to(snapshot_root))
            for path in snapshot_root.rglob("*.json")
        )
    )


def _snapshot_texts(snapshot_root: Path) -> dict[str, str]:
    """正式快照目录的完整内容，用来证明一次命令之后什么都没被动过。"""
    if not snapshot_root.is_dir():
        return {}
    return {
        str(path.relative_to(snapshot_root)): path.read_text(encoding="utf-8")
        for path in sorted(snapshot_root.rglob("*.json"))
    }


# --- factors compute ---------------------------------------------------------


def test_factors_compute_does_not_touch_the_formal_candidate_snapshot(
    local_tmp: Path,
) -> None:
    """计算因子不是一次正式运行，不能重写当天的正式候选结果。"""
    root = _snapshot_root(local_tmp)
    sentinel = _write_sentinel(root)

    result = _invoke(root, "factors", "compute", "--as-of", SNO_DAY)

    assert result.exit_code == 0, result.output
    assert _candidate_text(root) == sentinel


# --- strategy run ------------------------------------------------------------

# 「不写正式快照的命令」三行：行序与原用例一致，label 即原测试名，
# 原 docstring 逐字保留为行注释。族横跨三个命令小节，落在中间的
# `# --- strategy run ---` 小节里，三个小节标题就都还有内容。
# 列 = label, args：
#   - `args` 逐行保留原 `_invoke(root, ...)` 的命令行参数；
#   - 每行各用 `local_tmp/<label>` 作快照根（原用例各自拿一份新的 `local_tmp`），
#     行与行不共享现场，一行落下快照不会误伤邻行。
NON_PERSISTENT_COMMAND_CASES = (
    # test_factors_compute_writes_no_formal_snapshot_at_all:
    #   目标状态：`factors compute` 只计算，不落任何正式 Snapshot。
    (
        "test_factors_compute_writes_no_formal_snapshot_at_all",
        ("factors", "compute", "--as-of", SNO_DAY),
    ),
    # test_strategy_run_writes_no_formal_snapshot:
    #   跑一个 Scanner 是纯计算：它没有资格写当天的 STRATEGY/CANDIDATE。
    (
        "test_strategy_run_writes_no_formal_snapshot",
        ("strategy", "run", "momentum", "--as-of", SNO_DAY),
    ),
    # test_scan_writes_no_formal_snapshot_at_all:
    #   目标状态：`scan` 是 non-persistent preview。
    (
        "test_scan_writes_no_formal_snapshot_at_all",
        ("scan", "--as-of", SNO_DAY),
    ),
)


def test_read_only_commands_write_no_formal_snapshot(local_tmp: Path) -> None:
    """factors compute / strategy run / scan 都不落任何正式 Snapshot。

    原 3 条「writes_no_formal_snapshot」用例逐条成行；循环只收集，
    断言在表外一次完成，失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, args in NON_PERSISTENT_COMMAND_CASES:
        root = _snapshot_root(local_tmp / label)
        result = _invoke(root, *args)
        if result.exit_code != 0:
            wrong.append(
                f"{label}: exit_code 为 {result.exit_code}，输出 {result.output!r}"
            )
        written = _written_snapshots(root)
        if written != ():
            wrong.append(f"{label}: 落下了正式快照 {written!r}")
    assert not wrong, "只读命令不得写正式快照:\n" + "\n".join(wrong)


# --- scan --------------------------------------------------------------------


def test_scan_leaves_every_formal_snapshot_untouched(local_tmp: Path) -> None:
    """`daily` 写下的正式快照，不能被一次预览改动哪怕一个字节。"""
    root = _snapshot_root(local_tmp)

    daily = _invoke(root, "daily", "--as-of", SNO_DAY, "--allow-incomplete")
    assert daily.exit_code == 0, daily.output
    formal = _snapshot_texts(root)
    assert formal, "前置条件：daily 必须真的写过正式快照"

    after = _invoke(root, "scan", "--as-of", SNO_DAY)

    assert after.exit_code == 0, after.output
    assert _snapshot_texts(root) == formal


def test_scan_does_not_replace_a_formal_candidate_snapshot(local_tmp: Path) -> None:
    """哨兵法：只要 `scan` 真的写了正式快照，这份哨兵就不可能是原样。

    本夹具上预览与 `daily` 恰好算出同样的候选内容，所以"内容没变"不能证明
    任何事。哨兵是任何人都不会产出的内容，它还在原地就意味着没人动过这个文件。
    """
    root = _snapshot_root(local_tmp)
    sentinel = _write_sentinel(root)

    result = _invoke(root, "scan", "--as-of", SNO_DAY)

    assert result.exit_code == 0, result.output
    assert _candidate_text(root) == sentinel


# ===========================================================================
# 来源：tests/integration/test_dividend_sync_cli.py（3 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# `astock sync-dividends` 命令集成测试 (Plan B Task 3).
#
# 验证：
# - 第一轮部分返回时，第二轮仅请求仍然缺失的标的 (partial-response resume)；
# - 当一轮没有带来任何新标的时停止继续请求 (no-progress stop)；
# - 块身份合并：后一轮落地的数据不会冲掉前一轮已落地的标的 (survive later rounds)；
# - 目标路径严格为 data/raw/neodata/dividend_history/YYYY-MM-DD.csv。
#


DIV_AS_OF = "2026-09-19"


DIVIDEND_SYNC_DAY = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


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
            DIV_AS_OF,
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
    target_csv = csv_root / "neodata" / "dividend_history" / f"{DIV_AS_OF}.csv"
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
            DIV_AS_OF,
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
            DIV_AS_OF,
            "--universe",
            str(universe_file),
            "--max-rounds",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    target_csv = csv_root / "neodata" / "dividend_history" / f"{DIV_AS_OF}.csv"
    lines = target_csv.read_text(encoding="utf-8").splitlines()
    # 验证 header + 两条独立内容行
    assert len(lines) >= 3
    assert any("600519.SH" in l for l in lines)
    assert any("000858.SZ" in l for l in lines)


# ===========================================================================
# 来源：tests/integration/test_market_signal_readiness_cli.py（3 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# `astock calibrate market-signal-readiness` 命令集成测试 (Plan C Task 2).
#
# 验证：
# - 严格只读：运行前后 Snapshot/Watchlist/Job 目录指纹完全一致；
# - 缺少快照：缺少 FACTOR 或 STRATEGY 快照时退出非 0，并点名缺失类别；
# - 配置非法：资格配置损坏或未知阈值键时立即失败（fail loudly）；
# - 确定性输出：在 --output-dir 下生成符合命名的 .json 和 .md 产物。
#


AS_OF_STR = "2026-09-19"


SIGNAL_READINESS_CLI_AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


def _hash_tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    hashes = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            hashes[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
    return hashes


def test_missing_snapshot_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 2: 缺少 FACTOR 或 STRATEGY 快照时报错并指出缺失类别。"""
    runner = CliRunner()
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))

    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "calibrate",
            "market-signal-readiness",
            "--as-of",
            AS_OF_STR,
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code != 0
    assert "FACTOR" in result.output or "STRATEGY" in result.output


def test_read_only_and_deterministic_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 1 & Step 4: 严格只读，生成正确的 JSON 与 MD 报告。"""
    runner = CliRunner()
    snap_dir = tmp_path / "snapshots"
    watch_dir = tmp_path / "watchlist"
    job_dir = tmp_path / "jobs"
    out_dir = tmp_path / "out"

    snap_dir.mkdir(parents=True)
    watch_dir.mkdir(parents=True)
    job_dir.mkdir(parents=True)

    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_dir))
    monkeypatch.setenv("ASTOCK_WATCHLIST_ROOT", str(watch_dir))
    monkeypatch.setenv("ASTOCK_JOB_ROOT", str(job_dir))

    store = resolve_snapshot_store(snap_dir)
    fr = FactorResult(
        symbol="600519.SH",
        factor="ret_20d",
        as_of=SIGNAL_READINESS_CLI_AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(),
        raw_value=0.12,
    )
    sr = StrategyResult(
        symbol="600519.SH",
        strategy_id="value",
        as_of=SIGNAL_READINESS_CLI_AS_OF,
        score=88.0,
        rank_percentile=0.95,
        eligible=True,
        strategy_version="v1",
        lineage=SnapshotLineage(),
        factor_snapshot=(),
    )
    store.write(SnapshotKind.FACTOR, SIGNAL_READINESS_CLI_AS_OF, [fr])
    store.write(SnapshotKind.STRATEGY, SIGNAL_READINESS_CLI_AS_OF, [sr])

    # 记录执行前各目录指纹
    before_snaps = _hash_tree(snap_dir)
    before_watch = _hash_tree(watch_dir)
    before_jobs = _hash_tree(job_dir)

    result = runner.invoke(
        app,
        [
            "calibrate",
            "market-signal-readiness",
            "--as-of",
            AS_OF_STR,
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0
    assert (out_dir / f"market-signal-readiness-{AS_OF_STR}.json").is_file()
    assert (out_dir / f"market-signal-readiness-{AS_OF_STR}.md").is_file()

    # 验证严格只读
    assert _hash_tree(snap_dir) == before_snaps
    assert _hash_tree(watch_dir) == before_watch
    assert _hash_tree(job_dir) == before_jobs


def test_invalid_qualification_config_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 3: 资格规则配置非法时 fail loudly，绝不以空合格标的静默产生报告。"""
    runner = CliRunner()
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir(parents=True)
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_dir))

    # 指向一个损坏的资格配置文件目录
    bad_cfg_dir = tmp_path / "configs" / "qualifications"
    bad_cfg_dir.mkdir(parents=True)
    (bad_cfg_dir / "value.yaml").write_text(
        "rules: [{unknown_key: foo}]", encoding="utf-8"
    )
    monkeypatch.setenv("ASTOCK_QUALIFICATION_DIR", str(bad_cfg_dir))

    store = resolve_snapshot_store(snap_dir)
    fr = FactorResult(
        symbol="600519.SH",
        factor="ret_20d",
        as_of=SIGNAL_READINESS_CLI_AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(),
        raw_value=0.12,
    )
    sr = StrategyResult(
        symbol="600519.SH",
        strategy_id="value",
        as_of=SIGNAL_READINESS_CLI_AS_OF,
        score=88.0,
        rank_percentile=0.95,
        eligible=True,
        strategy_version="v1",
        lineage=SnapshotLineage(),
        factor_snapshot=(),
    )
    store.write(SnapshotKind.FACTOR, SIGNAL_READINESS_CLI_AS_OF, [fr])
    store.write(SnapshotKind.STRATEGY, SIGNAL_READINESS_CLI_AS_OF, [sr])

    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "calibrate",
            "market-signal-readiness",
            "--as-of",
            AS_OF_STR,
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code != 0


# ===========================================================================
# 来源：tests/integration/test_qualification_impact_cli.py（2 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Integration tests for the read-only qualification impact audit CLI.
#
# Pins down:
#
# - the command reads stored FACTOR / STRATEGY snapshots and strict canonical
#   qualifiers, and writes only the two audit files under ``--output-dir``;
# - it guarantees zero production mutation across snapshot / watchlist / job roots;
# - it fails loudly when the required snapshots are absent.
#


IMPACT_CLI_DAY = "2026-09-04"


def _factor(symbol: str, name: str, value: float, day: datetime) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=day,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _growth_result(
    symbol: str, day: datetime, *, rank_percentile: float = 0.95
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id="growth",
        strategy_version="v1",
        as_of=day,
        eligible=True,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=90.0,
        rank_percentile=rank_percentile,
    )


def _write_snapshots(snapshot_root: Path, day: datetime) -> None:
    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.FACTOR,
        day,
        (
            _factor("600000.SH", "net_profit_parent_yoy", 20.0, day),
            _factor("600000.SH", "revenue_yoy", 8.0, day),
            _factor("600000.SH", "roe_ttm", 9.0, day),
            _factor("600001.SH", "net_profit_parent_yoy", 10.0, day),
            _factor("600001.SH", "revenue_yoy", 8.0, day),
            _factor("600001.SH", "roe_ttm", 9.0, day),
        ),
    )
    store.write(
        SnapshotKind.STRATEGY,
        day,
        (
            _growth_result("600000.SH", day),
            _growth_result("600001.SH", day),
        ),
    )


def _fingerprint(root: Path) -> dict[str, tuple[int, int, str]]:
    """文件名 + 大小 + mtime + 内容 hash 的确定性指纹。"""
    result: dict[str, tuple[int, int, str]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[path.relative_to(root).as_posix()] = (
                stat.st_size,
                stat.st_mtime_ns,
                digest,
            )
    return result


def test_qualification_impact_cli_is_read_only(tmp_path: Path) -> None:
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    output_dir = tmp_path / "impact_out"

    day = _as_of(IMPACT_CLI_DAY)
    _write_snapshots(snapshot_root, day)
    watchlist_root.mkdir(parents=True)
    job_root.mkdir(parents=True)
    (watchlist_root / "SENTINEL.txt").write_text(
        "watchlist untouched", encoding="utf-8"
    )
    (job_root / "SENTINEL.txt").write_text("job untouched", encoding="utf-8")

    before = (
        _fingerprint(snapshot_root),
        _fingerprint(watchlist_root),
        _fingerprint(job_root),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "qualification-impact",
            "--as-of",
            IMPACT_CLI_DAY,
            "--output-dir",
            str(output_dir),
        ],
        env={
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_WATCHLIST_ROOT": str(watchlist_root),
            "ASTOCK_JOB_ROOT": str(job_root),
        },
    )
    assert result.exit_code == 0, result.output
    assert "Qualification impact audit written" in result.stdout

    after = (
        _fingerprint(snapshot_root),
        _fingerprint(watchlist_root),
        _fingerprint(job_root),
    )
    # 只读：Snapshot / Watchlist / Job 状态逐字节不变。
    assert before == after

    json_path = output_dir / f"qualification-impact-{IMPACT_CLI_DAY}.json"
    md_path = output_dir / f"qualification-impact-{IMPACT_CLI_DAY}.md"
    assert json_path.is_file()
    assert md_path.is_file()

    document = json.loads(json_path.read_text(encoding="utf-8"))
    strategies = {item["strategy_id"]: item for item in document["strategies"]}
    growth = strategies["growth"]
    assert growth["strategy_eligible_count"] == 2
    assert growth["top_ten_count"] == 2
    assert growth["absolute_pass_count"] == 1
    assert growth["dual_pass_count"] == 1
    assert growth["qualified_symbols"] == ["600000.SH"]

    markdown = md_path.read_text(encoding="utf-8")
    assert (
        "| strategy | eligible | ranked | top10 | absolute-pass | dual-pass |"
        in markdown
    )
    assert "`growth`" in markdown


def test_qualification_impact_cli_fails_on_missing_snapshot(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate",
            "qualification-impact",
            "--as-of",
            IMPACT_CLI_DAY,
            "--output-dir",
            str(tmp_path / "out"),
        ],
        env={"ASTOCK_SNAPSHOT_ROOT": str(tmp_path / "snapshots")},
    )
    assert result.exit_code != 0
    assert "no FACTOR snapshot" in result.output


# ===========================================================================
# 来源：tests/integration/test_qualified_cli.py（9 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# `astock qualified` CLI 命令集成测试（Plan A 任务 2）。
#
# 验证：
# - 只读已存储的 FACTOR / STRATEGY 快照 + 已批准资格配置，展示双门槛通过结果；
# - 缺 FACTOR / STRATEGY 快照时非零退出并给出规范提示；
# - 资格配置非法（ASTOCK_QUALIFICATION_DIR）时 fail-closed，绝不降级为零合格正常屏；
# - 请求的策略不在已批准 qualifiers 中时显式 not-found 报错；
# - Dividend 零合格：退出 0、`qualified: 0`、显式数据健康 warning；
# - 只读保证：Snapshot / Watchlist / Job 三个根目录前后指纹完全一致。
#
# 资格配置一律从仓库 `configs/qualifications` 复制到临时目录（已批准阈值，
# 测试不发明任何数值），再通过 `ASTOCK_QUALIFICATION_DIR` 注入。
#


SHANGHAI = ZoneInfo("Asia/Shanghai")


QUALIFIED_CLI_DAY = "2026-09-17"


QUALIFIED_CLI_AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=SHANGHAI)


REPO_ROOT = Path(__file__).resolve().parents[2]


CANONICAL_QUALIFICATION_DIR = REPO_ROOT / "configs" / "qualifications"


# growth 已批准绝对门槛：net_profit_parent_yoy>=15、revenue_yoy>=5、roe_ttm>=8
GROWTH_FACTOR_SEEDS: dict[str, dict[str, float]] = {
    # 绝对门槛通过
    "600000.SH": {"net_profit_parent_yoy": 20.0, "revenue_yoy": 8.0, "roe_ttm": 9.0},
    # 绝对门槛不通过：净利同比 10 < 15
    "600001.SH": {"net_profit_parent_yoy": 10.0, "revenue_yoy": 8.0, "roe_ttm": 9.0},
    # 绝对门槛通过
    "600002.SH": {"net_profit_parent_yoy": 25.0, "revenue_yoy": 12.0, "roe_ttm": 10.0},
    # 绝对门槛通过
    "600003.SH": {"net_profit_parent_yoy": 30.0, "revenue_yoy": 15.0, "roe_ttm": 11.0},
}


def _qualified_cli_factor(symbol: str, name: str, value: float) -> FactorResult:
    return FactorResult(
        symbol=symbol,
        factor=name,
        as_of=QUALIFIED_CLI_AS_OF,
        status=DataStatus.VALUE,
        factor_version="v1",
        lineage=SnapshotLineage(factor_version="v1"),
        raw_value=value,
    )


def _strategy_result(
    symbol: str,
    *,
    strategy_id: str = "growth",
    score: float | None = 80.0,
    percentile: float | None = 0.95,
    eligible: bool = True,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version="v1",
        as_of=QUALIFIED_CLI_AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version="v1"),
        score=score,
        rank_percentile=percentile,
    )


def _qualification_dir(tmp_path: Path) -> Path:
    """把仓库里已批准的资格配置复制到临时目录，测试不改任何阈值。"""
    target = tmp_path / "qualifications"
    shutil.copytree(CANONICAL_QUALIFICATION_DIR, target)
    return target


def _seed_growth_snapshots(snapshot_root: Path) -> None:
    """播种 growth 双门槛场景：600003/600000 双通过，其余各缺一门。"""
    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.FACTOR,
        QUALIFIED_CLI_AS_OF,
        tuple(
            _qualified_cli_factor(symbol, name, value)
            for symbol, factors in GROWTH_FACTOR_SEEDS.items()
            for name, value in factors.items()
        ),
    )
    store.write(
        SnapshotKind.STRATEGY,
        QUALIFIED_CLI_AS_OF,
        (
            # percentile 0.95 通过 + 绝对门槛通过 → 双通过
            _strategy_result("600000.SH", percentile=0.95, score=80.0),
            # percentile 0.95 通过 + 绝对门槛失败
            _strategy_result("600001.SH", percentile=0.95, score=75.0),
            # percentile 0.50 失败 + 绝对门槛通过
            _strategy_result("600002.SH", percentile=0.50, score=70.0),
            # percentile 0.99 通过 + 绝对门槛通过 → 双通过（排第一）
            _strategy_result("600003.SH", percentile=0.99, score=88.0),
            # 其他策略：隔离性验证，绝不出现
            _strategy_result("601398.SH", strategy_id="momentum", percentile=0.99),
        ),
    )


def _qualified_cli_invoke(
    snapshot_root: Path,
    watchlist_root: Path,
    job_root: Path,
    qualification_dir: Path,
    *args: str,
) -> TyperResult:
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_WATCHLIST_ROOT": str(watchlist_root),
            "ASTOCK_JOB_ROOT": str(job_root),
            "ASTOCK_QUALIFICATION_DIR": str(qualification_dir),
        },
    )


def _tree_fingerprint(directory: Path) -> dict[str, str]:
    """文件相对路径 → 内容 SHA256；目录相对路径 → 占位符。

    同时覆盖「内容被改」「新增/删除文件」「新增/删除目录」三种变化。
    """
    entries: dict[str, str] = {}
    if not directory.exists():
        return entries
    for path in sorted(directory.rglob("*")):
        rel = path.relative_to(directory).as_posix()
        if path.is_file():
            entries[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            entries[rel] = "directory"
    return entries


def test_qualified_cli_help() -> None:
    """帮助信息声明 --as-of 与 --top。"""
    result = CliRunner().invoke(app, ["qualified", "--help"])
    assert result.exit_code == 0
    help_text = strip_ansi(result.stdout)
    assert "--as-of" in help_text
    assert "--top" in help_text


def test_qualified_only_dual_pass_displayed(tmp_path: Path) -> None:
    """Step 1: 只展示双门槛通过的行；覆盖度计数完整可见。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)
    _seed_growth_snapshots(snapshot_root)

    result = _qualified_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "growth",
        "--as-of",
        QUALIFIED_CLI_DAY,
    )

    assert result.exit_code == 0, result.output
    out = strip_ansi(result.stdout)
    assert f"growth — {QUALIFIED_CLI_DAY}" in out
    assert (
        "coverage: eligible=4 ranked=4 percentile_pass=3 absolute_pass=3 "
        "qualified=2" in out
    )
    assert "qualified: 2" in out
    assert "showing: 2" in out
    # 双通过的两行，按 rank_percentile DESC 排序
    assert "1  600003.SH  score=88.00  percentile=0.9900" in out
    assert "2  600000.SH  score=80.00  percentile=0.9500" in out
    assert out.index("600003.SH") < out.index("600000.SH")
    # 单门槛通过与其他策略的标的不出现
    assert "600001.SH" not in out
    assert "600002.SH" not in out
    assert "601398.SH" not in out


def test_qualified_top_limit_truncates_items_not_coverage(tmp_path: Path) -> None:
    """--top 截断展示行数，但不改变 limit 之前计算的覆盖度。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)
    _seed_growth_snapshots(snapshot_root)

    result = _qualified_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "growth",
        "--as-of",
        QUALIFIED_CLI_DAY,
        "--top",
        "1",
    )

    assert result.exit_code == 0, result.output
    out = strip_ansi(result.stdout)
    assert "showing: 1" in out
    assert "600003.SH" in out
    assert "600000.SH" not in out
    # 覆盖度仍按全量计算
    assert "qualified=2" in out
    assert "qualified: 2" in out


def _seed_factor_snapshot_only(snapshot_root: Path) -> None:
    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.FACTOR,
        QUALIFIED_CLI_AS_OF,
        (_qualified_cli_factor("600000.SH", "roe_ttm", 9.0),),
    )


# 两行是「所需快照缺失必须响亮失败」同一断言的参数枚举（缺 FACTOR / 缺 STRATEGY）。
QUALIFIED_MISSING_SNAPSHOT_CASES: tuple[
    tuple[str, Callable[[Path], None], str], ...
] = (
    (
        "test_qualified_missing_factor_snapshot",
        lambda snapshot_root: None,
        "FACTOR",
    ),
    (
        "test_qualified_missing_strategy_snapshot",
        _seed_factor_snapshot_only,
        "STRATEGY",
    ),
)


def test_qualified_missing_snapshot_fails_loudly(tmp_path: Path) -> None:
    wrong = []
    for label, seed_snapshots, missing_kind in QUALIFIED_MISSING_SNAPSHOT_CASES:
        case_root = tmp_path / label
        case_root.mkdir()
        snapshot_root = case_root / "snapshots"
        watchlist_root = case_root / "watchlist"
        job_root = case_root / "jobs"
        qualification_dir = _qualification_dir(case_root)
        seed_snapshots(snapshot_root)

        result = _qualified_cli_invoke(
            snapshot_root,
            watchlist_root,
            job_root,
            qualification_dir,
            "qualified",
            "growth",
            "--as-of",
            QUALIFIED_CLI_DAY,
        )

        if result.exit_code == 0:
            wrong.append(
                f"{label}: 期望非零退出，实际 exit_code=0；输出 {result.output!r}"
            )
            continue
        expected_message = f"no {missing_kind} snapshot for {QUALIFIED_CLI_DAY}"
        if expected_message not in strip_ansi(result.output):
            wrong.append(
                f"{label}: 输出缺少 {expected_message!r}；"
                f"实际 {strip_ansi(result.output)!r}"
            )
    assert not wrong, "所需快照缺失未按预期失败:\n" + "\n".join(wrong)


def _write_unapproved_growth_rule(qualification_dir: Path) -> None:
    # 未批准的因子名 → load_canonical_qualifiers 抛 QualificationConfigInvalid
    (qualification_dir / "growth.yaml").write_text(
        "strategy_id: growth\n"
        "version: v1\n"
        "thresholds:\n"
        "  not_an_approved_factor:\n"
        "    min: 1.0\n",
        encoding="utf-8",
    )


# 两行是「请求无法被兑现时必须显式报错、绝不降级为正常屏」同一断言的参数枚举：
# 非法资格配置 fail-closed / 未批准策略显式 not-found。
QUALIFIED_UNHONORABLE_REQUEST_CASES: tuple[
    tuple[str, Callable[[Path], None], str, tuple[str, ...]], ...
] = (
    (
        "test_qualified_invalid_config_fails_closed",
        _write_unapproved_growth_rule,
        "growth",
        ("qualification configuration is invalid", "not_an_approved_factor"),
    ),
    (
        "test_qualified_unknown_strategy_fails_loudly",
        lambda qualification_dir: None,
        "foo",
        ("foo", "no approved qualification rule"),
    ),
)


def test_qualified_unhonorable_requests_fail_loudly(tmp_path: Path) -> None:
    wrong = []
    for (
        label,
        prepare_qualification_dir,
        strategy,
        expected_fragments,
    ) in QUALIFIED_UNHONORABLE_REQUEST_CASES:
        case_root = tmp_path / label
        case_root.mkdir()
        snapshot_root = case_root / "snapshots"
        watchlist_root = case_root / "watchlist"
        job_root = case_root / "jobs"
        qualification_dir = _qualification_dir(case_root)
        _seed_growth_snapshots(snapshot_root)
        prepare_qualification_dir(qualification_dir)

        result = _qualified_cli_invoke(
            snapshot_root,
            watchlist_root,
            job_root,
            qualification_dir,
            "qualified",
            strategy,
            "--as-of",
            QUALIFIED_CLI_DAY,
        )

        if result.exit_code == 0:
            wrong.append(
                f"{label}: 期望非零退出，实际 exit_code=0；输出 {result.output!r}"
            )
            continue
        out = strip_ansi(result.output)
        for fragment in expected_fragments:
            if fragment not in out:
                wrong.append(f"{label}: 输出缺少 {fragment!r}；实际 {out!r}")
        # 绝不降级为正常的零合格屏
        for forbidden in ("qualified:", "showing:"):
            if forbidden in out:
                wrong.append(f"{label}: 不应出现 {forbidden!r}；实际 {out!r}")
    assert not wrong, "无法兑现的请求未按预期失败:\n" + "\n".join(wrong)


def test_qualified_dividend_zero_result_warns(tmp_path: Path) -> None:
    """Step 5: Dividend 零合格 → 退出 0、`qualified: 0`、显式 warning。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)

    store = JsonSnapshotStore(snapshot_root)
    # 现实缺口：股息率因子没有上游数据，快照里没有 dividend_yield_ttm 记录
    store.write(
        SnapshotKind.FACTOR,
        QUALIFIED_CLI_AS_OF,
        (_qualified_cli_factor("000001.SZ", "roe_ttm", 9.0),),
    )
    store.write(
        SnapshotKind.STRATEGY,
        QUALIFIED_CLI_AS_OF,
        (_strategy_result("000001.SZ", strategy_id="dividend", percentile=0.95),),
    )

    result = _qualified_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "dividend",
        "--as-of",
        QUALIFIED_CLI_DAY,
    )

    assert result.exit_code == 0, result.output
    out = strip_ansi(result.output)
    assert "qualified: 0" in out
    assert "warning:" in out
    assert "无任何双门槛通过标的" in out
    assert "showing: 0" in out


def test_qualified_read_only_guarantee(tmp_path: Path) -> None:
    """Step 8: 只读证明——三个根目录的文件与目录集合前后完全一致。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"
    qualification_dir = _qualification_dir(tmp_path)

    watchlist_root.mkdir(parents=True)
    job_root.mkdir(parents=True)
    (snapshot_root / "SENTINEL.txt").parent.mkdir(parents=True, exist_ok=True)
    (snapshot_root / "SENTINEL.txt").write_text("snapshot sentinel", encoding="utf-8")
    (watchlist_root / "SENTINEL.txt").write_text("watchlist sentinel", encoding="utf-8")
    (job_root / "SENTINEL.txt").write_text("job sentinel", encoding="utf-8")
    _seed_growth_snapshots(snapshot_root)

    before = (
        _tree_fingerprint(snapshot_root),
        _tree_fingerprint(watchlist_root),
        _tree_fingerprint(job_root),
    )

    result = _qualified_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        qualification_dir,
        "qualified",
        "growth",
        "--as-of",
        QUALIFIED_CLI_DAY,
    )
    assert result.exit_code == 0, result.output

    after = (
        _tree_fingerprint(snapshot_root),
        _tree_fingerprint(watchlist_root),
        _tree_fingerprint(job_root),
    )
    # 内容哈希、文件集合、目录集合全部一致：没有修改，也没有新建
    assert after == before


# ===========================================================================
# 来源：tests/integration/test_screen_cli.py（9 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 策略选股 CLI 命令集成测试（任务 3）。
#
# 验证：
# - 基于存储快照只读筛选，绝不重算因子或扫描器；
# - 混合策略快照的隔离与 TOP 截断；
# - 缺失 STRATEGY 快照报错与提示；
# - 策略不存在报错与提示；
# - 低覆盖率告警（LOW_COVERAGE_WARNING_RATIO = 0.90）；
# - 合格标的过滤与 --all-results 开关；
# - --min-percentile 百分位过滤；
# - 只读保证：快照、自选与作业目录完全不被修改。
#


SCREEN_CLI_SHANGHAI = ZoneInfo("Asia/Shanghai")


SCREEN_CLI_DAY = "2026-09-17"


SCR_AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=SCREEN_CLI_SHANGHAI)


def _screen_cli_strategy_result(
    symbol: str,
    *,
    strategy_id: str = "growth",
    strategy_version: str = "v1",
    score: float | None = None,
    percentile: float | None = None,
    eligible: bool = True,
) -> StrategyResult:
    return StrategyResult(
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        as_of=SCR_AS_OF,
        eligible=eligible,
        lineage=SnapshotLineage(strategy_version=strategy_version),
        score=score,
        rank_percentile=percentile,
    )


def _screen_cli_invoke(
    snapshot_root: Path,
    watchlist_root: Path,
    job_root: Path,
    *args: str,
) -> Result:
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_SNAPSHOT_ROOT": str(snapshot_root),
            "ASTOCK_WATCHLIST_ROOT": str(watchlist_root),
            "ASTOCK_JOB_ROOT": str(job_root),
        },
    )


def _tree_hashes(directory: Path) -> dict[str, str]:
    """计算目录下所有文件的相对路径和 SHA256，用于断言只读性。"""
    hashes: dict[str, str] = {}
    if not directory.exists():
        return hashes
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(directory))
            content = path.read_bytes()
            hashes[rel] = hashlib.sha256(content).hexdigest()
    return hashes


def test_screen_cli_help() -> None:
    """验证 screen 命令帮助信息与参数声明。"""
    runner = CliRunner()
    result = runner.invoke(app, ["screen", "--help"])
    assert result.exit_code == 0
    help_text = strip_ansi(result.stdout)
    assert "--as-of" in help_text
    assert "--top" in help_text
    assert "--min-percentile" in help_text
    assert "--all-results" in help_text
    # Step 7 文案修复：screen 展示的是策略结果，不是 Candidate
    assert "strategy results" in help_text
    assert "candidates" not in help_text


def test_screen_mixed_strategy_snapshot_top_limit(tmp_path: Path) -> None:
    """Step 1: 混合策略快照中只显示指定策略，且严格应用 top 截断。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    # 写入 growth 与 momentum 混合快照
    growth_results = [
        _screen_cli_strategy_result(
            "600000.SH", strategy_id="growth", score=80.0, percentile=0.95
        ),
        _screen_cli_strategy_result(
            "000001.SZ", strategy_id="growth", score=75.0, percentile=0.90
        ),
        _screen_cli_strategy_result(
            "600519.SH", strategy_id="growth", score=70.0, percentile=0.85
        ),
    ]
    momentum_results = [
        _screen_cli_strategy_result(
            "601398.SH", strategy_id="momentum", score=90.0, percentile=0.98
        ),
        _screen_cli_strategy_result(
            "300750.SZ", strategy_id="momentum", score=85.0, percentile=0.92
        ),
    ]
    store.write(SnapshotKind.STRATEGY, SCR_AS_OF, growth_results + momentum_results)

    result = _screen_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        SCREEN_CLI_DAY,
        "--top",
        "2",
    )

    assert result.exit_code == 0, result.output
    assert f"growth — {SCREEN_CLI_DAY}" in result.stdout
    assert "coverage: total=3 eligible=3 scored=3 ranked=3" in result.stdout
    assert "showing: 2" in result.stdout

    # 包含排名前 2 的 growth 标的
    assert "600000.SH" in result.stdout
    assert "000001.SZ" in result.stdout
    # 被 top=2 截断的第 3 个 growth 标的不在输出中
    assert "600519.SH" not in result.stdout
    # momentum 标的绝不出现
    assert "601398.SH" not in result.stdout
    assert "300750.SZ" not in result.stdout


def _seed_growth_strategy_snapshot(snapshot_root: Path) -> None:
    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.STRATEGY,
        SCR_AS_OF,
        [
            _screen_cli_strategy_result(
                "600000.SH", strategy_id="growth", score=80.0, percentile=0.95
            )
        ],
    )


# 两行是「screen 无法诚实出表时必须响亮失败」同一断言的参数枚举：
# 缺 STRATEGY 快照 / 快照里没有所请求的策略。
SCREEN_UNSERVICEABLE_REQUEST_CASES: tuple[
    tuple[str, Callable[[Path], None], str, str], ...
] = (
    (
        "test_screen_missing_snapshot",
        lambda snapshot_root: None,
        "growth",
        (
            f"no STRATEGY snapshot for {SCREEN_CLI_DAY}\n"
            f"run `astock daily --as-of {SCREEN_CLI_DAY} --allow-incomplete` first"
        ),
    ),
    (
        "test_screen_unknown_strategy",
        _seed_growth_strategy_snapshot,
        "foo",
        f"strategy 'foo' has no stored results for {SCREEN_CLI_DAY}",
    ),
)


def test_screen_unserviceable_requests_fail_loudly(tmp_path: Path) -> None:
    wrong = []
    for (
        label,
        seed_snapshots,
        strategy,
        expected_message,
    ) in SCREEN_UNSERVICEABLE_REQUEST_CASES:
        case_root = tmp_path / label
        case_root.mkdir()
        snapshot_root = case_root / "snapshots"
        watchlist_root = case_root / "watchlist"
        job_root = case_root / "jobs"
        seed_snapshots(snapshot_root)

        result = _screen_cli_invoke(
            snapshot_root,
            watchlist_root,
            job_root,
            "screen",
            strategy,
            "--as-of",
            SCREEN_CLI_DAY,
        )

        if result.exit_code == 0:
            wrong.append(
                f"{label}: 期望非零退出，实际 exit_code=0；输出 {result.output!r}"
            )
            continue
        if expected_message not in result.output:
            wrong.append(
                f"{label}: 输出缺少 {expected_message!r}；实际 {result.output!r}"
            )
    assert not wrong, "screen 无法服侍的请求未按预期失败:\n" + "\n".join(wrong)


def test_screen_low_coverage_warning(tmp_path: Path) -> None:
    """Step 5: scored / total < 0.90 时打印低覆盖率告警。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    # 5 个结果中只有 4 个有分数：4 / 5 = 0.80 < 0.90
    results = [
        _screen_cli_strategy_result("S1", score=80.0, percentile=0.95),
        _screen_cli_strategy_result("S2", score=75.0, percentile=0.90),
        _screen_cli_strategy_result("S3", score=70.0, percentile=0.85),
        _screen_cli_strategy_result("S4", score=65.0, percentile=0.80),
        _screen_cli_strategy_result("S5", score=None, percentile=None),
    ]
    store.write(SnapshotKind.STRATEGY, SCR_AS_OF, results)

    result = _screen_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        SCREEN_CLI_DAY,
        "--all-results",
    )

    assert result.exit_code == 0, result.output
    assert (
        "coverage warning: only 4/5 stored results have a score; "
        "ranking reflects available data" in result.stdout
    )


def test_screen_high_coverage_no_warning(tmp_path: Path) -> None:
    """覆盖率 >= 0.90 时不打印告警。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    results = [
        _screen_cli_strategy_result("S1", score=80.0, percentile=0.95),
        _screen_cli_strategy_result("S2", score=75.0, percentile=0.90),
    ]
    store.write(SnapshotKind.STRATEGY, SCR_AS_OF, results)

    result = _screen_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        SCREEN_CLI_DAY,
    )

    assert result.exit_code == 0, result.output
    assert "coverage warning" not in result.stdout


def test_screen_eligible_filter_and_all_results_flag(tmp_path: Path) -> None:
    """默认仅显示合格标的，--all-results 包含不合格标的。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    results = [
        _screen_cli_strategy_result("AAA", score=80.0, percentile=0.95, eligible=True),
        _screen_cli_strategy_result("BBB", score=90.0, percentile=0.99, eligible=False),
    ]
    store.write(SnapshotKind.STRATEGY, SCR_AS_OF, results)

    # 默认 eligible-only
    res_default = _screen_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        SCREEN_CLI_DAY,
    )
    assert res_default.exit_code == 0
    assert "showing: 1" in res_default.stdout
    assert "AAA" in res_default.stdout
    assert "BBB" not in res_default.stdout

    # --all-results
    res_all = _screen_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        SCREEN_CLI_DAY,
        "--all-results",
    )
    assert res_all.exit_code == 0
    assert "showing: 2" in res_all.stdout
    assert "AAA" in res_all.stdout
    assert "BBB" in res_all.stdout


def test_screen_min_percentile_filter(tmp_path: Path) -> None:
    """--min-percentile 过滤低于阈值的标的。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    store = JsonSnapshotStore(snapshot_root)
    results = [
        _screen_cli_strategy_result("AAA", score=80.0, percentile=0.96),
        _screen_cli_strategy_result("BBB", score=75.0, percentile=0.94),
        _screen_cli_strategy_result("CCC", score=70.0, percentile=0.80),
    ]
    store.write(SnapshotKind.STRATEGY, SCR_AS_OF, results)

    res = _screen_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        SCREEN_CLI_DAY,
        "--min-percentile",
        "0.95",
    )
    assert res.exit_code == 0
    assert "showing: 1" in res.stdout
    assert "AAA" in res.stdout
    assert "BBB" not in res.stdout
    assert "CCC" not in res.stdout


def test_screen_read_only_guarantee(tmp_path: Path) -> None:
    """Step 6: 只读保证——执行前后快照、自选与作业目录完全无变化。"""
    snapshot_root = tmp_path / "snapshots"
    watchlist_root = tmp_path / "watchlist"
    job_root = tmp_path / "jobs"

    snapshot_root.mkdir(parents=True)
    watchlist_root.mkdir(parents=True)
    job_root.mkdir(parents=True)

    # 放置哨兵文件
    (snapshot_root / "SENTINEL.txt").write_text("snapshot sentinel", encoding="utf-8")
    (watchlist_root / "SENTINEL.txt").write_text("watchlist sentinel", encoding="utf-8")
    (job_root / "SENTINEL.txt").write_text("job sentinel", encoding="utf-8")

    store = JsonSnapshotStore(snapshot_root)
    store.write(
        SnapshotKind.STRATEGY,
        SCR_AS_OF,
        [_screen_cli_strategy_result("600000.SH", score=80.0, percentile=0.95)],
    )

    # 记录执行前哈希
    hashes_snapshot_before = _tree_hashes(snapshot_root)
    hashes_watchlist_before = _tree_hashes(watchlist_root)
    hashes_job_before = _tree_hashes(job_root)

    # 执行 screen
    result = _screen_cli_invoke(
        snapshot_root,
        watchlist_root,
        job_root,
        "screen",
        "growth",
        "--as-of",
        SCREEN_CLI_DAY,
    )
    assert result.exit_code == 0

    # 验证执行后哈希完全一致
    assert _tree_hashes(snapshot_root) == hashes_snapshot_before
    assert _tree_hashes(watchlist_root) == hashes_watchlist_before
    assert _tree_hashes(job_root) == hashes_job_before


# ===========================================================================
# 来源：tests/integration/test_today_cli.py（4 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# Integration tests for `astock today` CLI command.
#
# Plan: docs/superpowers/plans/2026-09-21-candidate-today-query-experience.md Task 4
# Spec: docs/superpowers/specs/2026-09-21-candidate-correctness-product-query-design.md
#


today_cli_runner = CliRunner()


TODAY_CLI_AS_OF = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)


def _today_cli_make_candidate(
    symbol: str,
    *,
    primary_strategy_id: str = "momentum",
    qualified_strategies: tuple[str, ...] = ("momentum",),
    market_validation: MarketValidation | None = MarketValidation.CONFIRMED,
    signal: Signal | None = Signal.BREAKOUT,
    next_action: NextAction = NextAction.WATCH,
    risks: tuple[str, ...] = (),
) -> Candidate:
    quals = tuple(
        StrategyQualification(
            symbol=symbol,
            strategy_id=s_id,
            strategy_version="v1",
            qualification_version="v1",
            qualified=True,
            percentile_pass=True,
            absolute_pass=True,
            rank_percentile=0.95,
            as_of=TODAY_CLI_AS_OF,
        )
        for s_id in qualified_strategies
    )
    s_results = tuple(
        StrategyResult(
            symbol=symbol,
            strategy_id=s_id,
            strategy_version="v1",
            as_of=TODAY_CLI_AS_OF,
            eligible=True,
            score=88.0,
            rank_percentile=0.95,
            lineage=SnapshotLineage(strategy_version="v1"),
        )
        for s_id in qualified_strategies
    )
    return Candidate(
        symbol=symbol,
        as_of=TODAY_CLI_AS_OF,
        next_action=next_action,
        lineage=SnapshotLineage(
            strategy_version="v1",
            qualification_version="v1",
            candidate_policy_version="v1",
            regime_version="v1",
            market_validation_version="v1",
            signal_version="v1",
            universe_snapshot="2026-09-19:u1",
        ),
        primary_strategy_id=primary_strategy_id,
        strategy_qualifications=quals,
        strategy_results=s_results,
        market_validation=market_validation,
        signal=signal,
        reasons=(f"qualified for {primary_strategy_id}",),
        risks=risks,
    )


def test_today_cli_missing_snapshot_fails_explicitly(
    local_tmp: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(local_tmp / "snapshots"))
    result = today_cli_runner.invoke(app, ["today", "--as-of", "2026-09-01"])
    assert result.exit_code != 0
    assert "no CANDIDATE snapshot for 2026-09-01" in result.output


def test_today_cli_empty_snapshot_exits_zero(local_tmp: Path, monkeypatch) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)
    store.write(SnapshotKind.CANDIDATE, TODAY_CLI_AS_OF, [])
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))

    result = today_cli_runner.invoke(app, ["today", "--as-of", "2026-09-19"])
    assert result.exit_code == 0
    assert "candidates: 0" in result.output


def test_today_cli_exact_aggregation_and_top_order(
    local_tmp: Path, monkeypatch
) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)

    candidates = [
        _today_cli_make_candidate(
            "601336.SH",
            primary_strategy_id="value",
            qualified_strategies=("value", "garp"),
            market_validation=MarketValidation.NEUTRAL,
            signal=Signal.VALUE_CONTRARIAN,
        ),
        _today_cli_make_candidate(
            "300741.SZ",
            primary_strategy_id="momentum",
            market_validation=MarketValidation.CONFIRMED,
            signal=Signal.BREAKOUT,
        ),
        _today_cli_make_candidate(
            "688617.SH",
            primary_strategy_id="growth",
            market_validation=MarketValidation.NEUTRAL,
            signal=Signal.TREND_WEAKEN,
            risks=("技术信号提示走弱风险 (TREND_WEAKEN)",),
        ),
    ]
    store.write(SnapshotKind.CANDIDATE, TODAY_CLI_AS_OF, candidates)
    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))

    result = today_cli_runner.invoke(app, ["today", "--as-of", "2026-09-19"])
    assert result.exit_code == 0
    output = result.output

    # 验证关键聚合数字与分类
    assert "candidates: 3" in output
    assert "value: 1" in output
    assert "momentum: 1" in output
    assert "growth: 1" in output
    assert "CONFIRMED: 1" in output
    assert "NEUTRAL: 2" in output
    assert "VALUE_CONTRARIAN: 1" in output
    assert "BREAKOUT: 1" in output
    assert "TREND_WEAKEN: 1" in output

    # 验证 Top 列表保持原生存储顺序
    idx_val = output.find("601336.SH")
    idx_mom = output.find("300741.SZ")
    idx_gro = output.find("688617.SH")
    assert idx_val != -1 and idx_mom != -1 and idx_gro != -1
    assert idx_val < idx_mom < idx_gro


def test_today_cli_is_strictly_read_only(local_tmp: Path, monkeypatch) -> None:
    snap_root = local_tmp / "snapshots"
    store = JsonSnapshotStore(snap_root)
    c = _today_cli_make_candidate("600519.SH")
    store.write(SnapshotKind.CANDIDATE, TODAY_CLI_AS_OF, [c])
    snap_file = store.path_for(SnapshotKind.CANDIDATE, TODAY_CLI_AS_OF)
    initial_bytes = snap_file.read_bytes()
    initial_mtime = snap_file.stat().st_mtime_ns

    monkeypatch.setenv("ASTOCK_SNAPSHOT_ROOT", str(snap_root))
    result = today_cli_runner.invoke(app, ["today", "--as-of", "2026-09-19"])
    assert result.exit_code == 0

    assert snap_file.read_bytes() == initial_bytes
    assert snap_file.stat().st_mtime_ns == initial_mtime


# ===========================================================================
# 来源：tests/integration/test_trade_gate_cli.py（1 例）
# ===========================================================================


def test_trade_commands_are_registered() -> None:
    result = CliRunner().invoke(app, ["trade", "--help"])
    assert result.exit_code == 0
    for name in ("evaluate", "show", "override", "execute", "review", "stats"):
        assert name in result.stdout


# ===========================================================================
# 来源：tests/integration/test_valuation_backfill_cli.py（7 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# 估值补抓与覆盖报告的 CLI 集成测试。
#
# 这条链路存在的理由：源端一批只回 1–2 只，2,303 只研究池必须多轮补齐。
# 所以四件事必须钉住：
#
# 1. 多轮补抓是合并的——后一轮不冲掉前一轮；
# 2. 第二轮只请求仍然缺的标的，已覆盖的不重复问；
# 3. 缺口没补完时退出码 1，缺口清单落盘；全覆盖时退出码 0；
# 4. 覆盖报告的分母是显式研究池，不是"已落地的标的"。
#
# 全程不联网：provider 由假源替换，只回放构造的内容块。
#


AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


VBF_DAY = "2026-09-17"


VALUATION_BACKFILL_ROOT = Path(__file__).resolve().parents[2]


NEODATA_FIXTURES = VALUATION_BACKFILL_ROOT / "tests" / "fixtures" / "neodata"


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


def _valuation_backfill_invoke(
    local_tmp: Path,
    monkeypatch: object,
    source: object,
    *args: str,
) -> object:
    monkeypatch.setattr(
        app_module,
        "_neodata_provider",
        # 签名要与被替换的 `_neodata_provider(batch_size=…)` 对齐。
        lambda batch_size=None: source,
    )  # type: ignore[attr-defined]
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

    result = _valuation_backfill_invoke(
        local_tmp,
        monkeypatch,
        source,
        "sync-valuation",
        "--as-of",
        VBF_DAY,
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
    landed = (local_tmp / "neodata" / "valuation" / f"{VBF_DAY}.csv").read_text(
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

    result = _valuation_backfill_invoke(
        local_tmp,
        monkeypatch,
        source,
        "sync-valuation",
        "--as-of",
        VBF_DAY,
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

    first = _valuation_backfill_invoke(
        local_tmp,
        monkeypatch,
        source,
        "sync-valuation",
        "--as-of",
        VBF_DAY,
        "--universe",
        str(universe),
    )
    second = _valuation_backfill_invoke(
        local_tmp,
        monkeypatch,
        source,
        "sync-valuation",
        "--as-of",
        VBF_DAY,
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
    result = _valuation_backfill_invoke(
        local_tmp,
        monkeypatch,
        CompleteSource(),
        "sync-valuation",
        "--as-of",
        VBF_DAY,
        "--universe",
        str(local_tmp / "nope.json"),
    )

    assert result.exit_code == 1
    assert "研究池名单不存在" in result.output


def test_a_non_positive_batch_size_is_refused(
    local_tmp: Path, monkeypatch: object
) -> None:
    universe = _write_universe(local_tmp, ("600519.SH",))

    result = _valuation_backfill_invoke(
        local_tmp,
        monkeypatch,
        CompleteSource(),
        "sync-valuation",
        "--as-of",
        VBF_DAY,
        "--universe",
        str(universe),
        "--batch-size",
        "0",
    )

    assert result.exit_code == 2
    assert "batch-size" in strip_ansi(result.output)


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
    _write_blocks(local_tmp / "neodata" / "valuation" / f"{VBF_DAY}.csv", blocks)

    result = _valuation_backfill_invoke(
        local_tmp,
        monkeypatch,
        CompleteSource(),
        "valuation-coverage",
        "--as-of",
        VBF_DAY,
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

    result = _valuation_backfill_invoke(
        local_tmp,
        monkeypatch,
        CompleteSource(),
        "valuation-coverage",
        "--as-of",
        VBF_DAY,
        "--universe",
        str(path),
    )

    assert result.exit_code == 1
    assert "research_symbols" in result.output
