"""WeStock CLI provider tests.

These tests replay recorded command output, so they need no Node.js, no
network and no WeStock binary — the same rule the AkShare provider tests
follow. What they pin down is the part a fixture cannot show by itself:

- `--fields all` is always requested, because the default field set omits the
  publication date that makes a financial record point-in-time usable;
- coverage is established by comparing requested codes with returned codes,
  never by the CLI's own batch summary (it says success even when nothing came
  back);
- cells stay verbatim — a `-` stays `-`, a number stays a string;
- a source problem is reported through `status`, and a caller problem raises.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest
from astock_lens.data.providers.westock import (
    BINARY_ENV,
    CommandResult,
    MalformedTable,
    WestockCliProvider,
    from_westock_code,
    parse_tables,
    to_westock_code,
)
from astock_lens.domain.enums import DataStatus

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "westock"
AS_OF = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)

DATASETS = ("financial_income", "financial_balance", "financial_cashflow")
FIXTURE_SYMBOLS = ("600519.SH", "000001.SZ", "300750.SZ")


class ReplayRunner:
    """Replay recorded output and remember every argv it was handed."""

    def __init__(
        self,
        stdout: str = "",
        *,
        returncode: int = 0,
        stderr: str = "",
        by_code: str | None = None,
    ) -> None:
        self.argv: list[list[str]] = []
        self._stdout = stdout
        self._returncode = returncode
        self._stderr = stderr
        # When set, only a batch containing this code gets the recorded output;
        # every other batch answers with nothing.
        self._by_code = by_code

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        self.argv.append(list(argv))
        if self._by_code is not None and self._by_code not in argv[2]:
            return CommandResult(returncode=0, stdout="", stderr="")
        return CommandResult(
            returncode=self._returncode, stdout=self._stdout, stderr=self._stderr
        )


def _recorded(dataset: str) -> str:
    return (FIXTURES / f"{dataset}.md").read_text(encoding="utf-8")


def _markdown(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> str:
    """A minimal table, for shapes the recordings do not contain."""
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    return f"{header}\n{separator}\n{body}\n"


def _request(dataset: str, symbols: Sequence[str] = FIXTURE_SYMBOLS) -> FetchRequest:
    return FetchRequest(dataset=dataset, as_of=AS_OF, symbols=tuple(symbols))


def _provider(
    runner: ReplayRunner, *, binary: str = "/opt/westock", **kwargs: object
) -> WestockCliProvider:
    return WestockCliProvider(binary, runner=runner, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("dataset", DATASETS)
def test_every_recorded_statement_parses_into_one_table(dataset: str) -> None:
    tables = parse_tables(_recorded(dataset))

    assert len(tables) == 1
    columns = tables[0].columns
    assert "EndDate" in columns
    assert "InfoPublDate" in columns
    assert "code" in columns
    assert len(tables[0].rows) == 24  # three symbols, eight periods


def test_fetch_returns_the_recorded_cells_verbatim() -> None:
    runner = ReplayRunner(_recorded("financial_income"))

    raw = _provider(runner).fetch(_request("financial_income"))

    assert raw.status is DataStatus.VALUE
    assert raw.row_count == 24
    assert raw.missing_symbols == ()
    assert raw.payload is not None
    assert "InfoPublDate" in raw.payload.columns
    # Raw keeps the source shape: cells stay strings, and a missing marker stays
    # a missing marker instead of becoming a number.
    published = raw.payload.columns.index("InfoPublDate")
    assert all(isinstance(row[published], str) for row in raw.payload.rows)
    assert any("-" in row for row in raw.payload.rows)


def test_the_publication_field_is_always_requested() -> None:
    """`core` omits InfoPublDate, so the field set is not a caller's choice."""
    runner = ReplayRunner(_recorded("financial_income"))

    _provider(runner, periods=8).fetch(_request("financial_income"))

    argv = runner.argv[0]
    assert argv[1:3] == ["finance", "sh600519,sz000001,sz300750"]
    assert argv[argv.index("--type") + 1] == "income"
    assert argv[argv.index("--fields") + 1] == "all"
    assert argv[argv.index("--limit") + 1] == "8"


@pytest.mark.parametrize(
    ("dataset", "statement"),
    (
        ("financial_income", "income"),
        ("financial_balance", "balance"),
        ("financial_cashflow", "cashflow"),
    ),
)
def test_each_dataset_maps_to_its_statement(dataset: str, statement: str) -> None:
    runner = ReplayRunner(_recorded(dataset))

    _provider(runner).fetch(_request(dataset))

    assert runner.argv[0][runner.argv[0].index("--type") + 1] == statement


def test_symbols_the_source_did_not_return_are_named() -> None:
    """The CLI's own batch summary cannot be trusted for coverage."""
    runner = ReplayRunner(_recorded("financial_income"))

    raw = _provider(runner).fetch(
        _request("financial_income", (*FIXTURE_SYMBOLS, "601398.SH"))
    )

    assert raw.missing_symbols == ("601398.SH",)
    assert raw.status is DataStatus.VALUE


def test_an_empty_answer_is_null_with_every_symbol_missing() -> None:
    runner = ReplayRunner("")

    raw = _provider(runner).fetch(_request("financial_income"))

    assert raw.status is DataStatus.NULL
    assert raw.row_count == 0
    assert raw.payload is None
    assert raw.missing_symbols == FIXTURE_SYMBOLS


def test_a_failing_command_is_a_source_error_not_an_exception() -> None:
    runner = ReplayRunner("", returncode=2, stderr="network unreachable")

    raw = _provider(runner).fetch(_request("financial_income"))

    assert raw.status is DataStatus.SOURCE_ERROR
    assert raw.row_count == 0


def test_a_batch_with_extra_columns_widens_the_merged_table() -> None:
    """The source's shape depends on what the batch contains.

    Measured on 2026-09-16: a batch holding a bank returns six more columns
    than a batch of manufacturers. The first whole-market run treated that
    difference as corruption and threw away a whole statement; the fix is to
    merge on the union and leave the cells a shape did not carry empty — a
    missing value, not a zero.
    """
    narrow = _markdown(
        ("code", "EndDate", "InfoPublDate", "OperatingRevenue"),
        (("sz000002", "2026-06-30", "2026-08-15", "1.0"),),
    )
    wide = _markdown(
        ("code", "EndDate", "InfoPublDate", "OperatingRevenue", "Deposit"),
        (("sz000001", "2026-06-30", "2026-08-15", "2.0", "3.0"),),
    )

    class TwoShapes:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, argv: Sequence[str]) -> CommandResult:
            self.calls += 1
            return CommandResult(
                returncode=0,
                stdout=narrow if self.calls == 1 else wide,
                stderr="",
            )

    raw = _provider(TwoShapes(), batch_size=1).fetch(
        _request("financial_income", ("000002.SZ", "000001.SZ"))
    )

    assert raw.status is DataStatus.VALUE
    assert raw.payload is not None
    assert "Deposit" in raw.payload.columns
    # The first batch's row keeps its alignment and gains an empty cell where
    # its own shape had no column.
    deposit = raw.payload.columns.index("Deposit")
    assert raw.payload.rows[0][deposit] == ""
    assert raw.payload.rows[1][deposit] == "3.0"
    assert raw.row_count == 2


def test_a_failed_batch_does_not_discard_the_other_batches() -> None:
    """A whole-market run must not lose a table to one transient batch."""

    class OneBadBatch:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, argv: Sequence[str]) -> CommandResult:
            self.calls += 1
            if argv[2].startswith("sh601398"):
                return CommandResult(returncode=3, stdout="", stderr="rate limited")
            return CommandResult(
                returncode=0, stdout=_recorded("financial_income"), stderr=""
            )

    runner = OneBadBatch()
    raw = _provider(runner, batch_size=3).fetch(
        _request("financial_income", (*FIXTURE_SYMBOLS, "601398.SH"))
    )

    assert raw.status is DataStatus.VALUE
    assert raw.row_count == 24
    assert raw.message is not None
    assert "batch 2/2" in raw.message
    assert "rate limited" in raw.message
    assert raw.missing_symbols == ("601398.SH",)
    # One retry per failed batch: the good batch is fetched once, the bad twice.
    assert runner.calls == 3


def test_every_batch_failing_is_a_source_error_with_the_reason() -> None:
    runner = ReplayRunner("", returncode=5, stderr="endpoint down")

    raw = _provider(runner, batch_size=10).fetch(_request("financial_income"))

    assert raw.status is DataStatus.SOURCE_ERROR
    assert raw.payload is None
    assert raw.message is not None
    assert "endpoint down" in raw.message


def test_batching_calls_once_per_batch_and_concatenates_rows() -> None:
    runner = ReplayRunner(_recorded("financial_income"))

    raw = _provider(runner, batch_size=2).fetch(
        _request("financial_income", (*FIXTURE_SYMBOLS, "601398.SH"))
    )

    assert len(runner.argv) == 2
    assert runner.argv[0][2] == "sh600519,sz000001"
    assert runner.argv[1][2] == "sz300750,sh601398"
    assert raw.row_count == 48  # the recorded table twice: rows concatenate


def test_a_batch_with_no_data_does_not_erase_the_other_batches() -> None:
    runner = ReplayRunner(_recorded("financial_income"), by_code="sh600519")

    raw = _provider(runner, batch_size=2).fetch(
        _request("financial_income", (*FIXTURE_SYMBOLS, "601398.SH"))
    )

    assert raw.status is DataStatus.VALUE
    assert raw.row_count == 24
    # The second batch answered with nothing, and 601398.SH is the symbol that
    # never appeared in any returned table — the recorded fixture happens to
    # carry 300750.SZ already, so that one is covered.
    assert raw.missing_symbols == ("601398.SH",)


def test_report_period_is_reported_only_when_every_row_agrees() -> None:
    single = "| code | EndDate |\n| --- | --- |\n| sh600519 | 2026-06-30 |\n"
    several = (
        "| code | EndDate |\n| --- | --- |\n"
        "| sh600519 | 2026-06-30 |\n| sh600519 | 2026-03-31 |\n"
    )

    one = _provider(ReplayRunner(single)).fetch(_request("financial_income"))
    many = _provider(ReplayRunner(several)).fetch(_request("financial_income"))

    assert one.report_period == date(2026, 6, 30)
    assert many.report_period is None


def test_an_unknown_dataset_is_a_caller_problem() -> None:
    with pytest.raises(ValueError, match="unknown dataset"):
        _provider(ReplayRunner("")).fetch(
            FetchRequest(
                dataset="financial_whatever", as_of=AS_OF, symbols=("600519.SH",)
            )
        )


def test_choosing_the_market_is_not_this_provider_s_decision() -> None:
    with pytest.raises(ValueError, match="requires explicit symbols"):
        _provider(ReplayRunner("")).fetch(
            FetchRequest(dataset="financial_income", as_of=AS_OF)
        )


def test_an_empty_symbol_list_is_a_caller_problem() -> None:
    with pytest.raises(ValueError, match="empty symbol list"):
        _provider(ReplayRunner("")).fetch(_request("financial_income", ()))


def test_a_symbol_without_an_exchange_suffix_is_refused() -> None:
    with pytest.raises(ValueError, match="600519"):
        to_westock_code("600519")


def test_the_cli_error_path_is_a_source_error_not_an_exception() -> None:
    """A process that never starts is a source problem, not a caller mistake."""
    provider = WestockCliProvider(binary="/nonexistent/westock")

    raw = provider.fetch(_request("financial_income"))

    assert raw.status is DataStatus.SOURCE_ERROR
    assert raw.row_count == 0


def test_codes_round_trip_between_the_two_vocabularies() -> None:
    for symbol in FIXTURE_SYMBOLS:
        assert from_westock_code(to_westock_code(symbol)) == symbol

    assert to_westock_code("830799.BJ") == "bj830799"
    with pytest.raises(ValueError, match="known exchange prefix"):
        from_westock_code("xx600519")


def test_health_reports_a_missing_binary_and_names_the_override(
    local_tmp: Path,
) -> None:
    health = WestockCliProvider(binary=local_tmp / "nope").health()

    assert health.healthy is False
    assert health.status is DataStatus.SOURCE_ERROR
    assert health.message is not None
    assert BINARY_ENV in health.message


def test_health_reports_a_present_binary_without_running_it(
    local_tmp: Path,
) -> None:
    binary = local_tmp / "westock"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    health = WestockCliProvider(binary=binary).health()

    assert health.healthy is True
    assert health.status is DataStatus.VALUE
    assert health.message is not None
    assert "only proven by a fetch" in health.message


def test_health_refuses_a_file_that_cannot_be_executed(local_tmp: Path) -> None:
    binary = local_tmp / "westock"
    binary.write_text("not executable\n", encoding="utf-8")
    binary.chmod(0o644)

    assert WestockCliProvider(binary=binary).health().healthy is False


def test_the_binary_comes_from_the_environment(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = local_tmp / "westock"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv(BINARY_ENV, str(binary))

    assert WestockCliProvider().health().healthy is True


def test_a_ragged_row_is_refused_rather_than_published() -> None:
    text = "| code | EndDate |\n| --- | --- |\n| sh600519 | 2026-06-30 | extra |\n"

    with pytest.raises(MalformedTable, match="cells"):
        parse_tables(text)


def test_the_cli_status_preamble_is_not_mistaken_for_data() -> None:
    text = (
        "[Batch] 状态: success | 总数: 1 | 成功: 1 | 失败: 0\n"
        "\n"
        "| code | EndDate |\n| --- | --- |\n| sh600519 | 2026-06-30 |\n"
    )

    tables = parse_tables(text)

    assert len(tables) == 1
    assert tables[0].rows == (("sh600519", "2026-06-30"),)


def test_periods_and_batch_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="periods must be positive"):
        WestockCliProvider("/opt/westock", periods=0)

    with pytest.raises(ValueError, match="batch_size must be positive"):
        WestockCliProvider("/opt/westock", batch_size=0)
