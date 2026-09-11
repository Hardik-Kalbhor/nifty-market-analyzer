"""
cognigraph/core.py — CogniGraph class definition and singleton access.
"""

import os
import threading
import logging
from pathlib import Path
from typing import Any

from .constants import DEFAULT_HALF_LIFE_DAYS
from .regime import RegimeMixin
from .storage import StorageMixin
from .extraction import ExtractionMixin
from .ingestion import IngestionMixin
from .retrieval import RetrievalMixin

logger = logging.getLogger(__name__)


class CogniGraph(
    RegimeMixin,
    StorageMixin,
    ExtractionMixin,
    IngestionMixin,
    RetrievalMixin,
):
    """
    Hierarchical Cognitive Knowledge Graph memory layer for autonomous trading agents.
    """

    def __init__(self, history_dir: str | None = None, half_life_days: float = DEFAULT_HALF_LIFE_DAYS):
        self.half_life_days = half_life_days
        self._lock = threading.RLock()
        if history_dir is None:
            base = os.getenv("HISTORY_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history"))
        else:
            base = history_dir

        try:
            os.makedirs(base, exist_ok=True)
            self._file_path = Path(base) / "cognigraph.json"
        except (OSError, PermissionError):
            fallback = "/tmp/history"
            os.makedirs(fallback, exist_ok=True)
            self._file_path = Path(fallback) / "cognigraph.json"

        self._triples: dict[str, Any] = {}
        self._episodes: dict[str, Any] = {}
        self._regime_index: dict[str, list[str]] = {}

        self._load_or_bootstrap()


_cognigraph_instance: CogniGraph | None = None
_instance_lock = threading.Lock()


def get_cognigraph(history_dir: str | None = None) -> CogniGraph:
    """Return process-level singleton CogniGraph instance, or new instance if explicit history_dir is given."""
    global _cognigraph_instance
    if history_dir is not None:
        if _cognigraph_instance is not None and str(_cognigraph_instance._file_path.parent) == str(Path(history_dir).resolve()):
            return _cognigraph_instance
        return CogniGraph(history_dir)

    if _cognigraph_instance is None:
        with _instance_lock:
            if _cognigraph_instance is None:
                _cognigraph_instance = CogniGraph()
    return _cognigraph_instance


def reset_cognigraph() -> None:
    """Reset the singleton instance (useful for test isolation)."""
    global _cognigraph_instance
    with _instance_lock:
        _cognigraph_instance = None
