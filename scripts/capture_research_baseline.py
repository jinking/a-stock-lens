"""迁移前的研究诊断基线：一次只读分析，六个产物。

**这活为什么干。** 迁移到 Parquet + DuckDB 之后，要能回答"结果变了没有"。答案
只能来自一份**迁移前**、**同一份输入**、**可以逐字节复算**的产物。所以本脚本必须
是纯离线的：一次 `run_research_analysis`，多产物渲染，不碰正式快照 / Watchlist /
Job，不重跑任何外部抓取。一旦它开始依赖网络或正式状态，"基线"就变成一次会漂移的
快照，而不是证据。

**六个产物。**

| 文件 | 是什么 |
| --- | --- |
| `manifest.json` | 输入哈希、as_of、配置摘要、产物哈希；标记 `artifact_kind=research_diagnostic` |
| `factors.jsonl` | 每行一条因子结果，排序键 `(symbol, factor)` |
| `strategies.jsonl` | 每行一条策略结果，排序键 `(strategy_id, symbol)` |
| `research-universe.json` | 研究池决策：谁进来了、谁被什么规则挡在外面 |
| `calibration.json` | 校准报告（机器读） |
| `calibration.md` | 校准报告（人读） |

**两类不许违反的红线。**

1. **数值不四舍五入。** JSONL 每行直接是领域对象的 `model_dump_json()`：写进去的
   是算出来的那个浮点数，不是它的某个好看版本。四舍五入会在迁移比对时把真实的
   差异抹平——那正好是这份基线唯一要做的事。
2. **缺行业照样出诊断，但绝不假装完整。** canonical 成员缺 9 只是**事实**，写成
   `unknown_industry_symbols` 列出来；`require_full_industry_coverage` 关掉，因为
   这里的产物是诊断材料，不是决策材料。

`--industry-path` 是显式输入而不是按约定路径探测：基线必须能指向并记录它实际
用的那一份成员文件（连同 sha256），否则"用的是哪份映射"就无从复算。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from astock_lens.calibration.candidate_report import (
    IndustryEvidence,
    generate_calibration_report,
)
from astock_lens.calibration.render import render_json, render_markdown
from astock_lens.data.industry import build_industry_map
from astock_lens.data.sync import read_industry_memberships
from astock_lens.factors.config import load_factor_config
from astock_lens.pipelines.analysis import run_research_analysis
from astock_lens.strategies.registry import load_scanners, strategy_paths
from astock_lens.universe.config import load_universe_config

ARTIFACT_KIND = "research_diagnostic"
MANIFEST_NAME = "manifest.json"
FACTORS_NAME = "factors.jsonl"
STRATEGIES_NAME = "strategies.jsonl"
UNIVERSE_NAME = "research-universe.json"
CALIBRATION_JSON_NAME = "calibration.json"
CALIBRATION_MD_NAME = "calibration.md"
ARTIFACT_NAMES: tuple[str, ...] = (
    FACTORS_NAME,
    STRATEGIES_NAME,
    UNIVERSE_NAME,
    CALIBRATION_JSON_NAME,
    CALIBRATION_MD_NAME,
)

UNIVERSE_CONFIG_NAME = "universe.yaml"
FACTORS_DIR = "factors"
STRATEGIES_DIR = "strategies"

# 与 `astock_lens.cli.app` / `api.app` / `normalize.valuations` 同一套约定：裸日期
# 按 A 股收盘理解。
SHANGHAI = ZoneInfo("Asia/Shanghai")
A_SHARE_CLOSE_HOUR = 15

CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    """流式摘要：让"用的是哪一份输入"可以被复算。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def parse_as_of(value: str) -> datetime:
    """裸日期按上海收盘理解；完整 ISO 时间必须自带时区。"""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        parsed = _parse_aware(value)
        return parsed
    return datetime(day.year, day.month, day.day, A_SHARE_CLOSE_HOUR, tzinfo=SHANGHAI)


def _parse_aware(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"--as-of must be YYYY-MM-DD or a timezone-aware ISO datetime, got {value!r}"
        ) from error
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError(
            f"--as-of needs a timezone offset when a time is given, got {value!r}"
        )
    return parsed


def _write_jsonl(
    path: Path,
    records: Sequence[Any],
    *,
    key: Callable[[Any], tuple[str, str]],
) -> int:
    """按给定键排序后逐行写：每行就是领域对象自己的序列化结果。

    排序键必须是显式的、与输入顺序无关的，否则同一份输入会因为归一化阶段内部
    的迭代顺序而给出不同字节的文件，迁移比对就失去了基准。
    """
    ordered = sorted(records, key=key)
    with path.open("w", encoding="utf-8") as stream:
        for record in ordered:
            stream.write(record.model_dump_json() + "\n")
    return len(ordered)


def _write_json(path: Path, document: object) -> None:
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def capture(
    *,
    csv_root: Path,
    as_of: datetime,
    output_dir: Path,
    config_root: Path,
    industry_path: Path,
) -> Path:
    """跑一次只读研究诊断，落六个产物，返回 manifest 路径。

    输入先读、先失败：成员文件不存在时立刻抛 `FileNotFoundError`，绝不在输出目录
    里留下一份"看起来跑过了"的半成品。
    """
    # 两种失败必须分开：路径不存在是"你给错了"，文件没有成员是"那份文件是空的"。
    # `read_industry_memberships` 对不存在的文件返回空（那是它守的规矩：缺失不等于
    # 错误），所以这里先把"路径不存在"单独判掉，免得把两者混成一个"没有成员"。
    if not industry_path.is_file():
        raise FileNotFoundError(f"--industry-path does not exist: {industry_path}")
    memberships = read_industry_memberships(industry_path)
    if not memberships:
        raise ValueError(
            f"{industry_path}: no industry memberships; an empty mapping is not "
            "the same fact as a mapping that was never fetched"
        )
    industry_map = build_industry_map(memberships, as_of=as_of)
    visible_dates = [
        membership.as_of for membership in memberships if membership.as_of <= as_of
    ]
    evidence = IndustryEvidence(
        origin="canonical",
        source_ref=str(industry_path),
        source_sha256=sha256_file(industry_path),
        mapping_as_of=max(visible_dates, default=None),
        diagnostic_only=True,
    )

    universe_config_path = config_root / UNIVERSE_CONFIG_NAME
    factor_paths = tuple(sorted((config_root / FACTORS_DIR).glob("*.yaml")))
    scan_paths = strategy_paths(config_root / STRATEGIES_DIR)
    universe_config = load_universe_config(universe_config_path)
    factor_configs = tuple(load_factor_config(path) for path in factor_paths)
    scanners = load_scanners(config_root / STRATEGIES_DIR)

    # 唯一一次 canonical 分析：报告与两个交换文件都由这一步的返回结果渲染。
    population_state, analysis = run_research_analysis(
        csv_root=csv_root,
        as_of=as_of,
        universe_config=universe_config,
        factor_configs=factor_configs,
        scanners=scanners,
    )

    report = generate_calibration_report(
        as_of=analysis.as_of,
        strategy_results=analysis.strategy_results,
        factor_results=analysis.factor_results,
        industry_map=industry_map,
        industry_evidence=evidence,
        # 本任务的产物是诊断材料：缺行业要列出来，不是拒绝出报告。
        require_full_industry_coverage=False,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    factor_count = _write_jsonl(
        output_dir / FACTORS_NAME,
        analysis.factor_results,
        key=lambda record: (record.symbol, record.factor),
    )
    strategy_count = _write_jsonl(
        output_dir / STRATEGIES_NAME,
        analysis.strategy_results,
        key=lambda record: (record.strategy_id, record.symbol),
    )
    _write_json(
        output_dir / UNIVERSE_NAME,
        {
            "as_of": population_state.as_of.isoformat(),
            "listing_prefilter_count": len(population_state.listing_prefilter_symbols),
            "research_count": len(population_state.research_symbols),
            "listing_prefilter_symbols": list(
                population_state.listing_prefilter_symbols
            ),
            "research_symbols": list(population_state.research_symbols),
            "exclusions": [
                exclusion.model_dump(mode="json")
                for exclusion in population_state.excluded
            ],
        },
    )
    (output_dir / CALIBRATION_JSON_NAME).write_text(
        render_json(report), encoding="utf-8"
    )
    (output_dir / CALIBRATION_MD_NAME).write_text(
        render_markdown(report), encoding="utf-8"
    )

    record_counts = {
        FACTORS_NAME: factor_count,
        STRATEGIES_NAME: strategy_count,
        UNIVERSE_NAME: len(population_state.research_symbols),
        CALIBRATION_JSON_NAME: len(report.strategies),
        CALIBRATION_MD_NAME: None,
    }
    manifest_path = output_dir / MANIFEST_NAME
    _write_json(
        manifest_path,
        {
            "artifact_kind": ARTIFACT_KIND,
            # 这份产物是 var/acceptance 下的交换证据，不是业务状态，也没有被写进
            # 任何 SnapshotStore；迁移比对读它，正式链路不读它。
            "registered_as_business_state": False,
            "as_of": analysis.as_of.isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "sources": {
                "csv_root": str(csv_root),
                "config_root": str(config_root),
                "industry_path": str(industry_path),
            },
            "inputs": [
                _describe_input(path)
                for path in _input_paths(
                    industry_path, universe_config_path, factor_paths, scan_paths
                )
            ],
            "config_summary": {
                "universe_config_digest": universe_config.digest()[:12],
                "min_average_turnover_20d": universe_config.min_average_turnover_20d,
                "min_listing_days": universe_config.min_listing_days,
                "factor_versions": [
                    [config.name, config.version] for config in factor_configs
                ],
                "strategy_versions": [
                    [scanner.config.id, scanner.config.version] for scanner in scanners
                ],
            },
            "population": {
                "broad_listing_count": len(analysis.outcome.securities),
                "listing_prefilter_count": len(
                    population_state.listing_prefilter_symbols
                ),
                "research_count": len(population_state.research_symbols),
                "factor_result_count": factor_count,
                "strategy_result_count": strategy_count,
            },
            "coverage": {
                "unknown_industry_symbols": list(report.unknown_industry_symbols),
                "unknown_industry_count": report.unknown_industry_count,
                "industry_coverage_ratio": report.industry_coverage_ratio,
                "industry_evidence": report.industry_evidence.model_dump(mode="json"),
            },
            "artifacts": [
                _describe_artifact(
                    output_dir / name, name=name, records=record_counts[name]
                )
                for name in ARTIFACT_NAMES
            ],
        },
    )
    return manifest_path


def _input_paths(
    industry_path: Path,
    universe_config_path: Path,
    factor_paths: tuple[Path, ...],
    scan_paths: tuple[Path, ...],
) -> tuple[Path, ...]:
    """输入清单按路径稳定排序，成员文件排在最前（它是这一轮最易漂移的输入）。"""
    others = sorted(
        {*factor_paths, *scan_paths, universe_config_path}, key=lambda item: str(item)
    )
    return (industry_path, *others)


def _describe_input(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _describe_artifact(
    path: Path, *, name: str, records: int | None
) -> dict[str, object]:
    return {
        "name": name,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "records": records,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：只写 `--output-dir`。"""
    parser = argparse.ArgumentParser(
        prog="capture_research_baseline.py",
        description=("跑一次只读研究分析并落六个诊断产物（迁移前的可逐字节比对基线）"),
    )
    parser.add_argument("--csv-root", type=Path, required=True, help="Raw CSV 根目录")
    parser.add_argument(
        "--as-of",
        required=True,
        help="交易日 YYYY-MM-DD（按上海收盘），或带时区 ISO 时间",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="产物输出目录")
    parser.add_argument(
        "--config-root", type=Path, required=True, help="configs 根目录"
    )
    parser.add_argument(
        "--industry-path", type=Path, required=True, help="显式指定的行业成员 CSV"
    )
    options = parser.parse_args(argv)

    try:
        as_of = parse_as_of(options.as_of)
        manifest = capture(
            csv_root=options.csv_root,
            as_of=as_of,
            output_dir=options.output_dir,
            config_root=options.config_root,
            industry_path=options.industry_path,
        )
    except (OSError, ValueError) as failure:
        print(f"capture failed: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1

    print(f"manifest written: {manifest}")
    for name in ARTIFACT_NAMES:
        print(f"  {options.output_dir / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
