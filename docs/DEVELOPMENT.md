# 开发指南

## 1. 环境

需要 Python >= 3.12 与 uv。

```bash
uv sync                                  # 默认轻量环境
uv sync --extra data --extra providers   # 需要 DuckDB / PyArrow / Polars / AkShare 时
```

可选依赖拆分的理由：bootstrap 阶段的测试只需要 CLI、API 与配置依赖，不应被迫安装大数据栈。

## 2. 常用命令

```bash
uv run pytest --cov=astock_lens --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run astock doctor
```

等价目标：`make test`、`make lint`、`make typecheck`。

## 3. 目录职责

- `src/astock_lens/domain/`：领域枚举与不可变模型；
- `src/astock_lens/data/`：Provider、Normalizer、Quality Gate、Repository 契约与实现；
- `src/astock_lens/universe|factors|strategies|market|signals|candidates|watchlist/`：对应 Pipeline 阶段；
- `src/astock_lens/research/`：深研适配器契约与模型；
- `src/astock_lens/pipelines|jobs/`：编排与运行状态；
- `src/astock_lens/api|cli/`：对外入口；
- `src/astock_lens/backtest|portfolio|events/`：预留边界，V1 无业务实现；
- `configs/`：YAML 配置，只放已确认的值；
- `data/`、`var/`：运行时数据与日志，不进版本库。

## 4. 工作流

1. 先写失败测试，确认它因为目标行为尚不存在而失败；
2. 写最小实现让测试通过；
3. 运行测试、lint、格式检查与类型检查；
4. 一个任务一个可评审的提交。

## 5. 边界与禁止事项

完整清单见根目录 `AGENTS.md`。最容易踩的两条：

- **禁止静默兜底**：缺失与错误不得变成 0，也不得被省略；
- **不要发明参数**：设计文档未确认的阈值与权重保持缺席或显式标注 `Deferred`。

## 6. 依赖与工具

Ruff 与 mypy 配置在 `pyproject.toml`，mypy 为 strict。`docs/` 被 ruff 排除：设计文档里的 Python 代码块是正文，不得被格式化器改写。

`ruff` 0.16 的默认规则包含 `DTZ001` 与 `UP017`，因此所有 `datetime` 字面量都必须带时区，且应使用 `datetime.UTC`。
