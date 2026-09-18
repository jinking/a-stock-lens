"""启动流程的读取成本：一次运行只读落地文件常数次，不按标的数重复读。

2026-09-18 全池实测发现的缺陷：首轮 5,301 只标的落地完成后，流程在收尾计数上
烧了 30 分钟以上的纯 CPU（`ps` 显示 96% CPU、零 TCP 连接、日志 31 分钟无输出）。
根因是 `_count_bars` 每只标的都把整份 `daily_bars.csv`（当时 97,641 行）重新读一遍
并解析一遍，于是"按标的计数"变成 O(标的数 × 文件行数)。

这条测试用可计数的 `read_raw_rows` 替代品把成本钉住：一次运行读取落地文件的次数
必须是常数级（每轮扩展一次 + 收尾一次），而不是随标的数增长。
"""

from datetime import UTC, date, datetime
from pathlib import Path

from astock_lens.data import bootstrap
from astock_lens.data.bootstrap import (
    BootstrapRequirement,
    bootstrap_liquidity_history,
)
from astock_lens.data.contracts import RawDataset, RawPayload
from astock_lens.domain.enums import DataStatus

AS_OF = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
END_DATE = date(2026, 9, 17)
BAR_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
)
SYMBOLS = tuple(f"{index:06d}.SZ" for index in range(60))


class CountingFetcher:
    """每只标的都返回足够长的历史，于是不会有扩展轮次。"""

    def __init__(self, *, days: int = 30) -> None:
        self._days = days

    def fetch_symbol_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        start_date: date,
        end_date: date,
    ) -> RawDataset:
        rows = tuple(
            (
                symbol,
                (end_date - __import__("datetime").timedelta(days=offset)).isoformat(),
                "1",
                "1",
                "1",
                "1",
                "1",
                "1000",
                "0.01",
            )
            for offset in range(self._days)
        )
        return RawDataset(
            provider="counting",
            dataset="daily_bars",
            fetched_at=datetime.now(UTC),
            provider_version="test",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=BAR_COLUMNS, rows=rows),
        )


def test_the_flow_reads_the_landed_file_a_constant_number_of_times(
    local_tmp: Path, monkeypatch
) -> None:
    real_read = bootstrap.read_raw_rows
    calls = {"count": 0}

    def counted_read(path: Path):
        calls["count"] += 1
        return real_read(path)

    monkeypatch.setattr(bootstrap, "read_raw_rows", counted_read)

    bootstrap_liquidity_history(
        provider=CountingFetcher(),
        root=local_tmp,
        as_of=AS_OF,
        symbols=SYMBOLS,
        requirement=BootstrapRequirement(
            factor_name="avg_amount_20d", required_valid_bars=20
        ),
        end_date=END_DATE,
        chunk_size=20,
    )

    # 一次运行最多读几次：覆盖判定 + 每轮扩展一次计数 + 收尾一次。60 只标的
    # 只应有的个位数次数；按标的重复读会是 60 次以上。
    assert calls["count"] <= 8, (
        "the landed file must be read a constant number of times per run, not "
        f"once per symbol; read {calls['count']} times for {len(SYMBOLS)} symbols"
    )
