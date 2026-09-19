"""归一化数据读取契约（任务 2.2）。

Factor / Universe / Strategy 消费的是 `NormalizeOutcome`；它们不该知道那份数据
是从 Raw CSV 重新解析出来的，还是从已经落盘的归一化产物读出来的。这个协议就是
那条分界线。

写在这里的规则：

- `read` **只读**：它不写快照、不写任务记录、不改任何状态；
- 一次读取就是一次读取：调用方拿到 outcome 之后跨阶段复用，不是每个阶段再读
  一遍；
- 缺失或损坏**显式失败**：一个读不到的仓库不能让调用方悄悄回到 CSV，否则
  "分析跑在什么数据上"就没人说得清了。
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from astock_lens.data.repository.models import NormalizeOutcome


@runtime_checkable
class NormalizedRepository(Protocol):
    """只读一份已归一化的分析输入。"""

    def read(
        self, *, as_of: datetime, dataset: str, securities_dataset: str
    ) -> NormalizeOutcome:
        """只读已选数据源，缺失或损坏显式失败。"""
        ...
