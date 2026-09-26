# source: westock CLI
# endpoint: kline
# params: {"start": "2026-09-22", "end": "2026-09-22", "period": "day", "fq": "nofq", "codes": ["sh999999","sh000000"]}
# fetched_at: 2026-09-22T13:35:00+00:00
# rows: 0
# notes: 上报"success"但实际数据为空。这是契约里必须按 NULL 而非 VALUE 处理的情况。
#        Provider 应通过 requested ∖ returned 计算 missing_symbols，而非信任 Batch 状态。

[Batch] 状态: success | 总数: 2 | 成功: 2 | 失败: 0

数据为空
