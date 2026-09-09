"""
memory_fts package — SQLite FTS5 Hybrid Memory Recall Engine for NIFTY Agents.
"""

from .constants import _sanitize_fts_query
from .schema import FTSConnectionMixin
from .sync import FTSAutoSyncMixin
from .search import FTSSearchMixin
from .core import (
    NiftyMemoryFTS,
    get_memory_fts,
)

__all__ = [
    "_sanitize_fts_query",
    "FTSConnectionMixin",
    "FTSAutoSyncMixin",
    "FTSSearchMixin",
    "NiftyMemoryFTS",
    "get_memory_fts",
]
