#!/usr/bin/env bash
# 冷启动取数的旁观进度（可选的便利工具，不是主要观测手段）。
#
# 主要观测手段是命令自己：`astock sync-bootstrap` 现在每 10–20 秒打印一行心跳
# （processed/satisfied/failed/pending/inflight/throughput/elapsed），数字全部来自
# 本次调用。本脚本只适合在第二块屏幕上盯"文件长了多少"。
#
# 所有数字都从本次运行的清单与落地文件推导，不写死总数、所需 bar 数或日期：
#   data/raw/bootstrap/<as-of>/manifest.json 给出本次运行的 as-of 与所需 bar 数。
#   用法：bash scripts/watch-bootstrap.sh [raw_root] [as-of]
#   raw_root 默认 data/raw；as-of 默认取该根目录下最新的一次冷启动运行。
set -uo pipefail

RAW_ROOT="${1:-data/raw}"
AS_OF="${2:-}"

while true; do
  uv run python - "$RAW_ROOT" "$AS_OF" <<'PY' 2>/dev/null
import json
import sys
from datetime import date, datetime
from pathlib import Path

from astock_lens.data.bootstrap import _bar_counts
from astock_lens.data.sync import read_raw_rows

root = Path(sys.argv[1])
wanted = sys.argv[2]
runs = sorted((root / "bootstrap").glob("*/manifest.json"))
stamp = datetime.now().strftime("%H:%M:%S")
if not runs:
    print(f"{stamp}  还没有冷启动清单：{root / 'bootstrap'}")
else:
    chosen = [path for path in runs if path.parent.name == wanted] if wanted else runs
    manifest_path = (chosen or runs)[-1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    as_of = manifest["as_of"]
    required = manifest["required_valid_bars"]
    entries = manifest["entries"]
    landed = sum(1 for entry in entries if entry["status"] == "success")
    counts = _bar_counts(
        root / "daily_bars.csv", end_date=date.fromisoformat(as_of), column="amount"
    )
    satisfied = sum(1 for value in counts.values() if value >= required)
    rows = len(read_raw_rows(root / "daily_bars.csv")[1])
    print(
        f"{stamp}  {as_of}  清单 {len(entries):5d} 只 | 达标 {satisfied:5d} "
        f"(需 {required} 根) | 已落地 {landed:5d} 只 | 文件 {rows:7d} 行"
    )
PY
  sleep 20
done
