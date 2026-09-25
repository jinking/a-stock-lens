# Westock 替换 AkShare 当 bulk daily bars — 设计规格

**Date:** 2026-09-22  
**Status:** 已按授权实施；本规格同步记录修订后的数据契约。  
**Path:** Provider 层增量（架构边界内）

> 把 `astock daily --sync` 单日跑 1.5 小时缩短到 3–5 分钟，**不引入新数据源依赖**（westock 是已装的 CLI，listing 复用本地快照）。本规格新增一个 Provider、改一个工厂函数，不删 AkShare。

## 1. 动机与现状

`astock daily --as-of YYYY-MM-DD --sync` 跑 09-21 / 09-22 两天时实测单日 1h44m 仍未结束，金总要求查清根因并优化。

**根因（已查源码确认）**：`AkShareProvider._fetch_bars`（src/astock_lens/data/providers/akshare_provider.py:363-391）串行 for-loop 全市场 ~5400 只，每只一次 `akshare.stock_zh_a_hist_tx` HTTP，**单只 0.5–2s，全市场 ≈ 1.5h/日**。架构上 AkShare 不暴露 timeout / 取消句柄，并发必须进程隔离（provider 注释明确，详见 `AKSHARE_FALLBACK_REQUIRES_PROCESS_ISOLATION`）。

**金总已拍板的决策**：

1. 方案 A：westock `kline` + `quote` 双源
2. 默认 Provider 直接改 westock（不再默认 akshare）
3. AkShare 整个移除（包括 listing）
4. 现在就抓真实响应固化 fixture

**实测中推翻的假设**：

- **决策 3 修订**：发现 `data/raw/securities.csv` 已缓存 5568 行全市场 listing，且 daily bars fetch 不再依赖实时 listing（`_land_dataset` 内部按 listing 决定 wanted symbols 的路径只走一次）。**listing 复用本地快照即可**，AkShare 只在冷启动兜底时仍有用，本期不删。
- **AkShare 内部走的就是腾讯域**（akshare 的 `stock_zh_a_hist_tx` → `ifzq.gtimg.cn`），westock CLI 也是 `ifzq.gtimg.cn`。**两者换源不换底层**，本规格是"换 wrapper"而非"换数据源"。

## 2. 目标

| 项 | 现状 | 目标 |
|---|---|---|
| `daily --sync` 单日耗时 | 1.5h | 3–5 min |
| 全市场多日增量（一周）| 10h+ | 30 min |
| AkShare 仍是 hot path | 是 | 否（仅冷启动兜底）|
| listing 数据源 | AkShare（每次 fetch）| 本地 `securities.csv` 缓存 |
| Provider 默认值 | AkShareProvider | WestockBarsProvider |

**非目标**（明确 scope 边界）：

- ❌ 不删 AkShareProvider（listing 冷启动 + 紧急 fallback 仍用）
- ❌ 不替换 listing 数据源（本地缓存已够）
- ❌ 不引入 iFinD 商业 API（金总在评审中贴过 key，但本项目代码 / memory / fixture 都没有 iFinD 痕迹，且商业 API 性价比 + 凭证风险都偏高）
- ❌ 不动 multiprocessing.Pool 改造 AkShare（已被 westock 取代）
- ❌ 不动 Strategy / Factor / Universe / 数据契约 / 6 种缺失状态语义

## 3. westock 双源实测数据

### 3.1 速度

| 操作 | 耗时 | 备注 |
|---|---|---|
| `kline` 6 只 2 天 | 4.3s | 含 CLI 启动 |
| `kline` 11 只 1 天 | 1.3s | |
| **`kline` 250 只 1 天** | **6.5s** | **稳态上限** |
| `kline` 500 只 1 天 | partial（30 只成功）| 触发 `LOCAL_RATE_LIMITED` |
| `quote` 100 只 1 天 | 4.7s | |
| 250 只 1 天 `quote` | ~6s | 同 `kline` |

**全市场 5400 只估算**：22 批 × ~5s ≈ 2–3 min（双源各 1 遍 ≈ 5–6 min）。**对比 AkShare 1.5h 提速 18–30×**。

### 3.2 字段对齐（关键契约）

以 `sh600000` 2026-09-22 为实测样本：

| emit 列 | AkShare | westock kline | westock quote | 取谁 |
|---|---|---|---|---|
| `symbol` | `600000.SH` | `sh600000` | `sh600000` | code 前缀转 canonical |
| `trade_date` | `2026-09-22` | `2026-09-22` | `2026-09-22` | kline.date |
| `open` | 9.03 | 9.03 | 9.03 | kline.open |
| `high` | 9.07 | 9.07 | 9.07 | kline.high |
| `low` | 8.97 | 8.97 | 8.97 | kline.low |
| `close` | 9.04 | 9.04 (`last`) | 9.04 (`price`) | **quote.price** |
| `volume` | **53266700** | **532667** | 532667 | **kline.volume × 100**（westock 单位是"手"=100 股）|
| `amount` | **480795700** | 480800000 | **480795737** | **quote.amount**（kline 有 ~5000 元取整误差）|
| `turnover_rate` | 0.0016 (=0.16%) | 0.16 | 0.16 | **quote.turnover_rate × 0.01**（源是 %，Raw 保持小数比例）|

**关键陷阱**：

1. **volume 单位差 100 倍** —— 必须显式 ×100，否则下游 liquidity 因子挂
2. **kline 的 `last` ≠ 收盘价字段名**（westock 命名），应用 `quote.price`
3. **kline 的 `amount` 有取整误差** —— 与 quote 不一致，应用 quote
4. **westock 的 `exchange` 字段语义不同** —— `0.39` 是换手率数字，不是交易所代码。**不映射 SSE/SZSE/BSE**
5. **缺失字段** —— westock 无 `adj_factor`（但 normalize 不依赖）

### 3.3 错误契约

| westock 输出 | 上报状态 |
|---|---|
| `success` 且有数据 | `VALUE` |
| `success` 但 `数据为空`（如 `sh999999`）| `NULL` + `missing_symbols = requested` |
| `partial` 部分缺失 | `VALUE` + `missing_symbols = requested ∖ returned` |
| `LOCAL_RATE_LIMITED` | `SOURCE_ERROR`（**不写 0 行**）|
| 二进制不存在 / exit ≠ 0 | `SOURCE_ERROR` |
| 单只 fetch 抛异常（caller 错误）| `ValueError`（不是 status）|

**关键**：westock `Batch 状态: success` 不代表数据真到位，必须按 `requested ∖ returned` 计算 missing_symbols。

## 4. 设计

### 4.1 新增 `WestockBarsProvider`

文件：`src/astock_lens/data/providers/westock_bars.py`（新）

```python
class WestockBarsProvider:
    """Bulk daily bars via westock CLI（kline + quote 双源合并）。

    用 westock 替换 AkShareProvider 的 daily bars 路径。
    listing 不在本 Provider 范围——复用本地 data/raw/securities.csv。
    """

    BATCH_SIZE = 100        # 按所有者要求每 100 只回显一次进度
    DEFAULT_TIMEOUT = 30.0  # 与 WestockCliProvider 一致

    def __init__(self, *, binary=None, batch_size=BATCH_SIZE,
                 timeout=DEFAULT_TIMEOUT, attempts=2,
                 runner=None, provider="westock-bars", version="v1"): ...
    def health(self) -> ProviderHealth: ...
    def fetch(self, request: FetchRequest) -> RawDataset:
        """双源：kline（OHLCV）+ quote（close + turnover_rate + prev_close），
        按 code join，输出 BAR_EMIT_COLUMNS。
        """
        # 1. 校验 request.symbols 非空
        # 2. 切批（BATCH_SIZE = 100）
        # 3. 逐批调 kline + quote，捕获 _SourceError
        # 4. 按 code 内 join
        # 5. 应用列映射 + 单位换算（volume × 100）
        # 6. 缺值上报 missing_symbols，不补 0
        ...
```

**列映射常量**（与现有 `BAR_EMIT_COLUMNS` 对齐）：

```python
BAR_EMIT_COLUMNS = (
    "symbol", "trade_date", "open", "high", "low",
    "close", "volume", "amount", "turnover_rate",
)
```

**双源合并伪代码**：

```python
def fetch(self, request):
    wanted = tuple(request.symbols)
    kline_rows = self._invoke_kline(wanted, request.as_of)        # list[dict]
    quote_rows = self._invoke_quote(wanted, request.as_of)        # list[dict]
    kline_by = {row["code"]: row for row in kline_rows}
    quote_by = {row["code"]: row for row in quote_rows}

    rows = []
    missing = []
    for code in wanted:
        k, q = kline_by.get(code), quote_by.get(code)
        if k is None or q is None:
            missing.append(code)
            continue
        rows.append(_merge_row(code, k, q))     # close/q.price, volume*100, amount/q.amount

    return RawDataset(
        status=VALUE if rows else (NULL if not missing else SOURCE_ERROR),
        row_count=len(rows),
        missing_symbols=tuple(missing),
        payload=RawPayload(columns=BAR_EMIT_COLUMNS, rows=tuple(rows)),
    )
```

### 4.2 工厂函数切换

文件：`src/astock_lens/cli/runtime.py`（`_bulk_provider`；`app.py` 只负责 CLI 组装）

```python
def _bulk_provider() -> DataProvider:
    """The bulk provider `astock sync` lands data from.

    默认走 westock（kline + quote 双源）；AkShare 留作
    `ASTOCK_BULK_PROVIDER=akshare` 显式回退。
    """
    choice = os.getenv("ASTOCK_BULK_PROVIDER", "westock").lower()
    if choice == "westock":
        return WestockBarsProvider()
    if choice == "akshare":
        return AkShareProvider()
    raise typer.BadParameter(
        f"unknown ASTOCK_BULK_PROVIDER={choice!r}; "
        f"supported: 'westock' (default), 'akshare' (fallback)"
    )
```

### 4.3 listing 复用

`astock daily --sync` 有本地 `securities.csv` 时通过 `LocalCsvProvider` 读取名单，不重复调用 AkShare；冷启动缺少名单时由 AkShare 获取。显式 `astock sync` 与 `sync-bootstrap` 仍刷新名单，使用 `_listing_provider()`：WeStock 行情 Provider 配 AkShare，测试或显式 AkShare Provider 保持同一 Provider。`WestockBarsProvider` 不接收 `securities` 数据集。

## 5. 测试策略（TDD 强制）

### 5.0 Test Delta Budget

本切片复用既有 RawDataset 契约，并为批量双命令、数据单位/日期校验、错误状态、默认 Provider 路由及 listing 分流新增聚焦测试；这些行为不能由现有 AkShare 测试表达。

新测试仅保留以下 WeStock 特有行为：成交量乘以 100、quote 优先于 kline、缺失标的语义，以及尚未被现有测试覆盖的 Provider 选择行为。

### 5.1 单元测试（先写，红）

文件：`tests/unit/test_westock_bars.py`（只有在现有测试无法覆盖时新增）

| 测试 | 断言 |
|---|---|
| `test_code_to_canonical` | `sh600000` → `600000.SH`，`sz000001` → `000001.SZ`，`bj920566` → `920566.BJ` |
| `test_volume_unit_conversion` | westock 532667 → emit 53266700 |
| `test_amount_prefers_quote_over_kline` | emit 用 quote.amount（480795737），不用 kline 取整值（480800000）|
| `test_close_prefers_quote_price` | emit 用 quote.price（9.04），不用 kline.last |
| `test_turnover_rate_unit` | WeStock 0.2% → emit 0.002（既有 Raw 小数比例契约）|
| `test_invalid_codes_report_missing` | fixture `sh999999` 上报 `missing_symbols=['sh999999']`，不补 0 |
| `test_partial_response_reports_missing` | partial + missing_symbols |
| `test_rate_limited_returns_source_error` | 不写 0 行 |
| `test_securities_dataset_raises` | `fetch(dataset='securities')` → `NotImplementedError` |

### 5.2 契约测试

文件：`tests/contract/test_westock_bars.py`（只有在现有契约测试无法参数化时新增）

| 测试 | 断言 |
|---|---|
| `test_emit_columns_match_bars_contract` | 列名 == `BAR_EMIT_COLUMNS`（与 AkShare 对齐）|
| `test_payload_is_raw_strings` | 不做类型转换 |
| `test_bulk_provider_default_is_westock` | 不设 env → WestockBarsProvider |
| `test_bulk_provider_akshare_fallback` | `ASTOCK_BULK_PROVIDER=akshare` → AkShareProvider |
| `test_invalid_bulk_provider_raises` | 未知值 → `typer.BadParameter` |
| `test_health_reports_binary_presence` | 二进制不存在 → SOURCE_ERROR |

### 5.3 端到端冒烟（不入仓）

- `astock doctor` 在 westock 模式报告健康
- `astock daily --as-of 2026-09-22 --sync --allow-incomplete` 跑 50 只标的
- 与 AkShare 同 50 只对比 row_count（误差 ≤ 5%）

### 5.4 fixture（已固化 6 份）

`tests/fixtures/westock/`：
- `kline_sh600519_sz000001_sz300750_2026-09-22.md`
- `quote_sh600519_sz000001_sz300750_2026-09-22.md`
- `kline_bj920566_2026-09-22.md`
- `kline_invalid_codes_2026-09-22.md`
- `kline_mixed_valid_invalid_2026-09-22.md`
- `connect_exchange_sh_sz.md`（listing 替代源证据）

## 6. 实施结论与边界

- listing 流程已按 §4.3 分离；WeStock Provider 复用既有 Markdown 表解析器。
- AkShare 的日线请求 `adjust=""` 是不复权，因此 WeStock 明确使用 `--fq nofq`；使用 `qfq` 会改变下游历史价格语义。
- WeStock 换手率是百分数，输出 Raw 必须乘 `0.01`；成交量以“手”计，输出 Raw 乘 `100` 转成股。
- quote 必须返回目标交易日，缺失/日期不符不落行。停牌或无 quote 的标的按缺失报告，不造零值；当前接口没有足够证据区分停牌与源端漏数。
- 实测只完成三只标的真实 WeStock 冒烟，未完成 50 只 AkShare 对照。两种 CLI 最终都访问腾讯接口，不能把对照描述成独立供应商验证；全市场延迟提升尚未实测。
- 全市场运行实测：200 只首批成功后，紧接着的 kline 批次返回 `LOCAL_RATE_LIMITED`。冷却后单独请求 200 只可成功。Provider 遇到该状态会停止后续批次并保留所有缺失标的；Raw 落库与 CLI 必须将部分覆盖标成未完成，不能报告完整成功。具体安全请求间隔待源端证据确认，不臆定速率。
- CLI 每完成一批输出已处理/总数、成功、缺失和待处理数；批次大小 100 只，限流批次同样显式显示。

## 7. 实施记录

工作已按测试先行完成：

新增 Provider、默认工厂与 listing 分流均有测试；全量 pytest、ruff、格式、mypy 均通过。

## 8. 验收标准（Definition of Done）

- [x] `WestockBarsProvider` 实现，复用 RawDataset 契约并测试 WeStock 特有行为
- [x] `_bulk_provider()` 默认 WeStock，`ASTOCK_BULK_PROVIDER=akshare` 显式回退
- [ ] 真实三标的 WeStock 冒烟通过；50 只 AkShare 对照未完成
- [x] AkShareProvider **未修改**，保留名单/历史补抓/显式回退
- [x] 工作记忆与数据单位决策已记录
- [x] fixture 与单位/错误状态测试覆盖关键场景
- [x] `uv run ruff check .`、格式、`uv run mypy` 通过
- [x] 全量 `uv run pytest -q`：1274 passed

## 9. 架构边界自检

| AGENTS.md 原则 | 本方案 |
|---|---|
| 依赖方向 Provider → Raw | ✅ 新 Provider 写 Raw，不动下游 |
| Strategy 不得调用 Provider | ✅ |
| API / Web 不得重算因子 | ✅ |
| 本地优先 Parquet + DuckDB | ✅（仍写 CSV raw）|
| 缺失数据 6 种状态 | ✅ 见 §3.3 |
| 不静默兜底 | ✅（缺则缺，不补 0）|
| 时间戳带时区 | ✅（westock 返回 ISO date，UTC 化）|
| 文档中文 | ✅（本文）|
| 数据契约层 | ✅（新增 Provider，不改既有契约）|

## 10. 安全备忘

🔴 **iFinD key**：金总在 2026-09-22 评审中贴过完整 iFinD token，本设计文档与代码 / 测试 / fixture / 工作记忆**全部不使用、不引用、不存储**该 token。建议金总立即到 iFinD 控制台撤销重发。后续任何凭证用环境变量或本地文件路径提供，不直接贴字符串。

## 11. 备选方案（被否决）

| 方案 | 否决理由 |
|---|---|
| B. 直连 `ifzq.gtimg.cn` HTTP API | protobuf 协议 + 签名机制需自维护，性价比低 |
| C. AkShare `multiprocessing.Pool` | 仍依赖 pip 包 + 进程隔离 + contract test 全补，被 westock 取代 |
| D. iFinD 商业 API | 凭证风险 + 商业包依赖 + 项目代码无 iFinD 痕迹，性价比低 |
| E. 自维护 listing provider | `data/raw/securities.csv` 已够，无需新建 |

## 12. 引用

- 实测 spike：`.workbuddy/memory/2026-09-22.md`（2026-09-22 当日）
- Fixture：`tests/fixtures/westock/*.md`（已固化）
- 现有 westock Provider：`src/astock_lens/data/providers/westock.py`（WestockCliProvider，财务三表）
- 现有 AkShare Provider：`src/astock_lens/data/providers/akshare_provider.py`（保留）
- CLI 工厂：`src/astock_lens/cli/runtime.py`（`_bulk_provider`；`app.py` 只负责 CLI 组装）
