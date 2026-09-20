"""分红事件与因子分析执行链集成测试 (Plan D Task 3)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astock_lens.domain.enums import DataStatus
from astock_lens.factors.config import FactorConfig
from astock_lens.pipelines.stages import (
    factor_stage,
    normalize_stage,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 20, 15, 0, tzinfo=SHANGHAI)


def _factor_config() -> FactorConfig:
    return FactorConfig(
        name="dividend_yield_ttm",
        domain="VALUATION",
        description="Trailing dividend yield, in percent.",
        inputs=("dividend_yield_ttm",),
        frequency="DAILY",
        direction="HIGHER_MEANS_MORE_INCOME_RETURNED",
        null_policy="NULL_UNLESS_THE_METRIC_HAS_A_PUBLISHED_VALUE",
        version="v1",
    )


def test_pipeline_computes_dividend_yield_ttm_from_landed_events(
    tmp_path: Path,
) -> None:
    """测试分析管线从落地分红历史数据到产出有效 dividend_yield_ttm 因子。"""
    csv_root = tmp_path / "csv"
    bars_dir = csv_root / "daily_bars"
    div_dir = csv_root / "neodata" / "dividend_history"
    sec_dir = csv_root / "securities"
    bars_dir.mkdir(parents=True)
    div_dir.mkdir(parents=True)
    sec_dir.mkdir(parents=True)

    # 1. 写入证券名单
    sec_file = sec_dir / "securities.csv"
    sec_file.write_text(
        "symbol,name,list_date\n601398.SH,工商银行,2006-10-27\n",
        encoding="utf-8",
    )

    # 2. 写入日线行情 (股价 5.00 元)
    bar_file = csv_root / "daily_bars.csv"
    bar_file.write_text(
        "symbol,trade_date,open,high,low,close,volume,amount\n"
        "601398.SH,2026-09-18,5.00,5.00,5.00,5.00,1000000,5000000\n",
        encoding="utf-8",
    )

    # 3. 写入分红历史落地文件
    div_file = div_dir / "2026-09-20.csv"
    div_text = (
        "### 601398.SH 工商银行 分红信息\n"
        "| 公告日期 | 分红方案描述 | 股权登记日 | 除权除息日 | 方案进度 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 2026-06-25 | 10派3.06元 | 2026-07-15 | 2026-07-16 | 实施 |\n"
    )
    div_file.write_text(
        f'type,desc,content\n分红派息详细,分红派息详细,"{div_text}"\n',
        encoding="utf-8",
    )

    # 4. 执行 normalize_stage
    outcome = normalize_stage(csv_root=csv_root, as_of=AS_OF)
    assert len(outcome.bars.dividend_events) >= 1
    assert outcome.bars.dividend_events[0].symbol == "601398.SH"

    # 5. 执行 factor_stage
    results = factor_stage(
        outcome=outcome,
        factor_configs=(_factor_config(),),
        as_of=AS_OF,
    )
    assert len(results) == 1
    fr = results[0]
    assert fr.factor == "dividend_yield_ttm"
    assert fr.status == DataStatus.VALUE
    assert fr.raw_value is not None
    # 10 派 3.06 -> 每股 0.306 / 5.00 * 100 = 6.12%
    assert round(fr.raw_value, 4) == 6.1200
