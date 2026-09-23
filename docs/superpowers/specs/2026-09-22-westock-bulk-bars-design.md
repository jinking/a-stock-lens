# Westock 替换 AkShare 当 bulk daily bars — 设计规格

**Date:** 2026-09-22  
**Status:** 设计草案，待金总评审  
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
| `turnover_rate` | 0.0016 (=0.16%) | 0.16 | 0.16 | **quote.turnover_rate**（已是 % 单位）|

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

    BATCH_SIZE = 200        # 实测 250 稳态，留 25% 余量
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
        # 2. 切批（BATCH_SIZE = 200）
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

`data/raw/securities.csv`（已有 5568 行）即全市场 listing 缓存。`_land_securities_listing` 行为不变（仍调 `_bulk_provider().fetch(FetchRequest(dataset='securities', ...))`），但**新默认 Provider 不支持 securities 数据集**。

**方案**：在 WestockBarsProvider.fetch 内部对 `request.dataset == 'securities'` 显式 raise `NotImplementedError`，让上层 `_land_securities_listing` 走 listing 缓存路径（`_csv_root() / "securities.csv"`）。

> 待 §6 实施计划中确认：listing 实际数据流是否真的走 WestockBarsProvider.fetch('securities')？还是走 LocalCsvProvider 直读 raw 缓存？需先读 `_land_listing` 源码。

## 5. 测试策略（TDD 强制）

### 5.0 Test Delta Budget

本切片先盘点并复用现有 Provider 契约测试，再决定新增测试。默认预算为：新增 0、删除 0、净变化 0；只有现有测试无法表达 WeStock 特有行为时才增加用例，并在实施计划和工作记忆中说明原因。优先参数化既有 Provider 契约测试，不为相同的 RawDataset 通用契约复制一套测试。

新测试仅保留以下 WeStock 特有行为：成交量乘以 100、quote 优先于 kline、缺失标的语义，以及尚未被现有测试覆盖的 Provider 选择行为。

### 5.1 单元测试（先写，红）

文件：`tests/unit/test_westock_bars.py`（只有在现有测试无法覆盖时新增）

| 测试 | 断言 |
|---|---|
| `test_code_to_canonical` | `sh600000` → `600000.SH`，`sz000001` → `000001.SZ`，`bj920566` → `920566.BJ` |
| `test_volume_unit_conversion` | westock 532667 → emit 53266700 |
| `test_amount_prefers_quote_over_kline` | emit 用 quote.amount（480795737），不用 kline 取整值（480800000）|
| `test_close_prefers_quote_price` | emit 用 quote.price（9.04），不用 kline.last |
| `test_turnover_rate_unit` | emit 0.2（已是 %），不是 0.002 |
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

## 6. 待澄清事项

下列点需在 §7 实施计划前再查一次源码确认：

1. **`_land_securities_listing` 真实数据流**：是 `_bulk_provider().fetch('securities')` 还是直接读本地 csv？这决定了 WestockBarsProvider 是否需要支持 securities 数据集。
2. **westock kline/quote 的 markdown 解析**：现有 `WestockCliProvider` 用 `parse_tables(completed.stdout)` 解析 markdown 表格，新 Provider 复用同一解析器还是另写？
3. **kline 的 `last` 字段是否一定是 `close`**？fixture 中三只都是 `last == quote.price`，但这是巧合还是契约？需 spot check 更多 fixture。
4. **停牌股 quote 返回全 0 的处理** —— 是否要按 `SOURCE_ERROR` 还是 `NULL`？fixture `quote_bj920566` 是正常交易的，没覆盖停牌 case。

## 7. 实施计划（待 superpowers 第 3 步生成）

工作将拆为以下任务（每个 2–5 分钟）：

1. 开 worktree + 跑测试基线（10 min）
2. RED：写 `test_westock_bars.py` 单元测试 9 个，全部 fail
3. GREEN：`WestockBarsProvider` 最小实现让单元测试全绿
4. RED：写 `test_westock_bars_contract.py` 契约测试
5. GREEN：实现 CLI 工厂切换 + 列映射常量 + `_invoke` subprocess
6. 端到端冒烟：50 只标的 vs AkShare
7. AGENTS.md 边界自检（架构边界、6 种状态、时区、禁止静默兜底）
8. 收尾：跑 `ruff check` + `mypy` + `pytest` 全绿
9. 工作记忆 + skill 更新

**总工程量：~4.5 h**（详见 §7 实施计划文档，金总拍板后再写）

## 8. 验收标准（Definition of Done）

- [ ] `WestockBarsProvider` 实现；新增测试数量符合 Test Delta Budget，且先复用/参数化既有契约测试
- [ ] 复用后的契约测试全绿；仅 WeStock 特有行为保留新增测试
- [ ] `_bulk_provider()` 默认 westock，`ASTOCK_BULK_PROVIDER=akshare` 回退可用
- [ ] 端到端冒烟：westock 50 只 vs AkShare 50 只，row_count 一致（≤ 5% 误差）
- [ ] AkShareProvider **完全不动**（仍作 fallback）
- [ ] 工作记忆更新（决策、字段映射、未解决问题）
- [ ] fixture 6 份覆盖关键场景
- [ ] `uv run ruff check .` 通过
- [ ] `uv run mypy` 通过
- [ ] `uv run pytest tests/contract/ tests/unit/` 全绿

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
- 现有 AkShare Provider：`src/astock_lens/data/providers/akshare_provider.py`（待替换）
- CLI 工厂：`src/astock_lens/cli/runtime.py`（`_bulk_provider`；`app.py` 只负责 CLI 组装）
