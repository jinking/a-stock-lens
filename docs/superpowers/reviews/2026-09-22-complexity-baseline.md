# 复杂度收敛基线

## 基线身份

- 采集日期：2026-09-22
- 分支：`main`
- 基线提交：`3e412fb385b7f536318c2337dbba3a132f61b267`（交易准入：增加离线回放统计与产物校验）
- 原规格基线：`fe09b004904fcc6c7883f1abb5aab039b5dc6665`，已被当前 `main` 后续提交取代；本报告采用当前 HEAD。
- 基线在隔离的干净 Git worktree 中采集，依赖按锁文件同步；未纳入主工作区未提交改动。
- 本地 Python 为 3.14.3，项目要求为 Python `>=3.12`。

## 规模

| 指标 | 本地实测 |
| --- | ---: |
| pytest 收集用例 | 1,269 |
| 测试 Python 文件 | 133 |
| 测试 Python 源码字节 | 1,056,565 |
| `src/astock_lens` Python 文件 | 158 |
| `src/astock_lens` Python 源码字节 | 854,590 |
| Trade Gate Python 文件 | 16 |
| Trade Gate 测试文件 | 13 |

规格中的 GitHub tree 统计为 Python 生产文件 148、测试文件 123、Trade Gate 生产文件 6、Trade Gate 测试文件 3；当前 HEAD 已包含后续提交，因此以上本地数字优先作为本轮比较基准。

## 质量基线

- `PYTHONPATH= uv run --no-sync pytest -q`：1,269 passed，耗时 210.49 秒；9 条弃用警告，无失败。
- `PYTHONPATH= uv run --no-sync pytest --durations=50 -q`：1,269 passed，耗时 162.98 秒。
- `uv run --no-sync ruff check src tests`：通过。
- `uv run --no-sync mypy`：通过，检查 158 个源码文件。
- Trade Gate 指定基线：8 passed。
- Web：`npm test` 为 65 passed（9 个测试文件）；`npm run typecheck` 与 `npm run build` 均通过。

## CLI 与输入快照

- 已保存 `astock --help` 及 `stock`、`screen`、`qualified`、`candidates`、`today`、`watch`、`research` 的 `--help` 输出，所有命令退出码均为 0。
- 已对基线中的 69 个受跟踪 `tests/fixtures/`、`data/snapshots/`、`configs/` 文件计算 SHA-256，清单保存在本地基线目录 `var/complexity-reduction/baseline/fixture-config-snapshot-sha256.txt`。
- 本轮提供的 v2 计划提到“按前一版计划”采集 CLI 输出与 fixture snapshot hashes，但仓库及本次输入目录均未包含该前版计划。因此，CLI 范围按 Task 3/4 涉及的发现和生命周期命令扩展，哈希范围按上述受跟踪 fixtures、snapshots 与配置文件确定。

## 可复核产物

完整测试收集清单、测试/源码字节清单、运行输出、耗时、CLI 帮助、Web 检查及哈希清单均保存在忽略目录 `var/complexity-reduction/baseline/`，不纳入版本控制。
