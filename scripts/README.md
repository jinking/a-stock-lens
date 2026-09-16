# scripts

本目录预留给运维与数据脚本，例如批量回填、快照校验、数据健康巡检。

V1 尚未加入任何脚本：所有已实现的能力都通过一等公民的 CLI 暴露（`uv run astock ...`），避免出现"只能靠脚本调用"的隐藏入口。

新增脚本前先确认该能力是否更适合作为 `astock` 子命令；CLI 必须能被 cron 与 coding agent 直接使用。

## 已加入的脚本

它们的共同点是**产物是测试或原始数据，而不是业务结果**，因此不适合做成 CLI 子命令：

- `generate_fixtures.py`：生成 `tests/fixtures/csv/` 下的行情/名单 fixture；
- `record_akshare_fixture.py`：把 AkShare 的真实返回录制为契约 fixture；
- `record_westock_fixture.py`：把腾讯 WeStock CLI 的真实返回录制为契约 fixture（需要
  `ASTOCK_WESTOCK_BIN` 指向二进制）。录制文件是命令 stdout 的**逐字**副本，测试只回放
  它，因此测试不需要网络、Node.js 或该二进制。

WeStock 二进制本身不随本仓库分发，安装方式见设计规格 §24 补遗：它由运维提供，通过
`ASTOCK_WESTOCK_BIN` 指路，`astock doctor` 会报告它是否可用。
