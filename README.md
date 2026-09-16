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

项目处于 **bootstrap 阶段**：工程骨架与架构契约已就绪，业务算法尚未实现。

| 已具备 | 尚未实现 |
| --- | --- |
| 设计三件套（spec / PRODUCT / ARCHITECTURE） | Provider 与数据抓取 |
| 类型化配置加载 `load_app_config` | Normalizer 与 Data Quality Gate |
| 领域枚举、时间模型、6 个扩展契约 Protocol | Universe / Factor / Strategy / Market / Signal 算法 |
| `astock doctor` CLI 与 FastAPI `/health` | DuckDB + Parquet 存储 |
| 单元测试与契约测试 | Watchlist、深研 Adapter 实现、React 前端 |

包结构已按 `docs/ARCHITECTURE.md` 建立，`src/astock_lens/` 下的 `backtest`、`portfolio`、`events` 等目录只是预留边界，没有 V1 实现。

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

## 测试与质量检查

```bash
uv run pytest --cov=astock_lens --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

等价的 Makefile 目标：`make test`、`make lint`、`make typecheck`。

## 下一步

第一个垂直切片是让设计文档中的验收链真正跑通：先实现 Provider + Normalizer + Data Quality Gate，再实现 Factor 计算、第一个 Scanner 与 Candidate 快照，然后接上 `/health` 之外的第一个领域 API。

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
