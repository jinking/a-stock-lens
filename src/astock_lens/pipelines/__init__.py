"""Daily pipeline orchestration.

There is one analysis implementation: `astock_lens.pipelines.analysis`. The
`daily` module adds job timing, verdicts and the formal snapshot writes on top
of it; nothing else may compute factors, the Universe or strategy scores in
its own words.
"""

from astock_lens.pipelines.analysis import AnalysisState, run_analysis

__all__ = ["AnalysisState", "run_analysis"]
