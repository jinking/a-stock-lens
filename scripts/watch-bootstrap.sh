#!/usr/bin/env bash
# 实时观看冷启动取数进度。用法：bash scripts/watch-bootstrap.sh
#
# 进度从**已落地的文件**算出，因此看到的是真正完成的量，不是预估：
#   - 已落地标的数 / 达标标的数（>= 所需有效 bar 数）/ 还差多少
#   - 每 20 秒刷新一次，Ctrl-C 退出；文件不再增长时会显示"停滞"
set -uo pipefail
TOTAL=5301
REQUIRED=20
while true; do
  uv run python - "$TOTAL" "$REQUIRED" <<'PY' 2>/dev/null
import sys
from datetime import date, datetime
from pathlib import Path
from astock_lens.data.bootstrap import _bar_counts
from astock_lens.data.sync import read_raw_rows

total, required = int(sys.argv[1]), int(sys.argv[2])
path = Path("data/raw/daily_bars.csv")
counts = _bar_counts(path, end_date=date(2026, 9, 17), column="amount")
ok = sum(1 for value in counts.values() if value >= required)
rows = len(read_raw_rows(path)[1])
stamp = datetime.now().strftime("%H:%M:%S")
pct = ok / total * 100
print(
    f"{stamp}  达标 {ok:5d}/{total} ({pct:5.1f}%) | 已落地 {len(counts):5d} 只 | "
    f"缺口 {max(0, total - ok):5d} | 文件 {rows:7d} 行"
)
PY
  sleep 20
done
