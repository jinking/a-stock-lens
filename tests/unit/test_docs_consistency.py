"""文档一致性测试：防止已闭环的 Candidate v2 / Market / Signal 状态在文档中出现过期断言。"""

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_readme_candidate_state_consistency() -> None:
    readme = (_repo_root() / "README.md").read_text(encoding="utf-8")
    assert "Candidate 阶段因为入选规则尚未批准而 `BLOCKED`" not in readme
    assert (
        "Market Regime、Market Validation、Signal 检测器（阈值 `Deferred`）"
        not in readme
    )
    assert "五个阶段显式 `BLOCKED`" not in readme
    assert "Candidate Qualification 规则（四个方案待所有者裁决）" not in readme


def test_roadmap_candidate_state_consistency() -> None:
    roadmap = (_repo_root() / "docs/ROADMAP.md").read_text(encoding="utf-8")
    assert "入选规则尚未批准" not in roadmap
    assert (
        "正式候选发布（Candidate Publishing）依然被既定产品门禁安全阻断" not in roadmap
    )
    assert (
        "Market Regime / Market Validation / Signal 三个模块：契约已就位，实现被上面第一节的阈值阻塞"
        not in roadmap
    )


def test_remaining_blockers_candidate_state_consistency() -> None:
    blockers = (_repo_root() / "docs/REMAINING_PRODUCT_BLOCKERS.md").read_text(
        encoding="utf-8"
    )
    assert "Candidate 阶段因为入选规则尚未批准" not in blockers
    assert (
        "目前日常管线中 `BUILD_CANDIDATES` 阶段被依法**强制安全阻断**" not in blockers
    )
    assert "src/astock_lens/signals/ 模块尚未构建" not in blockers
    assert "src/astock_lens/regime/ 尚未创建" not in blockers
