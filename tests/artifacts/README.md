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

`validate_job_manifest` 校验每日 Pipeline 留下的另一类产物：Job Manifest（`spec §15` / `ARCHITECTURE.md` §17）。校验项：11 个阶段是否都有运行记录、同一阶段是否重复、`BLOCKED`/`FAILED` 是否写明原因、非问题状态是否误填 error、终态是否记录 `finished_at`、`finished_at` 是否早于 `started_at`、`as_of` 是否与该日一致。`test_job_manifest_validator.py` 同样先用损坏记录验证每类检查会失败，再对 `run_daily` 真实写出的 manifest 做零发现校验。

`MARKET_REGIME` 快照目前没有生产者（`DETECT_REGIME` 被 `BLOCKED`），因此校验器不对它做零发现断言：缺失由 `astock daily` 显式列出，而不是被校验器默认通过。
