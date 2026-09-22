# Jev Test Failure Triage

本 Skill 用于在 `a-stock-lens` 开发过程中，把大量、边界清楚的 pytest 失败先交给 TypeSafe Jev 做低成本分类，再由 Codex 决定是否深入调查。

## 允许使用的场景

- 对 pytest failure 做根因类别初筛。
- 大量失败需要先分桶，再决定 Codex 的调查顺序。
- 需要区分实现错误、测试错误、缺失证据、环境问题、flaky 与证据不足。

## 禁止使用的场景

- 不得让 Jev 修改 Candidate Qualification 阈值、权重或词表。
- 不得让 Jev 决定 Candidate 是否发布、是否买卖、是否进入 Watchlist。
- 不得用 Jev 覆盖确定性 invariant、schema validation 或已经批准的设计文档。
- 不得把 `missing_evidence` 自动转换成 `0`、`False`、`NEUTRAL` 或任何默认业务值。
- 不得因为 Jev 高置信度而跳过必要测试。

## 调用方式

先准备 JSON：

```json
{
  "test_name": "tests/unit/test_x.py::test_y",
  "assertion": "expected ...",
  "traceback": "...",
  "related_files": ["src/astock_lens/..."],
  "context": "必要的业务上下文摘要"
}
```

然后执行：

```bash
uv run --extra jev python tools/jev_triage.py failure.json
```

也可以通过 stdin：

```bash
cat failure.json | uv run --extra jev python tools/jev_triage.py
```

## 结果解释

- `available=false`：TypeSafe 不可用。不要阻断主流程，直接由 Codex 自己分析。
- `category=uncertain`：证据不足，必须升级给 Codex 自己调查。
- `confidence >= 0.85`：只可把分类当作优先调查入口，不能当作最终事实。
- `0.65 <= confidence < 0.85`：仅作提示。
- `confidence < 0.65`：直接由 Codex 自己分析。

上述置信度区间仅用于当前 POC 的实验路由，不是 TypeSafe 官方规则；后续必须用真实失败样本校准。

## 输出类别

- `implementation_bug`
- `test_bug`
- `missing_evidence`
- `environment`
- `flaky`
- `uncertain`

## Agent 工作流

```text
pytest failure
→ 收集最小必要证据
→ Jev 分类
→ 若 unavailable / uncertain / 低置信度：Codex 直接调查
→ 否则：Codex 把分类当作调查起点
→ RED / GREEN
→ 完整测试
→ fresh reviewer
```

Jev 永远只是辅助判断器，不是项目规则源，也不是 reviewer。
