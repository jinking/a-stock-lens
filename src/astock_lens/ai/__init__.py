"""AI 辅助工具。

这里的 AI 组件只负责辅助判断，不得越过项目既有的确定性业务规则。
"""

from astock_lens.ai.jev import FailureCategory, FailureTriage, classify_test_failure

__all__ = ["FailureCategory", "FailureTriage", "classify_test_failure"]
