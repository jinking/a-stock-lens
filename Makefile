.PHONY: test test-fast test-stress lint typecheck

# 运行环境提示（详见 docs/DEVELOPMENT.md §7）：在 WorkBuddy 沙箱里，环境会经 PYTHONPATH
# 注入一个删除 shim，每次文件操作从 0.0125s 变成 0.372s（约 30 倍），全量因此从约 9 分半
# 变成跑不完，并可能让 tmp_path 夹具整批报 EEXIST。在那种环境里请显式置空：
#     make test PYTHONPATH=
# 下面的目标把 $(PYTHONPATH) 原样透传，所以默认行为不变（继承环境）。

# 全量回归（交付前）：串行，与验收基线同一种跑法。
test:
	PYTHONPATH=$(PYTHONPATH) uv run pytest

# 改动局部的快速回归：跳过 tests/stress/ 的全市场压力属性。
test-fast:
	PYTHONPATH=$(PYTHONPATH) uv run pytest tests/unit tests/contract tests/integration tests/artifacts

# 全市场压力属性（5,300 只标的）：改动 data/bootstrap*.py 或调度器时必跑。
# 对机器快慢敏感，见 docs/DEVELOPMENT.md §7.1。
test-stress:
	PYTHONPATH=$(PYTHONPATH) uv run pytest tests/stress

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy
