"""Daily pipeline orchestration."""

from astock_lens.pipelines.first_slice import FirstSliceResult, run_first_slice

__all__ = ["FirstSliceResult", "run_first_slice"]
