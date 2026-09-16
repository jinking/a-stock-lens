"""Concrete data providers."""

from astock_lens.data.providers.akshare_provider import AkShareProvider
from astock_lens.data.providers.local import LocalCsvProvider

__all__ = ["AkShareProvider", "LocalCsvProvider"]
