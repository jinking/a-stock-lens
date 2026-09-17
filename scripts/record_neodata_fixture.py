"""把 neodata 的真实响应录成 fixture（逐字副本）。

和 `record_westock_fixture.py` 同一规矩：录下来的是服务端返回的 JSON 原文，
测试只回放它。因此测试不需要网络、不需要有效凭证，也不会因为服务端升级而失真。

用法：

    uv run python scripts/record_neodata_fixture.py

凭证不在参数里传：脚本按 `providers/neodata.py` 的解析顺序找凭证文件
（插件目录 → 旧路径 → 环境变量），任何一环都不回显内容。
"""

import json
import sys
from pathlib import Path

from astock_lens.data.providers.neodata import (
    TOKEN_ENV,
    NeodataProvider,
    load_token,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "neodata"

# 一条查询对应一个数据集。措辞是固化的模板：neodata 按意图匹配，措辞决定能不能取到数据，
# 所以模板写在 Provider 里、由测试钉住，脚本只是把它的真实响应录下来。
SYMBOLS = ("600519.SH", "000858.SZ", "000568.SZ")
SECTOR = "白酒Ⅱ"


def main() -> int:
    token, status = load_token()
    if not token:
        print(
            f"凭证不可用（{status}）：请刷新后重试，或设置 {TOKEN_ENV}", file=sys.stderr
        )
        return 1

    provider = NeodataProvider(token=token)
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    for dataset in ("valuation", "industry", "financial_quarterly"):
        symbols = (SECTOR,) if dataset == "industry" else SYMBOLS
        query = provider.build_query(dataset, symbols)
        payload = provider.post(query)
        path = FIXTURE_ROOT / f"{dataset}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        blocks = len(
            ((payload.get("data") or {}).get("apiData") or {}).get("apiRecall") or []
        )
        print(f"{dataset}: {blocks} 个内容块 -> {path.relative_to(ROOT)}")
        print(f"  查询: {query}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
