# 环境操作红线（2026-09-19 事故复盘）

> 背景：本次会话为了装 PyArrow，把 `.venv` 里的依赖弄丢过一次（duckdb / pyarrow / akshare），
> 并且一度把阿里云 index 写进了 `pyproject.toml`、重解析了 `uv.lock`。已全部还原。这份文档
> 把"为什么"和"以后怎么做"钉死，避免下一个人再踩。

## 一、事故原因（uv 的语义，不是"下载会删东西"）

`uv run` / `uv sync` 不是"安装器"，是**让 `.venv` 精确等于「锁文件 + 本次指定的 extras」**：
不在本次解析结果里的包会被**卸载**，它是"对齐"，不是"追加"。

本项目把依赖分在 extras 里（见 `pyproject.toml`）：

- `data` = `duckdb` / `pyarrow`（`polars` 已于 2026-09-19 由所有者决定移除，见第四节）
- `providers` = `akshare`

**默认集合里没有这些包**，所以任何一次不带 `--extra` 的 `uv run` 都会把它们当作"不该在的包"清掉。

触发链（三步，全是操作失误）：

1. `uv pip install pyarrow` —— 往环境里塞了**锁文件之外**的包；
2. 紧接着一条**没带 `--extra`** 的 `uv run ...` —— uv 发现环境与锁定不一致，按默认集合重建，
   extras（duckdb / akshare）和那个外来 pyarrow 一起被卸载；
3. 为提速改用镜像 index 跑 `uv sync` —— uv 把 `[[tool.uv.index]]` 写进 `pyproject.toml`，
   并把 `uv.lock` 的 registry 全部重解析成镜像地址。

## 二、唯一正确的装包/同步方式

```bash
# 需要 data / providers 依赖时：只走这一条
UV_HTTP_TIMEOUT=1800 uv sync --locked --extra data --extra providers

# 如果只想跑命令、不希望它顺手改动环境（临时/受限网络下）
uv run --no-sync <命令>
```

禁止：

- `uv pip install <包>`（绕过锁文件，下一次 `uv run` 就会被对齐掉）；
- 不带 `--extra` 的裸 `uv run` 用来"装东西"；
- 用镜像 index 跑 `uv sync` 而不加 `--locked`（会改 `pyproject.toml` 与 `uv.lock`）。

慢网络注意：本机直连 PyPI 约 200KB/s 且会断流，uv 默认 2 分钟超时会掐断下载；把
`UV_HTTP_TIMEOUT` 调到 1800 秒可以让慢下载跑完。

## 三、当前环境状态（2026-09-19）

- 环境已与锁文件**账实相符**：`uv sync --locked --extra data --extra providers --dry-run` 输出
  `Would make no changes`；`duckdb 1.5.5`、`pyarrow 25.0.1`、`akshare 1.18.94`、
  `pytest 9.1.1`、`fastapi 0.141.1`；裸 `uv run pytest -q` = **917 passed / 0 skipped / EXIT=0**（2m34s）。
- `uv.lock` 与 `pyproject.toml` 已还原到 HEAD（误改原件备份在
  `var/benchmarks/restore-20260919/`）。

## 四、`polars` 的移除（2026-09-19，所有者决定 A）

**问题**：`data` extra 里声明了 `polars`，但它的 `polars-runtime-32`（46.1MiB）在本机网络上
反复超时/断流（直连 PyPI 约 200KB/s、清华/中科大/阿里云镜像同样失败），导致 `uv sync` 无法收敛，
环境长期处于"半成品"。

**事实核对**（决定了移除是安全的）：

- 全仓库 **0 处 `import polars`**（`rg 'import polars|from polars' src/ scripts/ tests/`），
  `pandas` 只是 `akshare` 的传递依赖（`uv pip show pandas` → `Required-by: akshare`）；
- `docs/ARCHITECTURE.md`、`docs/DATA_MODEL.md`、`docs/STORAGE.md` 的口径都只要求
  **Parquet（PyArrow）+ DuckDB**，没有任何规格要求 polars；
- 第二阶段 2.3–2.6 只需要 PyArrow。

**处理**：`uv remove --optional data polars` → `pyproject.toml` 的 `data` extra 变成
`duckdb>=1.0` + `pyarrow>=17.0`，`uv.lock` 中 polars 条目归零；随后
`uv sync --locked --extra data --extra providers` 使环境与锁文件一致（输出 `Would make no changes`）。
将来若真要引入 polars，先立规格再 `uv add --optional data polars`。

**待同步的陈旧表述**（不在本次改动范围，属其它任务文件）：`docs/STORAGE.md` §5 仍写
"`data` extra 已声明 `duckdb` / `polars` / `pyarrow`"、`docs/ROADMAP.md` 仍写
"`pyarrow` / `polars` 至今未安装"。这两处应随各自的文档任务更新。

## 四、关于"多份环境"

仓库只需要**一份**环境：主仓库根目录的 `.venv`。另一份出现在
`~/.codex/worktrees/full-market-bootstrap-redesign/a-stock-lens/.venv`，那是前一阶段在 **git
worktree（隔离工作树）** 里干活的副产物——uv 会为每个工作树目录建独立 `.venv`，不是刻意维持
"多份环境"。worktree 那份删掉不影响主仓库；保留则仅在"还要回到那个隔离工作树"时有意义。
