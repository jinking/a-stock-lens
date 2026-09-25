"""文档一致性测试：防止已闭环的 Candidate v2 / Market / Signal 状态在文档中出现过期断言。"""

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


# 文件 → 不得再出现的过期文案（逐字来自原先三个用例）。
STALE_CLAIMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "README.md",
        (
            "Candidate 阶段因为入选规则尚未批准而 `BLOCKED`",
            "Market Regime、Market Validation、Signal 检测器（阈值 `Deferred`）",
            "五个阶段显式 `BLOCKED`",
            "Candidate Qualification 规则（四个方案待所有者裁决）",
        ),
    ),
    (
        "docs/ROADMAP.md",
        (
            "入选规则尚未批准",
            "正式候选发布（Candidate Publishing）依然被既定产品门禁安全阻断",
            "Market Regime / Market Validation / Signal 三个模块：契约已就位，实现被上面第一节的阈值阻塞",
        ),
    ),
    (
        "docs/REMAINING_PRODUCT_BLOCKERS.md",
        (
            "Candidate 阶段因为入选规则尚未批准",
            "目前日常管线中 `BUILD_CANDIDATES` 阶段被依法**强制安全阻断**",
            "src/astock_lens/signals/ 模块尚未构建",
            "src/astock_lens/regime/ 尚未创建",
        ),
    ),
)


def test_documentation_does_not_claim_stale_status() -> None:
    """三份文档合并为一张表：任何一条过期文案都点名文件与文案。"""
    stale: list[str] = []
    for path, phrases in STALE_CLAIMS:
        text = (_repo_root() / path).read_text(encoding="utf-8")
        for phrase in phrases:
            if phrase in text:
                stale.append(f"{path}: {phrase!r}")
    assert not stale, "文档仍在声称过期状态:\n" + "\n".join(stale)
