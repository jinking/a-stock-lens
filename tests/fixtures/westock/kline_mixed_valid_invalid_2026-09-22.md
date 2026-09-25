# source: westock CLI
# endpoint: kline
# params: {"start": "2026-09-22", "end": "2026-09-22", "period": "day", "fq": "nofq", "codes": ["sh600519","sh999999"]}
# fetched_at: 2026-09-22T13:35:00+00:00
# rows: 1
# notes: 有效+无效混合：Batch 状态为 success，但只有 1 只返回；sh999999 应进入 missing_symbols。

[Batch] 状态: success | 总数: 2 | 成功: 2 | 失败: 0

| code | date | open | last | high | low | volume | amount | exchange | change_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sh600519 | 2026-09-22 | 1252.15 | 1253.8 | 1265.88 | 1248.1 | 24573 | 3088530000 | 0.2 | 0.0981981047 |
