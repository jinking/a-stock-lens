# 全市场启动行情批量数据源探测（2026-09-18）

## 范围与方法

本次仅调查冷启动所需的**近期 A 股日线历史**能力；不实现 Provider，不改动 bootstrap 编排，
也不发起真实行情请求或全市场运行。证据限定为当前 worktree 的锁文件、可调用环境、CLI
帮助入口与已有 Provider 源码。

## 探测命令与实际输出

```text
$ tools/bin/westock --help
zsh:1: no such file or directory: tools/bin/westock
```

```text
$ .venv/bin/python -c 'import akshare as ak, inspect; ...'
Traceback (most recent call last):
  File "<string>", line 1, in <module>
ModuleNotFoundError: No module named 'akshare'
```

```text
$ rg -n -C 3 'name = "akshare"|akshare' uv.lock pyproject.toml
pyproject.toml:27:providers = ["akshare>=1.14"]
uv.lock:84:name = "akshare"
uv.lock:85-version = "1.18.94"
```

```text
$ rg -n "daily|bar|history|quote|行情|K线" src tools docs
src/astock_lens/data/providers/akshare_provider.py:50:BAR_ENDPOINT = "stock_zh_a_hist_tx"
src/astock_lens/data/providers/akshare_provider.py:231:                    "daily interface is per-symbol..."
src/astock_lens/data/providers/akshare_provider.py:346:            dataset = self.fetch_symbol_bars(
src/astock_lens/data/providers/westock.py:151:    """Bulk financial statements from the Tencent WeStock CLI."""
docs/REVIEW_NOTES.md:70:| 100 只一批 | 11.4 秒、100 行全回；全市场三表约需半小时，属季度任务 |
```

最后一条为仓库内命中的、与本结论有关的代表性行；完整搜索还包含测试、夹具和非日线模块，
不改变下表判断。

未执行任何联网请求，故没有 VPN 失败或重试事件。

## 证据表

| Source | Capability | Batch breadth | Date range support | Observed row count | Observed request count | Suitable as bootstrap primary? yes/no | Reason |
| --- | --- | --- | --- | ---: | ---: | --- | --- |
| AkShare（当前已实现路径） | `stock_zh_a_hist_tx`，字段为 `date/open/high/low/close/volume/amount/turnover`，映射后保留 `symbol/trade_date/.../amount` | 单标的；`fetch()` 对每个 symbol 调用一次 `fetch_symbol_bars()` | 支持；源码传递 `start_date`、`end_date` 为 `YYYYMMDD` | 未观测；当前 `.venv` 无 AkShare，未联网 | 每个 symbol 1 次 | no | 保留 symbol、日期和 amount，但已实现调用形状是逐标的，不能实质减少全市场远程请求。锁定候选版本为 1.18.94，非已安装可调用证据。 |
| AkShare（本地可调用清单） | 要求从已安装模块枚举函数签名/文档 | 无法验证 | 无法验证 | 0（未产生数据行） | 0 | no | `ModuleNotFoundError`；不能以锁文件或推测的端点替代实际可调用 inventory。 |
| WeStock CLI | 已有 Provider 只支持 `income`、`balance`、`cashflow` 三大表；调用形状为 `finance <codes> --type <statement> --limit <periods> --fields all` | 财务批处理，默认每批 100 个 code | `--limit` 为报告期数量，不是日线 start/end 日期 | 本次未观测；历史仓库证据为财报 100 行/批 | 本次未观测；历史仓库证据为财报每批 1 次 | no | 当前 worktree 找不到 `tools/bin/westock`，且已有能力是财报而非近期日线，不能提供 bootstrap 所需 symbol/date/amount 日线。 |
| Neodata（已有 Provider） | `valuation`、`industry`、`financial_quarterly`；默认 10 项/批 | 最多 10 个显式查询值/批；不做标的枚举 | 无日线 `start_date/end_date` 契约 | 本次未观测 | 本次未观测 | no | 不提供日线 OHLCV/amount；既有批量仅适用于估值、行业和财报，不能替代近期行情历史。 |

## 结论

选择批量主数据源必须同时证明：能以少于逐标的的远程请求取回全市场近期历史，并保留
`symbol`、日期与 `amount`。当前证据未证明任何一个候选满足该条件。

NO_BATCH_PRIMARY_AVAILABLE

后续 Task 8 只能消费已有的单标的 fallback 契约；除非先补充可复现的本地 callable
inventory 与受控小样本证据，否则不得新增或臆造批量行情 Provider。

## 未决担忧

- worktree 缺少 AkShare 可调用安装和 WeStock CLI，因而无法以本地帮助/签名验证候选端点；这不是 VPN 失败，未触发联网重试规则。
- 历史文档中的 WeStock 100 标的批处理只证明财报能力，不能外推到 K 线。
- 若未来恢复 AkShare 环境，探测应先以单个受控小样本检查返回字段、日期参数与实际 HTTP 调用数；不得直接运行全市场，且联网/VPN失败最多重试一次。
