# A-Stock Lens

本地优先、单用户、面向全 A 股的多策略选股与研究生命周期系统。

它不把选股当成一次性条件过滤，而是管理完整研究过程：

`全市场发现 → 策略解释 → 市场验证 → 交易状态 → 观察池 → 深度研究 → 持续跟踪`

## Candidate ≠ Recommendation

系统输出 Candidate、Research Priority 与 Signal State，不输出"强烈买入"这类结论。Candidate 是一个**研究对象**，不是推荐；`next_action` 只允许 `IGNORE`、`WATCH`、`DEEP_RESEARCH`、`TRACK_SIGNAL`。

## 与 a-share-deep-research 的关系

两个仓库保持独立。A-Stock Lens 负责全市场发现与生命周期管理；证据密集的公司深度研究由现有 `a-share-deep-research` 承担。

集成方式是标准 `ResearchRequest` + `DeepResearchAdapter` 松耦合：V1 提供 CLI Adapter，未来可替换为 HTTP Adapter。A-Stock Lens 只保存 `ResearchSummary` 与产物引用，不复制深研报告与证据库，也不把对方作为 Python 依赖导入。

## 架构链路

严格单向的依赖方向：

```text
External Provider → Raw → Normalized → Data Quality Gate → Universe
  → Factor → Strategy → Market Regime/Router → Market Validation
  → Signal → Candidate → Watchlist / Research → API / Web / CLI
```

关键约束：

- Strategy 不得直接调用 AkShare；
- API / Web 不得重新计算因子；
- Research 模块不得复制深研项目业务；
- Provider 内部不得写入策略判断。

## V1 范围与非目标

V1 做：全 A 股 Universe、每日增量同步、约 40–60 个核心 Factor、7 个独立 Scanner（Value / Growth / GARP / Quality / Dividend / Momentum / Industry Trend）、Market Regime、Market Validation、Signal、Candidate 快照、Watchlist 状态机、深研适配器、6 个前端页面。

V1 不做：自动下单、券商交易 API、分钟级实时扫描、机器学习选股、LLM 直接决定买卖、复杂 Portfolio Optimizer、完整历史回测平台、期货/期权、港股/美股、多用户与权限、云端 SaaS 部署。

详见 `docs/PRODUCT.md`。

## 当前状态

项目处于**每日扫描切片已贯通**：`CSV → Raw → Normalized → Quality Gate → Universe → Factor → Strategy（横截面评分排名）→ Candidate → 四类快照` 可以端到端跑通，且不需要网络、不需要可选依赖。

| 已具备 | 尚未实现 |
| --- | --- |
| 设计三件套（spec / PRODUCT / ARCHITECTURE） | Market Regime、Market Validation、Signal |
| 类型化配置加载；阈值/因子/权重全部写在 YAML | Watchlist 状态机、深研 Adapter 实现、React 前端 |
| 领域枚举、时间模型、扩展契约 Protocol | `confidence` 算法（设计未定义，保持 `null`） |
| 本地 CSV Provider、Normalizer、Data Quality Gate | 权重正式评审（当前是等权草案 `PENDING REVIEW`） |
| Universe 引擎与不可变 `UniverseSnapshot`（含 deferred rule 上报） | 停牌天数数据源（设置 `long_suspension_days` 阈值的前置依赖） |
| 动量因子（`ret_20d` / `ret_60d` / `proximity_52w_high`）+ 流动性因子 | Parquet 行情存储 |
| 横截面评分与排名（percentile 加权混合）、`next_action` 路由（D5：仅按排序） | |
| `DuckDBSnapshotStore` 与 JSON store 同协议互换（`ASTOCK_SNAPSHOT_BACKEND=duckdb`） | |
| AkShare Provider（腾讯域日线 + 三交易所名单）+ 真实录制契约 fixture | |
| CLI `doctor` / `universe build` / `scan` / `factors compute`；API `/health` `/universe` `/factors` `/candidates` | |

包结构已按 `docs/ARCHITECTURE.md` 建立，`src/astock_lens/` 下的 `backtest`、`portfolio`、`events` 等目录只是预留边界，没有 V1 实现。

### 本切片刻意留空的部分

- **权重仍是等权草案。** `configs/strategies/momentum.yaml` 的 `weights:` 已生效（三条动量因子各 1.0），但标注 `PENDING REVIEW`——正式评审前它只是占位，不是结论。
- **`confidence` 恒为 `null`。** 设计要求该字段但未定义算法；资格判定已要求全部因子在场，"因子齐备比例"会恒等于 1.0，那是一个看起来有用实则无信息的数。
- **停牌天数诚实缺失。** 交易所名单不提供停牌天数，`suspended_trading_days` 允许 `None`（缺失 ≠ 0）。给 `long_suspension_days` 设阈值前，必须先有提供停牌天数的数据源。
- **快照后端可选。** 默认 JSON（零依赖），`ASTOCK_SNAPSHOT_BACKEND=duckdb` 切到 DuckDB，两者同协议。
- **窗口不完整即 `NULL`。** 60 日窗口内少一天，`ret_60d` 输出 `NULL`，不用更短的窗口凑数。

## 环境要求与安装

需要 Python >= 3.12 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync                                   # 默认轻量环境（CLI / API / 配置）
uv sync --extra data --extra providers    # 需要 DuckDB / PyArrow / Polars / AkShare 时
```

DuckDB、PyArrow、Polars 与 AkShare 是可选依赖，因此 bootstrap 阶段的测试不需要安装大数据栈。

## 快速检查

```bash
uv run astock --help
uv run astock doctor
```

`doctor` 只读本地文件：检查 Python 版本、加载 `configs/app.yaml`、报告配置中的存储路径是否存在。它不会抓取行情、不会连接外部数据源、也不会创建 DuckDB 文件。

### 跑一遍每日扫描

数据源指向本地 CSV 目录（默认 `data/raw`），快照写入目录（默认 `data/snapshots`），两者都可用环境变量覆盖：

```bash
export ASTOCK_CSV_ROOT=tests/fixtures/csv
export ASTOCK_SNAPSHOT_ROOT=tests/.tmp/demo
export ASTOCK_DATASET=daily_bars_long            # 长 fixture：300 个交易日

uv run astock universe build --as-of 2026-09-04  # 每条规则的判定结果 + UNIVERSE 快照
uv run astock scan --as-of 2026-09-04            # 排名、评分、next_action、四类快照
uv run astock factors compute --as-of 2026-09-04 # 每个因子一行 JSON，走 stdout

uv run uvicorn --factory astock_lens.api.app:create_app
curl "http://127.0.0.1:8000/universe?as_of=2026-09-04"
curl "http://127.0.0.1:8000/candidates?as_of=2026-09-04"
```

`--as-of` 接受交易日 `YYYY-MM-DD`，按当日 A 股收盘（15:00 +08:00）解析。

接真实数据时把 `ASTOCK_CSV_ROOT` 换成 AkShare 抓取落地目录，或等 `providers` 链路直接接 `AkShareProvider`（已实现，fixture 录制脚本见 `scripts/record_akshare_fixture.py`）。

`--as-of` 接受交易日 `YYYY-MM-DD`，按当日 A 股收盘（15:00 +08:00）解析。`factors compute` 的 JSON 走 stdout、运行说明走 stderr，因此可以直接管道给别的工具。

## 测试与质量检查

```bash
uv run pytest --cov=astock_lens --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

等价的 Makefile 目标：`make test`、`make lint`、`make typecheck`。

## 下一步

1. **独立 Artifact Validator**（`tests/artifacts/`）：不经过生产代码，直接校验真实扫描产物的键、取值范围、版本与时间戳。
2. **AkShare 全市场落地**：`securities` 名单（5564 只）与全市场日线的批量抓取与限流。
3. **权重正式评审**：把等权草案换成评审后的权重。
4. **Market Regime / Signal / Watchlist**：按设计文档顺序继续。

每条切片的计划都放在 `docs/superpowers/plans/`，设计权威仍是 `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`。

## 文档索引

- `docs/PRODUCT.md`：产品说明与 V1 范围
- `docs/ARCHITECTURE.md`：技术架构与模块边界
- `docs/DATA_MODEL.md`：时间模型、快照血缘、缺失状态与生命周期
- `docs/STRATEGY_SYSTEM.md`：7 个 Scanner 与共同契约
- `docs/DATA_SOURCES.md`：批量数据源与深研集成边界
- `docs/DEVELOPMENT.md`：开发环境与工作流
- `docs/TESTING.md`：测试体系
- `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`：完整设计规格
- `web/README.md`：前端页面规划

权威顺序：设计 spec → `docs/PRODUCT.md` → `docs/ARCHITECTURE.md` → `README.md`。
