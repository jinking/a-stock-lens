"""neodata 语义数据源（WorkBuddy 平台金融数据服务）。

按设计规格 §24 补遗（2026-09-17 修订），neodata 是一等 Provider，承担三类**主数据**：
估值事实、行业/板块数据、语义维度（主营构成、供应链、业绩会），并作为财报的交叉验证源。
它不做标的枚举——名单仍由 AkShare 提供，本 Provider 只按给定名单取数。

实测（2026-09-17，详见 `docs/REVIEW_NOTES.md` 第九节）：

- **可批量**：10 只标的一次查询返回 10 行（3.1 秒）。全市场按 10 只/次约 558 次调用，
  与 westock 的 37 分钟同量级；
- **有估值**：滚动 PE/PB、历史分位、相对行业估值标签，以及逐日 PE/PB/PS/市现率/股息率/EV/PEG；
- **有行业**：板块估值 + 完整成分股明细（总市值、流通市值、PE TTM、主力净流入）；
- **历史带重述标记**：历史行会标 `2026-08-15（最新调整）`，原始公告日与调整日都可见。

两条限制写进代码而不是藏着：

1. **意图匹配决定能否取到数据。** 服务端对未命中的查询返回 `1001 未命中意图`，
   因此查询措辞固化成 `QUERY_TEMPLATES` 并由测试钉住；调用方不能自由拼自然语言。
2. **批量回答是部分的，`entity` 不能当覆盖依据。** 实测（2026-09-17）：请求 3 只标的时，
   利润表只回了 2 只、估值只回了 1 只，而 `apiData.entity` 三只都列了。因此覆盖由
   **内容里实际出现的代码**判定，并对缺口的标的补抓一次；`entity` 只作参考。
3. **行业查询靠意图解析板块名，Provider 不校验解析结果。** 服务端返回的板块代码与名称
   原样落在 raw 里（`标的代码（统一输出字段名）` / `标的名称`），由归一化层核对，
   而不是在这里假装校验过。

凭证：由 WorkBuddy 平台下发，12 小时有效。v1.6.0 起缓存在插件目录内
（`plugins/cache/*/finance-data/*/skills/.neodata_token`），旧路径
`~/.workbuddy/.neodata_token` 是迁移前的位置。本模块按
环境变量 → 插件目录（取最新版本）→ 旧路径 的顺序解析，并在 `health()` 里如实报告状态与
刷新方式；它绝不回显凭证内容。
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from astock_lens.data.contracts import (
    FetchRequest,
    ProviderHealth,
    RawDataset,
    RawPayload,
)
from astock_lens.domain.enums import DataStatus

ENDPOINT = "https://copilot.tencent.com/agenttool/v1/neodata"
CHANNEL = "neodata"
SUB_CHANNEL = "workbuddy"

TOKEN_ENV = "ASTOCK_NEODATA_TOKEN"
TOKEN_FILE_ENV = "ASTOCK_NEODATA_TOKEN_FILE"
LEGACY_TOKEN_FILE = Path.home() / ".workbuddy" / ".neodata_token"
PLUGIN_TOKEN_GLOB = ".workbuddy/plugins/cache/*/finance-data/*/skills/.neodata_token"
TOKEN_TTL_SECONDS = 12 * 3600

# 数据集 → 查询模板。`{names}` 用顿号连接；措辞固化，不交给调用方自由拼写。
QUERY_TEMPLATES: Mapping[str, str] = {
    "valuation": "{names} 最新市盈率PE 市净率PB 股息率 总市值 历史估值分位",
    "industry": "{names} 行业 最新营业收入 净利润 同比增速 板块估值 成分股",
    "financial_quarterly": "{names} 最近8期 营业收入 归母净利润 报告期 发布日期",
    "dividend_history": "{names} 历史分红送配 每10股派息 股权登记日 除权日 实施状态",
}

# 按标的取数的数据集；行业数据集按板块名取数，因此不做标的覆盖核对。
SYMBOL_DATASETS: frozenset[str] = frozenset(
    {"valuation", "financial_quarterly", "dividend_history"}
)

DEFAULT_BATCH_SIZE = 10
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_ATTEMPTS = 2

REFRESH_HINT = (
    "凭证不可用：请在 WorkBuddy 侧刷新后保存到插件目录，"
    f"或设置 {TOKEN_ENV} / {TOKEN_FILE_ENV}"
)

PAYLOAD_COLUMNS: tuple[str, ...] = ("type", "desc", "content")

if TYPE_CHECKING:
    Transport = Callable[[str, Mapping[str, str], bytes, float], Mapping[str, object]]


def token_candidates() -> tuple[Path, ...]:
    """按解析顺序列出候选凭证文件（插件目录取最新版本优先）。"""
    configured = os.getenv(TOKEN_FILE_ENV)
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        sorted(
            Path.home().glob(PLUGIN_TOKEN_GLOB),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    )
    candidates.append(LEGACY_TOKEN_FILE)
    return tuple(candidates)


def load_token() -> tuple[str, str]:
    """读本地缓存的凭证，返回 (token, 状态)。

    状态取值与深研项目一致：`ok` / `missing` / `expired` / `broken`，
    这样两边可以用同一套话术向使用者解释。
    """
    configured = os.getenv(TOKEN_ENV, "").strip()
    if configured:
        return configured, "ok"

    for path in token_candidates():
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        except (PermissionError, OSError):
            return "", "broken"
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 旧格式（纯文本）没有签发时间，无法判断是否过期。
            return "", "expired"
        token = str(data.get("token", "")).strip()
        saved_at = float(data.get("saved_at") or 0)
        if not token:
            continue
        if time.time() - saved_at > TOKEN_TTL_SECONDS:
            return "", "expired"
        return token, "ok"

    return "", "missing"


def token_status_text() -> str:
    """给 `doctor` 用的一句话状态。"""
    _, status = load_token()
    return {
        "ok": "凭证有效",
        "missing": f"未找到凭证；{REFRESH_HINT}",
        "expired": f"凭证已过期（12 小时有效）；{REFRESH_HINT}",
        "broken": f"凭证文件不可读；{REFRESH_HINT}",
    }.get(status, f"未知状态：{status}")


def _live_transport(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> Mapping[str, object]:
    """真实请求。网络异常在调用方被翻译成状态，不在这里静默吞掉。"""
    request = urllib.request.Request(
        url, data=body, headers=dict(headers), method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload: object = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004 - 服务端返回体形状，不是调用方类型错误
            "neodata 返回的不是一个 JSON 对象"
        )
    return payload


class NeodataProvider:
    """按固定查询模板取估值、行业与单季财报数据。"""

    def __init__(
        self,
        token: str | None = None,
        *,
        endpoint: str = ENDPOINT,
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        attempts: int = DEFAULT_ATTEMPTS,
        transport: "Transport | None" = None,
        provider: str = "neodata",
        version: str = "v1",
    ) -> None:
        if batch_size <= 0:
            raise ValueError(f"batch_size 必须为正，收到 {batch_size}")
        if attempts <= 0:
            raise ValueError(f"attempts 必须为正，收到 {attempts}")
        self._token = token
        self._endpoint = endpoint
        self._batch_size = batch_size
        self._timeout = timeout
        self._attempts = attempts
        self._transport = transport if transport is not None else _live_transport
        self._provider = provider
        self._version = version

    def health(self) -> ProviderHealth:
        """报告凭证可用性；不发起请求，`doctor` 保持只读与快速。"""
        checked_at = datetime.now(UTC)
        token = self._token or load_token()[0]
        if not token:
            return ProviderHealth(
                provider=self._provider,
                healthy=False,
                status=DataStatus.SOURCE_ERROR,
                checked_at=checked_at,
                message=token_status_text(),
            )
        return ProviderHealth(
            provider=self._provider,
            healthy=True,
            status=DataStatus.VALUE,
            checked_at=checked_at,
            message=f"{token_status_text()}；连通性由真实取数证明",
        )

    def build_query(self, dataset: str, values: Sequence[str]) -> str:
        """按模板拼查询。措辞固化是刻意的：服务端按意图匹配。"""
        template = QUERY_TEMPLATES.get(dataset)
        if template is None:
            raise ValueError(
                f"未知数据集 {dataset!r}；本 Provider 支持 {sorted(QUERY_TEMPLATES)}"
            )
        if not values:
            raise ValueError(f"数据集 {dataset!r} 需要至少一个查询值")
        return template.format(names="、".join(values))

    def post(self, query: str) -> Mapping[str, object]:
        """发一次请求，返回原始 JSON。凭证缺失会被显式报出。"""
        token = self._token or load_token()[0]
        if not token:
            raise RuntimeError(token_status_text())
        body = json.dumps(
            {
                "query": query,
                "channel": CHANNEL,
                "sub_channel": SUB_CHANNEL,
                "data_type": "all",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        return self._transport(self._endpoint, headers, body, self._timeout)

    def fetch(self, request: FetchRequest) -> RawDataset:
        """按批次取数，并如实报告覆盖情况。"""
        if request.dataset not in QUERY_TEMPLATES:
            raise ValueError(
                f"未知数据集 {request.dataset!r}；本 Provider 支持 "
                f"{sorted(QUERY_TEMPLATES)}"
            )
        if request.symbols is None:
            raise ValueError(
                f"数据集 {request.dataset!r} 需要显式给出查询值：neodata 不做标的枚举，"
                "名单由 AkShare 名单决定"
            )
        if not request.symbols:
            raise ValueError(f"数据集 {request.dataset!r} 收到空的查询值列表")

        fetched_at = datetime.now(UTC)
        values = tuple(dict.fromkeys(request.symbols))
        rows: list[tuple[str, str, str]] = []
        failed_batches: list[str] = []

        for index, batch in enumerate(_chunks(values, self._batch_size), start=1):
            payload, failure = self._invoke(request.dataset, batch)
            if failure is not None:
                failed_batches.append(
                    f"第 {index} 批（{batch[0]}…{batch[-1]}）：{failure}"
                )
                continue
            rows.extend(_blocks(payload))

        summary = "；".join(failed_batches)
        if not rows:
            return self._emptied(
                request,
                fetched_at,
                DataStatus.SOURCE_ERROR if failed_batches else DataStatus.NULL,
                summary or "服务端没有返回任何内容块",
                missing=tuple(values),
            )

        missing = _missing(request.dataset, values, rows)
        if missing:
            # 一次补抓：批量回答常少一两只（实测 3 只请求只回 1–2 只），
            # 而 `entity` 显示"命中"并不代表内容里有它。
            for batch in _chunks(missing, self._batch_size):
                payload, failure = self._invoke(request.dataset, batch)
                if failure is not None:
                    failed_batches.append(f"补抓（{batch[0]}…{batch[-1]}）：{failure}")
                    continue
                rows.extend(_blocks(payload))
            summary = "；".join(failed_batches)
            missing = _missing(request.dataset, values, rows)

        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=DataStatus.VALUE,
            row_count=len(rows),
            missing_symbols=missing,
            message=summary or None,
            payload=RawPayload(columns=PAYLOAD_COLUMNS, rows=tuple(rows)),
        )

    def _invoke(
        self, dataset: str, batch: Sequence[str]
    ) -> tuple[Mapping[str, object], str | None]:
        """取一批数据，失败重试一次；返回 (payload, 失败原因)。"""
        query = self.build_query(dataset, batch)
        last = ""
        for _ in range(self._attempts):
            try:
                payload = self.post(query)
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as error:
                last = f"请求失败：{error}"
                continue
            except (RuntimeError, ValueError) as error:
                return {}, str(error)

            if str(payload.get("code")) != "200" or not payload.get("suc", False):
                last = f"服务端返回 code={payload.get('code')} msg={payload.get('msg')}"
                continue
            return payload, None
        return {}, last or "未知失败"

    def _emptied(
        self,
        request: FetchRequest,
        fetched_at: datetime,
        status: DataStatus,
        message: str,
        *,
        missing: tuple[str, ...] = (),
    ) -> RawDataset:
        """构建"什么都没取到"的元数据记录。"""
        return RawDataset(
            provider=self._provider,
            dataset=request.dataset,
            fetched_at=fetched_at,
            provider_version=self._version,
            status=status,
            row_count=0,
            missing_symbols=missing,
            message=message,
        )


def _chunks(values: Sequence[str], size: int) -> tuple[tuple[str, ...], ...]:
    """把查询值切批；逐批转成元组，避免切片结果为任意序列。"""
    return tuple(
        tuple(values[start : start + size]) for start in range(0, len(values), size)
    )


def _blocks(payload: Mapping[str, object]) -> list[tuple[str, str, str]]:
    """把 apiRecall 的内容块逐字取出来，一块一行。"""
    data = payload.get("data")
    api = data.get("apiData") if isinstance(data, Mapping) else None
    recall = api.get("apiRecall") if isinstance(api, Mapping) else None
    if not isinstance(recall, list):
        return []
    rows: list[tuple[str, str, str]] = []
    for block in recall:
        if not isinstance(block, Mapping):
            continue
        rows.append(
            (
                str(block.get("type") or ""),
                str(block.get("desc") or ""),
                str(block.get("content") or ""),
            )
        )
    return rows


def _missing(
    dataset: str,
    requested: Sequence[str],
    rows: Sequence[tuple[str, str, str]],
) -> tuple[str, ...]:
    """请求了但回答内容里没有出现的标的。

    只对按标的取数的数据集成立：行业数据集按板块名查询，服务端回答的是解析后的板块代码，
    两者不是同一套标识，因此这里不做覆盖判断（板块解析结果由归一化层核对）。

    判定依据是**内容**而不是 `apiData.entity`：实测请求 3 只时 entity 列了 3 只，
    而利润表内容只含 2 只、估值内容只含 1 只。
    """
    if dataset not in SYMBOL_DATASETS:
        return ()
    content = "\n".join(block[2] for block in rows)
    return tuple(value for value in requested if value not in content)
