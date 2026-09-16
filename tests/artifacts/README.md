# tests/artifacts

预留目录：用于独立 Artifact Validator 检查最终产物，而不是复用实现内部逻辑。

计划校验项：

- Snapshot 完整性；
- Candidate 引用一致性；
- Factor / Strategy 版本是否齐全；
- score 范围与状态枚举合法性；
- `available_at <= as_of`；
- 因子引用是否存在。

校验器已实现：`validator.py`（纯标准库，**不导入任何 `astock_lens` 生产代码**——共用实现自己的校验逻辑，就发现不了实现本身的系统性错误）。

`test_snapshot_validator.py` 先喂故意损坏的记录（缺键、越界评分、未知因子名、空版本、无时区时间戳、引用版本不一致），确认每一类损坏都被点名报出；再对每日扫描真实写入的四类快照做零发现校验。
