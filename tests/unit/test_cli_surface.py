"""CLI 表层（命令、行业装载器、研究适配器）长尾用例。

本文件由 Task 12「文件合并」把以下 3 个同域小文件整体搬入：
    - tests/unit/test_cli.py（9 例）
    - tests/unit/test_cli_industry_loader.py（7 例）
    - tests/unit/test_cli_research_adapter.py（9 例）
每个 `def test_*` 函数体逐字节未改；同名私有 helper / 常量 / fixture 加域前缀重命名并同步
改写引用点；各来源文件的模块 docstring 折为分节注释（内容逐字）。
"""

import json
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from astock_lens.cli.app import _latest_industry_file, _production_industry_map, app
from astock_lens.data.industry import IndustryMembershipAmbiguous
from astock_lens.research.adapters.cli import (
    COMMAND_ENV,
    CliDeepResearchAdapter,
    DeepResearchInvocationError,
    DeepResearchNotConfigured,
    resolve_adapter,
)
from astock_lens.research.models import ResearchJob, ResearchJobStatus, ResearchSummary

# ===========================================================================
# 来源：tests/unit/test_cli.py（9 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# CLI tests.
#
# The rule these tests pin down: the CLI is a first-class surface. A scan can be
# driven from cron or an agent with no Web UI, and it must fail loudly rather
# than print a reassuring summary for a run that did nothing.
#


ROOT = Path(__file__).resolve().parents[2]


CSV_ROOT = ROOT / "tests" / "fixtures" / "csv"


DAY = "2026-09-04"


# The short fixture carries 25 bars: enough for a 20-day window, not enough for
# the 60-day or 52-week momentum factors. The scan therefore runs against the
# long fixture, and the factor listing runs against the short one to keep its
# expected output small.
SHORT_DATASET = "daily_bars"


LONG_DATASET = "daily_bars_long"


SHORT_SYMBOLS = {"600000.SH", "000001.SZ", "600519.SH", "601398.SH"}


FACTOR_NAMES = {path.stem for path in (ROOT / "configs" / "factors").glob("*.yaml")}


def _invoke(local_tmp: Path, *args: str, dataset: str = SHORT_DATASET) -> Result:
    return CliRunner().invoke(
        app,
        list(args),
        env={
            "ASTOCK_CSV_ROOT": str(CSV_ROOT),
            "ASTOCK_SNAPSHOT_ROOT": str(local_tmp),
            "ASTOCK_DATASET": dataset,
        },
    )


# 「命令可运行且打印点名字样」两行：行序与原用例一致，label 即原测试名。
# 列 = label, args, expected：比对方式与原断言同为逐片段 `in result.stdout`。
STARTUP_COMMAND_CASES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # test_cli_help:
    ("test_cli_help", ("--help",), ("doctor", "scan")),
    # test_doctor_reports_the_factor_set_and_its_weights:
    (
        "test_doctor_reports_the_factor_set_and_its_weights",
        ("doctor",),
        ("factors:", "weights:"),
    ),
)


def test_startup_commands_report_their_surface() -> None:
    """原 2 条「--help / doctor」用例收表：退出码 0，且各自字样出现在 stdout。"""
    wrong = []
    for label, args, expected in STARTUP_COMMAND_CASES:
        result = CliRunner().invoke(app, list(args))
        if result.exit_code != 0:
            wrong.append(f"{label}: exit_code={result.exit_code}，期望 0")
            continue
        for fragment in expected:
            if fragment not in result.stdout:
                wrong.append(f"{label}: stdout 缺少 {fragment!r}")
    assert not wrong, "CLI 表层命令输出不符:\n" + "\n".join(wrong)


def test_factors_compute_prints_one_document_per_symbol_and_factor(
    local_tmp: Path,
) -> None:
    result = _invoke(local_tmp, "factors", "compute", "--as-of", DAY)

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    payloads = [json.loads(line) for line in lines]

    assert {payload["symbol"] for payload in payloads} == SHORT_SYMBOLS
    assert {payload["factor"] for payload in payloads} == FACTOR_NAMES
    assert len(lines) == len(SHORT_SYMBOLS) * len(FACTOR_NAMES)


# 「预览命令不落盘」两行：行序与原用例一致，label 即原测试名，docstring 逐字保留为行注释。
# 列 = label, args, expected：
#   - `args` 逐字取自原 `_invoke(local_tmp, ...)` 调用（dataset 同为 LONG_DATASET）；
#   - 比对方式与原断言同为逐片段 `in result.stdout`，落盘检查逐行点名 label。
PREVIEW_WITHOUT_WRITE_CASES: tuple[
    tuple[str, tuple[str, ...], tuple[str, ...]], ...
] = (
    # test_scan_reports_a_ranking_and_writes_no_snapshot:
    #   `scan` 是预览：6 只通过 Universe 的标的全部被打分，但不落盘。
    #
    #   2026-09-18 起北交所不在 Universe 的交易所清单里，所以样本从 7 只变 6 只，
    #   横截面排名的百分位随之改变（第一名的分数也因此从 95.24 变成 94.44）。
    (
        "test_scan_reports_a_ranking_and_writes_no_snapshot",
        ("scan", "--as-of", DAY),
        (
            "universe: 6 symbols considered",
            # 排名第一：涨得最快的标的，有分数、资格成立。
            "300750.SZ score 94.44 (eligible)",
        ),
    ),
    # test_universe_build_reports_the_verdicts_without_writing:
    (
        "test_universe_build_reports_the_verdicts_without_writing",
        ("universe", "build", "--as-of", DAY),
        ("included: 6", "ST: 1", "LONG_SUSPENSION"),
    ),
)


def test_preview_commands_report_their_verdicts_and_write_no_snapshot(
    local_tmp: Path,
) -> None:
    """原 2 条「预览不落盘」用例收表：退出码 0、各自字样出现、且不写任何 json。"""
    wrong = []
    for label, args, expected in PREVIEW_WITHOUT_WRITE_CASES:
        result = _invoke(local_tmp, *args, dataset=LONG_DATASET)
        if result.exit_code != 0:
            wrong.append(f"{label}: exit_code={result.exit_code}，期望 0")
            continue
        for fragment in expected:
            if fragment not in result.stdout:
                wrong.append(f"{label}: stdout 缺少 {fragment!r}")
        written = list(local_tmp.rglob("*.json"))
        if written:
            wrong.append(f"{label}: 预览命令写了快照 {written!r}")
    assert not wrong, "预览命令输出不符:\n" + "\n".join(wrong)


def test_scan_reports_every_candidate_with_a_score(local_tmp: Path) -> None:
    """Cross-sectional scoring means every candidate line carries a number;
    a bare symbol with no score would mean the scan ranked nothing."""
    result = _invoke(local_tmp, "scan", "--as-of", DAY, dataset=LONG_DATASET)

    candidate_lines = [
        line
        for line in result.stdout.splitlines()
        if line.strip().startswith(("6", "0", "3", "8", "9"))
    ]
    assert candidate_lines
    assert all("score" in line for line in candidate_lines)


def test_scan_rejects_a_malformed_date(local_tmp: Path) -> None:
    result = _invoke(local_tmp, "scan", "--as-of", "not-a-date")

    assert result.exit_code != 0
    assert "YYYY-MM-DD" in result.output


def test_calendar_commands_report_trading_status(local_tmp: Path) -> None:
    """astock calendar 子命令可以查询是否休市及最新交易日。"""
    # 2026-09-19 周六休市
    result_sat = _invoke(local_tmp, "calendar", "is-open", "--date", "2026-09-19")
    assert result_sat.exit_code == 0
    assert "closed" in result_sat.stdout.lower() or "休市" in result_sat.stdout

    # 2026-09-18 周五正常交易
    result_fri = _invoke(local_tmp, "calendar", "is-open", "--date", "2026-09-18")
    assert result_fri.exit_code == 0
    assert "open" in result_fri.stdout.lower() or "开市" in result_fri.stdout

    # 查询周六的最近交易日为周五
    result_latest = _invoke(local_tmp, "calendar", "latest", "--date", "2026-09-19")
    assert result_latest.exit_code == 0
    assert "2026-09-18" in result_latest.stdout


def test_sync_research_on_non_trading_day_skips_market_sync(local_tmp: Path) -> None:
    """休市日执行 sync-research 时跳过行情抓取并优雅返回。"""
    result = _invoke(local_tmp, "sync-research", "--as-of", "2026-09-19")
    assert result.exit_code == 0
    assert "non-trading day" in result.stdout.lower() or "休市" in result.stdout


# ===========================================================================
# 来源：tests/unit/test_cli_industry_loader.py（7 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
#


def _write_industry_csv(
    dir_path: Path, filename: str, rows: list[tuple[str, str, str, str]]
) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / filename
    lines = ["symbol,industry_id,industry_name,as_of,provider,source_ref\n"]
    for sym, ind_id, ind_name, as_of_str in rows:
        lines.append(f"{sym},{ind_id},{ind_name},{as_of_str},westock-cli,\n")
    file_path.write_text("".join(lines), encoding="utf-8")
    return file_path


# 「选文件 + 出映射」两行：行序与原用例一致，label 即原测试名，docstring 逐字保留为行注释。
# 列 = label, files, expected_file, expected_mapping：
#   - `files` 是 (文件名, 行) 序列，逐字取自原两次 `_write_industry_csv` 调用；
#   - `expected_mapping` 逐行按键取值 `==` 比名字（与原断言同为 `[]` 访问 + `==`）；
#   - 每行用独立子目录复现原用例各自的空 `tmp_path`。
INDUSTRY_FILE_SELECTION_CASES: tuple[
    tuple[
        str,
        tuple[tuple[str, list[tuple[str, str, str, str]]], ...],
        str,
        tuple[tuple[str, str], ...],
    ],
    ...,
] = (
    # test_step1_exact_date:
    #   Step 1: When an exact-date industry file exists, it must be selected.
    (
        "test_step1_exact_date",
        (
            (
                "2026-09-01.csv",
                [("000001.SZ", "sw2_bank", "银行", "2026-09-01T15:00:00+00:00")],
            ),
            (
                "2026-09-02.csv",
                [
                    ("000001.SZ", "sw2_bank", "银行", "2026-09-02T15:00:00+00:00"),
                    (
                        "000002.SZ",
                        "sw2_realestate",
                        "房地产",
                        "2026-09-02T15:00:00+00:00",
                    ),
                ],
            ),
        ),
        "2026-09-02.csv",
        (("000001.SZ", "银行"), ("000002.SZ", "房地产")),
    ),
    # test_step2_latest_prior_date:
    #   Step 2: When no exact-date file exists, latest prior date must be chosen.
    (
        "test_step2_latest_prior_date",
        (
            (
                "2026-08-30.csv",
                [("000001.SZ", "sw2_bank", "银行", "2026-08-30T15:00:00+00:00")],
            ),
            (
                "2026-09-01.csv",
                [
                    ("000001.SZ", "sw2_bank", "银行", "2026-09-01T15:00:00+00:00"),
                    ("600519.SH", "sw2_liquor", "白酒", "2026-09-01T15:00:00+00:00"),
                ],
            ),
        ),
        "2026-09-01.csv",
        (("000001.SZ", "银行"), ("600519.SH", "白酒")),
    ),
)


def test_industry_file_selection_and_mapping(tmp_path: Path) -> None:
    """原 2 条「精确日期 / 最近先前日期」用例收表：选中的文件与映射逐行断言。"""
    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    wrong = []
    for label, files, expected_file, expected_mapping in INDUSTRY_FILE_SELECTION_CASES:
        case_root = tmp_path / label
        case_root.mkdir()
        industry_dir = case_root / "westock" / "industry"
        for filename, rows in files:
            _write_industry_csv(industry_dir, filename, rows)

        selected = _latest_industry_file(day, root=case_root)
        if selected != industry_dir / expected_file:
            wrong.append(f"{label}: selected 得到 {selected!r}，期望 {expected_file!r}")
            continue
        mapping = _production_industry_map(day, root=case_root)
        for symbol, industry in expected_mapping:
            if mapping[symbol] != industry:
                wrong.append(
                    f"{label}: mapping[{symbol!r}] 得到 {mapping[symbol]!r}，"
                    f"期望 {industry!r}"
                )
    assert not wrong, "行业文件选择与映射不符:\n" + "\n".join(wrong)


# 「不合格文件不参与选择」两行：行序与原用例一致，label 即原测试名，docstring 逐字保留。
# 列 = label, files, extra_files, expected_file：
#   - `files` 逐字取自原 `_write_industry_csv` 调用，`extra_files` 逐字承接原
#     直接 `write_text` 的旁路文件（内容逐字）；
#   - 选中结果与原断言同为 `==`；每行用独立子目录复现原用例各自的空 `tmp_path`。
NON_ELIGIBLE_FILE_CASES: tuple[
    tuple[
        str,
        tuple[tuple[str, list[tuple[str, str, str, str]]], ...],
        tuple[tuple[str, str], ...],
        str,
    ],
    ...,
] = (
    # test_step3_future_date_exclusion:
    #   Step 3: Files dated after target as_of date must be strictly excluded.
    (
        "test_step3_future_date_exclusion",
        (
            (
                "2026-09-01.csv",
                [("000001.SZ", "sw2_bank", "银行", "2026-09-01T15:00:00+00:00")],
            ),
            (
                "2026-09-03.csv",
                [("000001.SZ", "sw2_bank", "银行新版", "2026-09-03T15:00:00+00:00")],
            ),
        ),
        (),
        "2026-09-01.csv",
    ),
    # test_ignores_non_iso_date_csv:
    #   Non-ISO-date CSV files (e.g. metadata.csv) are ignored safely.
    (
        "test_ignores_non_iso_date_csv",
        (
            (
                "2026-09-01.csv",
                [("000001.SZ", "sw2_bank", "银行", "2026-09-01T15:00:00+00:00")],
            ),
        ),
        (("latest.csv", "dummy"), ("README.md", "docs")),
        "2026-09-01.csv",
    ),
)


def test_non_eligible_files_are_ignored(tmp_path: Path) -> None:
    """原 2 条「未来日期 / 非 ISO 文件名」用例收表：选中结果仍是 09-01 那行。"""
    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    wrong = []
    for label, files, extra_files, expected_file in NON_ELIGIBLE_FILE_CASES:
        case_root = tmp_path / label
        case_root.mkdir()
        industry_dir = case_root / "westock" / "industry"
        for filename, rows in files:
            _write_industry_csv(industry_dir, filename, rows)
        for filename, content in extra_files:
            (industry_dir / filename).write_text(content, encoding="utf-8")

        selected = _latest_industry_file(day, root=case_root)
        if selected != industry_dir / expected_file:
            wrong.append(f"{label}: selected 得到 {selected!r}，期望 {expected_file!r}")
    assert not wrong, "不合格文件被错误选中:\n" + "\n".join(wrong)


def test_step4_no_data_raises_file_not_found(tmp_path: Path) -> None:
    """Step 4: When no eligible files exist, FileNotFoundError must be raised."""
    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

    # Empty directory
    with pytest.raises(
        FileNotFoundError,
        match="No eligible industry file found in .* for date 2026-09-02",
    ):
        _latest_industry_file(day, root=tmp_path)

    # Directory with only future files
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-09-05.csv",
        [("000001.SZ", "sw2_bank", "银行", "2026-09-05T15:00:00+00:00")],
    )
    with pytest.raises(
        FileNotFoundError,
        match="No eligible industry file found in .* for date 2026-09-02",
    ):
        _latest_industry_file(day, root=tmp_path)

    with pytest.raises(
        FileNotFoundError,
        match="No eligible industry file found in .* for date 2026-09-02",
    ):
        _production_industry_map(day, root=tmp_path)


def test_ambiguous_membership_fails_closed(tmp_path: Path) -> None:
    """Step 5: Ambiguous membership (same symbol in different industries) raises IndustryMembershipAmbiguous."""
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-09-02.csv",
        [
            ("000001.SZ", "sw2_bank", "银行", "2026-09-02T15:00:00+00:00"),
            ("000001.SZ", "sw2_realestate", "房地产", "2026-09-02T15:00:00+00:00"),
        ],
    )

    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    with pytest.raises(IndustryMembershipAmbiguous):
        _production_industry_map(day, root=tmp_path)


def test_includes_supplemental_industry_memberships(tmp_path: Path) -> None:
    """Step 5: Supplements from configuration are loaded and merged."""
    industry_dir = tmp_path / "westock" / "industry"
    _write_industry_csv(
        industry_dir,
        "2026-09-02.csv",
        [("000001.SZ", "sw2_bank", "银行", "2026-09-02T15:00:00+00:00")],
    )

    day = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    mapping = _production_industry_map(day, root=tmp_path)
    assert mapping["000001.SZ"] == "银行"
    # 000592.SZ is defined in configs/industry_supplement.yaml as 林业Ⅱ
    assert mapping.get("000592.SZ") == "林业Ⅱ"


# ===========================================================================
# 来源：tests/unit/test_cli_research_adapter.py（9 例）
# ===========================================================================
# 模块 docstring（逐字折为注释）：
# CLI deep research adapter tests.
#
# `spec §14` keeps `a-share-deep-research` behind an adapter, and
# `ARCHITECTURE.md` §13.2 forbids the Python-level dependency. The rule that
# matters here is that the boundary is honest: job states are passed through
# unchanged because they belong to the other system, and a command that fails
# produces an error — never a fabricated job, status or summary.
#


AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


RESPONDER = """
import json, sys

payload = json.load(sys.stdin)
action = payload["action"]

if action == "submit":
    print(json.dumps({
        "job_id": "job-1",
        "symbol": payload["request"]["symbol"],
        "submitted_at": "2026-09-04T15:05:00+00:00",
    }))
elif action == "status":
    print(json.dumps({
        "job_id": payload["job_id"],
        "state": "InProgress",
        "observed_at": "2026-09-04T15:06:00+00:00",
        "is_terminal": False,
    }))
else:
    print(json.dumps({
        "job_id": payload["job_id"],
        "symbol": "600519.SH",
        "completed_at": "2026-09-04T16:00:00+00:00",
        "summary": "channel inventory still rebuilding",
        "artifact_reference": "reports/600519.SH.md",
    }))
"""


def _command(script: str) -> str:
    return shlex.join([sys.executable, "-c", script])


def _adapter(script: str = RESPONDER) -> CliDeepResearchAdapter:
    return CliDeepResearchAdapter(command=_command(script))


def test_submit_returns_the_job_the_command_reported() -> None:
    from astock_lens.research.models import ResearchRequest

    job = _adapter().submit(ResearchRequest(symbol="600519.SH", as_of=AS_OF))

    assert isinstance(job, ResearchJob)
    assert job.job_id == "job-1"
    assert job.symbol == "600519.SH"
    assert job.submitted_at == datetime(2026, 9, 4, 15, 5, tzinfo=UTC)


def test_the_request_travels_to_the_command_unchanged() -> None:
    echo = _command(
        "import json,sys;"
        "p=json.load(sys.stdin);"
        "r=p['request'];"
        "print(json.dumps({'job_id': r['thesis'], 'symbol': r['symbol'],"
        " 'submitted_at': '2026-09-04T15:05:00+00:00'}))"
    )
    from astock_lens.research.models import ResearchRequest

    job = CliDeepResearchAdapter(command=echo).submit(
        ResearchRequest(symbol="600519.SH", as_of=AS_OF, thesis="brand moat")
    )

    assert job.job_id == "brand moat"


def test_status_passes_the_state_through_unchanged() -> None:
    status = _adapter().status("job-1")

    assert isinstance(status, ResearchJobStatus)
    # `InProgress` is the other system's vocabulary, not ours to rename.
    assert status.state == "InProgress"
    assert status.is_terminal is False
    assert status.job_id == "job-1"


def test_result_returns_the_summary_and_the_artifact_reference() -> None:
    summary = _adapter().result("job-1")

    assert isinstance(summary, ResearchSummary)
    assert summary.summary == "channel inventory still rebuilding"
    assert summary.artifact_reference == "reports/600519.SH.md"
    assert summary.completed_at == datetime(2026, 9, 4, 16, 0, tzinfo=UTC)


def test_an_unconfigured_command_is_refused_by_name() -> None:
    with pytest.raises(DeepResearchNotConfigured):
        CliDeepResearchAdapter(command="")

    with pytest.raises(DeepResearchNotConfigured):
        resolve_adapter(None, environ={})


def test_the_command_is_read_from_the_environment() -> None:
    adapter = resolve_adapter(None, environ={COMMAND_ENV: _command(RESPONDER)})

    assert adapter.status("job-1").state == "InProgress"


def test_a_failing_command_reports_the_failure_instead_of_a_result() -> None:
    failing = _command("import sys; sys.stderr.write('no token'); sys.exit(3)")

    with pytest.raises(DeepResearchInvocationError) as raised:
        CliDeepResearchAdapter(command=failing).status("job-1")

    assert "3" in str(raised.value)
    assert "no token" in str(raised.value)


def test_unreadable_output_is_refused_instead_of_guessed() -> None:
    noisy = _command("print('not json at all')")

    with pytest.raises(DeepResearchInvocationError, match="JSON"):
        CliDeepResearchAdapter(command=noisy).status("job-1")


def test_an_incomplete_payload_is_refused() -> None:
    partial = _command("import json; print(json.dumps({'job_id': 'job-1'}))")

    with pytest.raises(Exception, match="state"):
        CliDeepResearchAdapter(command=partial).status("job-1")
