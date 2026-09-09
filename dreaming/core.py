"""
dreaming/core.py — DreamingEngine class definition and singleton access.
"""

from __future__ import annotations
import os
import threading
from pathlib import Path
from typing import Any

from .constants import TIMEZONE, _clean_float, _now_ist_str
from .harvest import HarvestMixin
from .exit_audit import ExitAuditMixin
from .axioms_storage import AxiomStorageMixin
from .axioms_synthesis import AxiomSynthesisMixin
from .consolidation import ConsolidationMixin
from .cycle import ConsolidationCycleMixin


class DreamingEngine(
    HarvestMixin,
    ExitAuditMixin,
    AxiomStorageMixin,
    AxiomSynthesisMixin,
    ConsolidationMixin,
    ConsolidationCycleMixin,
):
    """
    Orchestrates the post-market 20:00 IST consolidation cycle.
    """

    def __init__(self, history_dir: str | None = None):
        if history_dir:
            self._history_dir = Path(history_dir).resolve()
        else:
            self._history_dir = Path(__file__).resolve().parent.parent / "history"
        self._history_dir.mkdir(parents=True, exist_ok=True)
        self._axioms_path = self._history_dir / "macro_axioms.json"
        self._dream_report_path = self._history_dir / "dream_report.json"
        self._lock = threading.Lock()
        self._axioms: dict[str, dict[str, Any]] = {}
        self._load_axioms()



# Singleton factory
_dreaming_instances: dict[str, DreamingEngine] = {}
_dreaming_lock = threading.Lock()


def get_dreaming_engine(history_dir: str | None = None) -> DreamingEngine:
    """Return cached DreamingEngine for the specified directory."""
    with _dreaming_lock:
        key = str(Path(history_dir).resolve()) if history_dir else "default"
        if key not in _dreaming_instances:
            _dreaming_instances[key] = DreamingEngine(history_dir)
        return _dreaming_instances[key]
