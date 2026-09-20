"""测试共用的输出处理工具。"""

import re

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """剥离 rich/typer 的着色转义，让断言只关心文本内容。

    在 `GITHUB_ACTIONS` / `FORCE_COLOR` 下 typer 会强制着色，rich 会把样式
    边界插进选项名内部（例如 `-\\x1b[0m-as-of`），直接按纯文本子串断言就会
    失配。断言前统一剥离转义后，测试结果不再取决于运行环境是否着色。
    """
    return ANSI_ESCAPE.sub("", text)
