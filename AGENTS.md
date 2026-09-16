# AGENTS.md

本文件面向后续在此仓库工作的 Codex / AI agent。请先读完再动手。

## 权威来源

发生冲突时按此顺序裁决：

1. `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`
2. `docs/PRODUCT.md`
3. `docs/ARCHITECTURE.md`
4. `README.md`

未在设计文档中确认的阈值、权重与词表一律视为 `Deferred`，不要自行发明。

## 架构边界（不可越过）

- 依赖方向固定：`Provider → Raw → Normalized → Data Quality Gate → Universe → Factor → Strategy → Market Regime/Router → Market Validation → Signal → Candidate → Watchlist/Research → API/Web/CLI`。
- Strategy 不得直接调用 AkShare 或其他 Provider。
- API / Web 不得重新计算因子。
- Research 模块不得复制 `a-share-deep-research` 的业务，也不得把它作为 Python 依赖导入。两者只通过 `ResearchRequest` / `DeepResearchAdapter` 集成。
- 本地优先：V1 存储是 Parquet + DuckDB，不引入 PostgreSQL / Redis。

## 数据与时间规则

- 财务数据必须携带 `report_period`、`announce_date`、`available_at`，且 `available_at <= as_of`。
- 任何时间敏感的计算都必须保存 `as_of`。
- 快照必须预留 `universe_snapshot`、`factor_version`、`strategy_version` 血缘字段。
- 缺失数据只有 6 种状态：`VALUE`、`NULL`、`STALE`、`INVALID`、`SOURCE_ERROR`、`NOT_APPLICABLE`。
- **禁止静默兜底**：错误与缺失永远不得变成 0，也不得被省略。
- 时间戳必须带时区；`DTZ001` 在 lint 中是开启的。

## 生命周期

- Watchlist 活跃状态仅 `DISCOVERED`、`WATCH`、`DEEP_RESEARCH`、`TRACK_SIGNAL`。
- `READY`、`HOLDING`、`EXITED`、`ARCHIVED` 是预留状态，V1 不得触达。
- Candidate 是研究对象，不是推荐；不得输出买卖结论。

## 开发规则

- 先写失败测试，再写实现。没有失败证据的行为变更不要提交。
- 不为未实现的功能写假实现或假成功返回值。契约层只有类型、文档字符串与 `...`。
- 不提交未在设计文档中确认的默认阈值。

## 命令

```bash
uv sync                                  # 默认轻量环境
uv sync --extra data --extra providers   # 需要 DuckDB / PyArrow / Polars / AkShare 时
uv run pytest                            # 测试
uv run ruff check .                      # lint
uv run ruff format --check .             # 格式检查
uv run mypy                              # 严格类型检查
uv run astock doctor                     # 只读自检
```

`ruff` 与 `mypy` 的配置都在 `pyproject.toml`。`docs/` 被排除在 ruff 之外：设计文档中的 Python 代码块是正文，不是源码，不得被格式化器改写。

## 测试层次

- `tests/unit/`：领域模型、时间规则、枚举，以及未来的 Factor / Strategy / Signal / 状态机。
- `tests/contract/`：扩展契约的公开签名。
- `tests/integration/`：预留，用于 Provider → Normalize → Factor → Strategy 链路。
- `tests/artifacts/`：预留，用于独立 Artifact Validator 检查快照与 Candidate 产物。
- `tests/fixtures/`：预留，用于固定 Golden Dataset。
