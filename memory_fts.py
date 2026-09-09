# memory_fts.py — backward-compatibility shim
from memory_fts import (  # noqa: F401
    _sanitize_fts_query,
    FTSConnectionMixin,
    FTSAutoSyncMixin,
    FTSSearchMixin,
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
