"""
memory_fts/core.py — NiftyMemoryFTS class definition and singleton access.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from .schema import FTSConnectionMixin
from .sync import FTSAutoSyncMixin
from .search import FTSSearchMixin

logger = logging.getLogger(__name__)


class NiftyMemoryFTS(FTSConnectionMixin, FTSAutoSyncMixin, FTSSearchMixin):
    """SQLite FTS5-backed episodic memory and analog retrieval engine."""

    def __init__(self, history_dir: str | None = None):
        if history_dir is None:
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history")
        else:
            base = history_dir

        try:
            os.makedirs(base, exist_ok=True)
            self._db_path = Path(base) / "memory_fts.db"
        except (OSError, PermissionError):
            fallback = "/tmp/history"
            os.makedirs(fallback, exist_ok=True)
            self._db_path = Path(fallback) / "memory_fts.db"

        self._lock = threading.Lock()
        self._history_dir = self._db_path.parent
        self._init_db()
        self._auto_sync_from_markdown()


# Global singleton cache keyed by db directory path
_FTS_INSTANCES: dict[str, NiftyMemoryFTS] = {}
_INSTANCES_LOCK = threading.Lock()


def get_memory_fts(history_dir: str | None = None) -> NiftyMemoryFTS:
    """Get or initialize the NiftyMemoryFTS singleton for the given directory."""
    global _FTS_INSTANCES
    key = os.path.abspath(history_dir) if history_dir else "default"
    with _INSTANCES_LOCK:
        if key not in _FTS_INSTANCES:
            _FTS_INSTANCES[key] = NiftyMemoryFTS(history_dir)
        return _FTS_INSTANCES[key]
