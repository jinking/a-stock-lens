"""neodata Provider 测试（回放真实录制的响应）。

这些测试钉住的是"实测才知道"的几件事，而不是接口的形状：

- 查询措辞固化在模板里——服务端按意图匹配，措辞变了就可能取不到数据；
- 批量回答是部分的：请求 3 只标的时，利润表只回 2 只、估值只回 1 只，
  而 `entity` 三只都列了，因此覆盖必须按**内容**判定；
- 缺口会补抓一次，剩下的才算真实缺口；
- 凭证按"环境变量 → 插件目录 → 旧路径"解析，状态如实报告且不回显内容。
"""

import copy
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from astock_lens.data.contracts import FetchRequest
from astock_lens.data.providers.neodata import (
    LEGACY_TOKEN_FILE,
    PAYLOAD_COLUMNS,
    QUERY_TEMPLATES,
    TOKEN_ENV,
    TOKEN_FILE_ENV,
    NeodataProvider,
    load_token,
    token_candidates,
    token_status_text,
)
from astock_lens.domain.enums import DataStatus

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "neodata"
AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
SYMBOLS = ("600519.SH", "000858.SZ", "000568.SZ")


from typing import cast


def _fixture(dataset: str) -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads((FIXTURES / f"{dataset}.json").read_text(encoding="utf-8")),
    )


class Replay:
    """回放录制响应，并记录每次请求的查询措辞。"""

    def __init__(
        self,
        payload: Mapping[str, object] | None = None,
        *,
        payloads: Sequence[Mapping[str, object]] | None = None,
        body: bytes | None = None,
    ) -> None:
        self.queries: list[str] = []
        self._payload = payload
        self._payloads = list(payloads or [])
        self._body = body

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> Mapping[str, object]:
        del timeout
        assert url.startswith("https://copilot.tencent.com/")
        if self._body is None:
            self._body = body
            self.last_headers = dict(headers)
        payload = json.loads(body.decode("utf-8"))
        self.queries.append(str(payload["query"]))
        if self._payloads:
            index = min(len(self.queries) - 1, len(self._payloads) - 1)
            return self._payloads[index]
        return self._payload or {}


def _provider(transport: Replay, **kwargs: object) -> NeodataProvider:
    return NeodataProvider("test-token", transport=transport, **kwargs)  # type: ignore[arg-type]


def _request(dataset: str, symbols: Sequence[str] = SYMBOLS) -> FetchRequest:
    return FetchRequest(dataset=dataset, as_of=AS_OF, symbols=tuple(symbols))


def test_query_templates_are_pinned_not_improvised() -> None:
    """措辞就是接口：服务端按意图匹配，测试把它钉住。"""
    provider = _provider(Replay({}))

    assert provider.build_query("valuation", ("600519.SH",)) == (
        "600519.SH 最新市盈率PE 市净率PB 股息率 总市值 历史估值分位"
    )
    assert provider.build_query("financial_quarterly", ("600519.SH", "000858.SZ")) == (
        "600519.SH、000858.SZ 最近8期 营业收入 归母净利润 报告期 发布日期"
    )
    assert provider.build_query("dividend_history", ("600519.SH",)) == (
        "600519.SH 历史分红送配 每10股派息 股权登记日 除权日 实施状态"
    )
    assert set(QUERY_TEMPLATES) == {
        "valuation",
        "industry",
        "financial_quarterly",
        "dividend_history",
    }


def test_dividend_history_coverage_is_read_from_content() -> None:
    """分红历史按内容判定覆盖度：请求两只，内容只有一只，缺口必须包含缺失的那只。"""
    payload = {
        "code": 200,
        "suc": True,
        "data": {
            "apiData": {
                "entity": ["600519.SH", "000858.SZ"],
                "apiRecall": [
                    {
                        "type": "分红送配详细",
                        "desc": "分红送配详细",
                        "content": (
                            "## 贵州茅台（标的代码：600519.SH）\n\n"
                            "| 公告日期 | 分红方案 | 股权登记日 | 除权除息日 | 方案进度 |\n"
                            "| --- | --- | --- | --- | --- |\n"
                            "| 2026-06-20 | 10派300.00元 | 2026-07-05 | 2026-07-06 | 实施 |\n"
                        ),
                    }
                ],
            }
        },
    }
    transport = Replay(payloads=[payload, {"data": {"apiData": {"apiRecall": []}}}])
    raw = _provider(transport).fetch(
        FetchRequest(
            dataset="dividend_history",
            as_of=AS_OF,
            symbols=("600519.SH", "000858.SZ"),
        )
    )
    assert raw.status is DataStatus.VALUE
    assert raw.missing_symbols == ("000858.SZ",)


def test_a_valuation_answer_is_landed_verbatim() -> None:
    # 第二次调用（补抓）故意返回空块，这样本测试只断言首批的落盘形态。
    transport = Replay(
        payloads=[_fixture("valuation"), {"data": {"apiData": {"apiRecall": []}}}]
    )

    raw = _provider(transport).fetch(_request("valuation"))

    assert raw.status is DataStatus.VALUE
    assert raw.payload is not None
    assert raw.payload.columns == PAYLOAD_COLUMNS
    assert raw.row_count == 1
    block_type, _, content = raw.payload.rows[0]
    assert block_type == "统一估值查询"
    assert "滚动市盈率（倍）" in content
    assert "市盈率历史分位数（%）" in content


def test_batch_coverage_is_read_from_the_content_not_from_entity() -> None:
    """实测：entity 说命中 3 只，估值内容里只有 1 只。"""
    transport = Replay(_fixture("valuation"))

    raw = _provider(transport).fetch(_request("valuation"))

    assert raw.missing_symbols == ("600519.SH", "000858.SZ")


def test_a_quarterly_answer_reports_the_symbol_it_left_out() -> None:
    transport = Replay(_fixture("financial_quarterly"))

    raw = _provider(transport).fetch(_request("financial_quarterly"))

    # 录制的响应里只有五粮液与泸州老窖。
    assert raw.missing_symbols == ("600519.SH",)


def test_the_gap_is_asked_for_once_more() -> None:
    """补抓一次：缺口被填上，缺失清零，而且补抓只问缺的那只。"""
    first = _fixture("financial_quarterly")
    second = copy.deepcopy(first)
    second["data"]["apiData"]["apiRecall"].append(  # type: ignore[index]
        {
            "type": "利润表",
            "desc": "利润表",
            "content": (
                "## 贵州茅台（标的代码：600519.SH）\n\n"
                "| 报告期 | 营业收入 |\n| --- | --- |\n| 2026-H1 | 90703260964.48 |\n"
            ),
        }
    )
    transport = Replay(payloads=[first, second])

    raw = _provider(transport).fetch(_request("financial_quarterly"))

    assert len(transport.queries) == 2
    assert "600519.SH" in transport.queries[1]
    assert "000858.SZ" not in transport.queries[1]  # 只问缺的那只
    assert raw.missing_symbols == ()
    # 首批一个内容块，补抓那批两个（原块 + 新补的贵州茅台块）。
    assert raw.row_count == 3


def test_an_industry_answer_is_two_blocks() -> None:
    """行业数据包含板块估值与成分股明细两块，板块代码原样保留供核对。"""
    transport = Replay(_fixture("industry"))

    raw = _provider(transport).fetch(_request("industry", ("白酒Ⅱ",)))

    assert raw.status is DataStatus.VALUE
    assert raw.payload is not None
    types = {row[0] for row in raw.payload.rows}
    assert types == {"统一估值查询", "板块成分明细"}
    joined = "\n".join(row[2] for row in raw.payload.rows)
    assert "01801125.PT" in joined
    assert "市盈率TTM" in joined
    # 行业数据集不做标的覆盖判断：请求的是板块名，回来的是板块代码。
    assert raw.missing_symbols == ()


def test_a_service_error_is_a_source_error_with_the_reason() -> None:
    transport = Replay(
        {"code": "1001", "msg": "未命中意图，非财报query没法处理", "suc": False}
    )

    raw = _provider(transport).fetch(_request("valuation"))

    assert raw.status is DataStatus.SOURCE_ERROR
    assert raw.payload is None
    assert raw.message is not None
    assert "1001" in raw.message


def test_the_request_carries_a_bearer_token() -> None:
    transport = Replay(_fixture("valuation"))

    _provider(transport).fetch(_request("valuation"))

    assert transport.last_headers["Authorization"] == "Bearer test-token"
    assert transport._body is not None
    assert json.loads(transport._body.decode("utf-8"))["sub_channel"] == "workbuddy"


def test_an_unknown_dataset_is_a_caller_problem() -> None:
    with pytest.raises(ValueError, match="未知数据集"):
        _provider(Replay({})).fetch(
            FetchRequest(dataset="whatever", as_of=AS_OF, symbols=("600519.SH",))
        )


def test_neodata_does_not_choose_the_market() -> None:
    with pytest.raises(ValueError, match="需要显式给出查询值"):
        _provider(Replay({})).fetch(FetchRequest(dataset="valuation", as_of=AS_OF))


def test_health_reports_a_missing_token_without_calling_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.setenv(TOKEN_FILE_ENV, "/nonexistent/token")
    monkeypatch.setattr(
        "astock_lens.data.providers.neodata.token_candidates",
        lambda: (Path("/nonexistent/token"),),
    )

    health = NeodataProvider().health()

    assert health.healthy is False
    assert health.status is DataStatus.SOURCE_ERROR
    assert health.message is not None
    assert "凭证" in health.message


def test_a_token_file_older_than_twelve_hours_reads_as_expired(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    path = local_tmp / "token"
    path.write_text(json.dumps({"token": "abc", "saved_at": 0}), encoding="utf-8")
    monkeypatch.setenv(TOKEN_FILE_ENV, str(path))

    token, status = load_token()

    assert token == ""
    assert status == "expired"
    assert "过期" in token_status_text()


def test_a_fresh_token_file_is_used(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    path = local_tmp / "token"
    path.write_text(
        json.dumps({"token": "fresh", "saved_at": datetime.now(UTC).timestamp()}),
        encoding="utf-8",
    )
    monkeypatch.setenv(TOKEN_FILE_ENV, str(path))

    assert load_token() == ("fresh", "ok")
    assert NeodataProvider().health().healthy is True


def test_the_environment_token_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOKEN_ENV, "from-env")

    assert load_token() == ("from-env", "ok")


def test_the_plugin_directory_is_searched_before_the_legacy_path(
    local_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v1.6.0 把凭证迁到插件目录，旧路径只是兜底。

    这里必须自造一个假的插件目录：真机上确实存在插件凭证，CI 上没有，
    靠机器状态断言的测试在别处会直接变红。
    """
    plugin_token = (
        local_tmp
        / ".workbuddy"
        / "plugins"
        / "cache"
        / "v1.6.0"
        / "finance-data"
        / "neodata"
        / "skills"
        / ".neodata_token"
    )
    plugin_token.parent.mkdir(parents=True)
    plugin_token.write_text(json.dumps({"token": "from-plugin"}), encoding="utf-8")
    monkeypatch.delenv(TOKEN_FILE_ENV, raising=False)
    monkeypatch.setenv("HOME", str(local_tmp))

    candidates = token_candidates()

    assert candidates[-1].as_posix().endswith(".workbuddy/.neodata_token")
    plugin_index = next(
        index
        for index, path in enumerate(candidates)
        if "plugins/cache" in path.as_posix()
    )
    assert plugin_index < candidates.index(LEGACY_TOKEN_FILE)


def test_batch_size_and_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        NeodataProvider("t", batch_size=0)
    with pytest.raises(ValueError, match="attempts"):
        NeodataProvider("t", attempts=0)
