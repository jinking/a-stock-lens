"""CSV 回放实现：从 Raw CSV 重新归一化（任务 2.2）。

这是"每次分析重新解析 Raw CSV"的那条路，算法原样搬自
`pipelines/stages.py` 的 `normalize_stage` / `financial_inputs` /
`valuation_inputs`。本任务只把读取点收敛成一个对象，**一行算法都没改**：
搬过来之后 `CsvNormalizedRepository.read()` 与旧的 `normalize_stage()` 必须
逐字段相等（有专门用例钉住）。
"""

from datetime import datetime
from pathlib import Path

from astock_lens.data.contracts import (
    FetchRequest,
    NormalizedDataset,
    RawDataset,
    RawPayload,
)
from astock_lens.data.normalize.csv_bars import CsvDailyBarNormalizer
from astock_lens.data.normalize.csv_securities import CsvSecurityNormalizer
from astock_lens.data.normalize.financials import (
    FinancialNormalizeOutcome,
    FinancialStatementNormalizer,
)
from astock_lens.data.normalize.valuations import NeodataValuationNormalizer
from astock_lens.data.providers.local import LocalCsvProvider
from astock_lens.data.providers.westock import FINANCIAL_DATASETS
from astock_lens.data.quality.financial_gate import (
    FinancialQualityGate,
    FinancialQualityReport,
    usable_observations,
)
from astock_lens.data.quality.gate import (
    DailyBarQualityGate,
    valid_bars,
)
from astock_lens.data.repository.models import (
    FinancialInputs,
    NormalizeOutcome,
    ValuationInputs,
)
from astock_lens.data.sync import latest_neodata_file, read_raw_rows
from astock_lens.domain.enums import DataStatus
from astock_lens.domain.models import FinancialObservation


class CsvNormalizedRepository:
    """从 Raw CSV 重新归一化一个时点。

    它是 `NormalizedRepository` 的默认实现：迁移期内它是唯一实现，将来 Parquet
    实现接上来之后，两者换的是读取点，不是算法。
    """

    def __init__(self, csv_root: Path) -> None:
        self._csv_root = csv_root

    @property
    def csv_root(self) -> Path:
        """这份仓库读的原始数据根。"""
        return self._csv_root

    def read(
        self, *, as_of: datetime, dataset: str, securities_dataset: str
    ) -> NormalizeOutcome:
        """Fetch, normalize, and gate one point in time.

        Only bars the gate did not flag move on; the report still records what
        was set aside, so the removal stays visible.
        """
        provider = LocalCsvProvider(self._csv_root)
        raw_bars = provider.fetch(FetchRequest(dataset=dataset, as_of=as_of))
        raw_securities = provider.fetch(
            FetchRequest(dataset=securities_dataset, as_of=as_of)
        )

        normalized = CsvDailyBarNormalizer().normalize(raw_bars, as_of=as_of)
        securities = CsvSecurityNormalizer().normalize(raw_securities, as_of=as_of)
        report = DailyBarQualityGate().check(normalized)

        financials = self.financial_inputs(as_of=as_of)
        valuations = self.valuation_inputs(as_of=as_of)

        gated = NormalizedDataset(
            dataset=normalized.dataset,
            as_of=normalized.as_of,
            daily_bars=valid_bars(normalized, report),
            # The factor engine reads one normalized dataset per symbol context, so
            # the fundamentals travel with the bars rather than beside them.
            observations=financials.observations,
            valuations=valuations.observations,
            parse_failures=normalized.parse_failures,
        )

        return NormalizeOutcome(
            raw_bars=raw_bars,
            raw_securities=raw_securities,
            quality_report=report,
            bars=gated,
            securities=securities.securities,
            financials=financials,
            valuations=valuations,
        )

    def financial_inputs(self, *, as_of: datetime) -> FinancialInputs:
        """Normalize and gate every landed financial statement.

        A statement that was never landed is named in `absent_datasets` rather
        than treated as an empty one: "nobody synced the balance sheet" and
        "the balance sheet had nothing in it" are different facts, and a factor
        has to be able to tell them apart.
        """
        provider = LocalCsvProvider(self._csv_root)
        normalizer = FinancialStatementNormalizer()
        gate = FinancialQualityGate()

        outcomes: list[FinancialNormalizeOutcome] = []
        reports: list[FinancialQualityReport] = []
        usable: list[FinancialObservation] = []
        absent: list[str] = []

        for dataset in sorted(FINANCIAL_DATASETS):
            raw = provider.fetch(FetchRequest(dataset=dataset, as_of=as_of))
            if raw.payload is None or not raw.payload.rows:
                absent.append(dataset)
                continue

            outcome = normalizer.normalize(raw, as_of=as_of)
            report = gate.check(
                outcome.observations,
                dataset=dataset,
                as_of=as_of,
                failures=outcome.failures,
            )
            outcomes.append(outcome)
            reports.append(report)
            usable.extend(usable_observations(outcome.observations, report))

        return FinancialInputs(
            outcomes=tuple(outcomes),
            reports=tuple(reports),
            observations=tuple(usable),
            absent_datasets=tuple(absent),
        )

    def valuation_inputs(self, *, as_of: datetime) -> ValuationInputs:
        """读取不晚于 `as_of` 的最新一天 neodata 估值落地，并归一化。

        时点由文件选择保证：未来日期的文件不会被读到（`latest_neodata_file`
        按 ISO 文件名比较）。没有落地过任何估值数据时 `source_file` 为 `None`——
        这是"还没同步"，与"市场没有估值"是两回事，因子层会因此报
        `NOT_APPLICABLE`，而不是把缺失当成 0。
        """
        path = latest_neodata_file(self._csv_root, "valuation", as_of=as_of)
        if path is None:
            return ValuationInputs(as_of=as_of)

        columns, rows = read_raw_rows(path)
        if not columns:
            return ValuationInputs(as_of=as_of, source_file=path)

        raw = RawDataset(
            provider="neodata",
            dataset="valuation",
            fetched_at=as_of,
            provider_version="v1",
            status=DataStatus.VALUE,
            row_count=len(rows),
            payload=RawPayload(columns=columns, rows=rows),
        )
        outcome = NeodataValuationNormalizer().normalize(raw, as_of=as_of)
        return ValuationInputs(
            as_of=as_of,
            source_file=path,
            observations=outcome.observations,
            absent_metrics=outcome.absent_metrics,
            failures=outcome.failures,
        )
