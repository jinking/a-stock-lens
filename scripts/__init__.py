"""仓库内一次性脚本的包根。

`scripts/` 里的脚本要能被测试直接 import（例如
`from scripts.audit_research_baseline import inventory`），前提是它首先是一个
**包**，并且仓库根在 `sys.path` 上。前者由本文件保证，后者由
`pyproject.toml` 的 `[tool.pytest.ini_options] pythonpath = ["."]` 保证。

这里刻意不导出任何东西：脚本仍是可独立运行的文件，不是库。
"""
