"""行业成员映射的领域记录与映射装配。

来源是既有 WeStock CLI（`sector` 组），按 2026-09-18 的 Task 7A 实测：目录
`sector ranking --kind industry` 可枚举（124 个申万二级板块，稳定 `pt0…` 代码），
成员 `sector constituent <代码>` 给出 `code,name` 且标题自带层级声明。

本模块只负责**记录与映射**，解析在 `data.normalize.industry`：与其余数据层一样，
Raw 保持源站形状，规范化才转成 Canonical Schema。

一条红线写在代码里而不是文档里：同一只标的落在两个不同板块时**拒绝**，报
`BLOCKED_PRIMARY_INDUSTRY_SEMANTICS`。申万二级本身是划分，所以正常情况下不会触发；
它防的是源站将来改成"概念/主题"口径时，我们悄悄按先到先得给出一个假的主行业。
"""

import os
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from astock_lens.data.providers.westock import BINARY_ENV, DEFAULT_BINARY
from astock_lens.domain.models import DomainRecord

# 依赖方向：记录与来源在本模块，解析在 `data.normalize.industry`。两者分开是为了
# 不出现循环导入（normalize 需要这里的记录类型，这里不反过来依赖 normalize）。


class IndustryCatalogEntry(DomainRecord):
    """目录里的一行：板块身份，不含成员。"""

    industry_id: str
    industry_name: str


class IndustryMembership(DomainRecord):
    """一只标的在某一时点属于某个行业板块的证据。"""

    symbol: str
    industry_id: str
    industry_name: str
    as_of: datetime
    provider: str
    source_ref: str | None = None


class IndustryMembershipAmbiguous(RuntimeError):
    """同一只标的在 as_of 落在多个行业，且来源未声明主行业语义。"""


class SectorSourceUnavailable(RuntimeError):
    """取行业数据的外部命令不可用。"""


SectorRunner = Callable[[Sequence[str]], str]


class IndustrySource(Protocol):
    """行业目录与成员的来源：两个只读调用，返回原文。"""

    @property
    def provider(self) -> str: ...

    def catalog_text(self) -> str: ...

    def constituent_text(self, industry_id: str) -> str: ...


class WestockSectorSource:
    """WeStock CLI 的 `sector` 组：目录与成员两个只读调用。

    二进制路径与 WeStock Provider 共用同一套约定（默认 `tools/bin/westock`，
    可用 `ASTOCK_WESTOCK_BIN` 覆盖），因此本机装好一次，两条链路都通。
    """

    def __init__(
        self,
        binary: Path | str | None = None,
        *,
        runner: SectorRunner | None = None,
        provider: str = "westock-cli",
        timeout: float = 120.0,
    ) -> None:
        configured = binary if binary is not None else os.getenv(BINARY_ENV)
        self._binary = Path(configured) if configured else DEFAULT_BINARY
        self._runner = runner if runner is not None else self._run
        self._provider = provider
        self._timeout = timeout

    @property
    def provider(self) -> str:
        return self._provider

    def catalog_text(self) -> str:
        return self._runner(
            (str(self._binary), "sector", "ranking", "--kind", "industry")
        )

    def constituents(self, entry: IndustryCatalogEntry) -> str:
        """兼容旧调用：一个板块的成员响应原文。"""
        return self.constituent_text(entry.industry_id)

    def constituent_text(self, industry_id: str) -> str:
        """一个板块的成员响应原文（标题即该板块的名字）。"""
        return self._runner(
            (
                str(self._binary),
                "sector",
                "constituent",
                industry_id,
                "--limit",
                "0",
            )
        )

    def _run(self, argv: Sequence[str]) -> str:
        binary = Path(argv[0])
        if not binary.is_file():
            raise SectorSourceUnavailable(
                f"WeStock CLI not found at {binary}; install it or point "
                f"{BINARY_ENV} at the binary"
            )
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=self._timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise SectorSourceUnavailable(
                f"{' '.join(argv)} exited {completed.returncode}: "
                f"{completed.stderr.strip()[:200]}"
            )
        return completed.stdout


def build_industry_map(
    memberships: Sequence[IndustryMembership],
    *,
    as_of: datetime,
) -> dict[str, str]:
    """把成员关系折成 `symbol -> industry`，拒绝多归属。

    时点由 `as_of` 保证：晚于 as_of 的记录不可见（与其余数据层同一条规则）。
    同一 (symbol, industry) 重复出现是源站分页/重试的产物，去重即可；
    同一 symbol 落在两个不同 industry 则是语义问题，必须显式失败。
    """
    mapping: dict[str, str] = {}
    ids: dict[str, str] = {}
    for membership in sorted(
        memberships, key=lambda item: (item.symbol, item.industry_id)
    ):
        if membership.as_of > as_of:
            continue
        known = ids.get(membership.symbol)
        if known is not None and known != membership.industry_id:
            raise IndustryMembershipAmbiguous(
                "BLOCKED_PRIMARY_INDUSTRY_SEMANTICS: "
                f"{membership.symbol} appears in both {known!r} "
                f"({mapping[membership.symbol]!r}) and "
                f"{membership.industry_id!r} ({membership.industry_name!r}); the "
                "source declares no primary-industry semantics, so choosing one "
                "would be an invention"
            )
        ids[membership.symbol] = membership.industry_id
        mapping[membership.symbol] = membership.industry_name
    return mapping
