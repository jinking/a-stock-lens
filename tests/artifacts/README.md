# tests/artifacts

预留目录：用于独立 Artifact Validator 检查最终产物，而不是复用实现内部逻辑。

计划校验项：

- Snapshot 完整性；
- Candidate 引用一致性；
- Factor / Strategy 版本是否齐全；
- score 范围与状态枚举合法性；
- `available_at <= as_of`；
- 因子引用是否存在。

当前没有任何校验器，因为还不存在快照产物。该校验器必须与生产实现**独立**：共用实现的校验逻辑无法发现实现自身的系统性错误。
