"""归一化分析输入的数据模型（任务 2.2）。

这三个模型原来长在 `pipelines/stages.py` 里，但它们是**数据层的产物**：定义
"归一化结果长什么样"，而不是"怎么算出来"。移到这里之后，data 层可以自己声明
`NormalizedRepository` 的返回类型，而不必反过来 import pipelines。

模型本身一字未改——搬迁不改契约，`pipelines.stages` 仍以同一批名字重导出，
老 import 路径继续可用。
"""

from datetime import datetime
from pathlib import Path

from astock_lens.data.contracts import NormalizedDataset, RawDataset
from astock_lens.data.normalize.financials import FinancialNormalizeOutcome
from astock_lens.data.normalize.valuations import ValuationFailure
from astock_lens.data.quality.financial_gate import FinancialQualityReport
from astock_lens.data.quality.gate import QualityReport
from astock_lens.domain.models import (
    DomainRecord,
    FinancialObservation,
    SecurityProfile,
    ValuationObservation,
)


class FinancialInputs(DomainRecord):
    """Normalized and gated fundamentals for one point in time.

    `observations` holds only what survived the gate; the per-dataset outcomes
    and reports keep everything the gate rejected visible, and
    `absent_datasets` names the statements that were never landed at all.
    """

    outcomes: tuple[FinancialNormalizeOutcome, ...] = ()
    reports: tuple[FinancialQualityReport, ...] = ()
    observations: tuple[FinancialObservation, ...] = ()
    absent_datasets: tuple[str, ...] = ()


class ValuationInputs(DomainRecord):
    """某一时点可用的估值观测，以及它们来自哪一天的取数。

    `source_file` 为 `None` 表示还没有落过估值数据——这是一个**可见**的事实，
    而不是"市场没有估值"。
    """

    as_of: datetime
    source_file: Path | None = None
    observations: tuple[ValuationObservation, ...] = ()
    absent_metrics: tuple[str, ...] = ()
    failures: tuple[ValuationFailure, ...] = ()


class NormalizeOutcome(DomainRecord):
    """What NORMALIZE produced, with the raw metadata it came from.

    The raw datasets are kept on the outcome so a later stage — Data Health, or
    the job record — can report which provider dataset a run actually read
    without fetching anything again.
    """

    raw_bars: RawDataset
    raw_securities: RawDataset
    quality_report: QualityReport
    bars: NormalizedDataset
    securities: tuple[SecurityProfile, ...] = ()
    financials: FinancialInputs = FinancialInputs()
    valuations: ValuationInputs | None = None
