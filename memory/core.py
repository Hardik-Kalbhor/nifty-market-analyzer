"""
memory/core.py — NiftyMemoryLog class definition and singleton access.
"""

import os
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import TIMEZONE
from .storage import MemoryStorageMixin
from .parser import MemoryParserMixin
from .resolution import MemoryResolutionMixin
from .context import MemoryContextMixin

logger = logging.getLogger(__name__)


class NiftyMemoryLog(
    MemoryStorageMixin,
    MemoryParserMixin,
    MemoryResolutionMixin,
    MemoryContextMixin,
):
    """Append-only NIFTY prediction memory log with self-reflection."""

    def __init__(self, history_dir: str | None = None) -> None:
        if history_dir is None:
            # Resolve relative to news_repo/history/
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history")
        else:
            base = history_dir

        try:
            os.makedirs(base, exist_ok=True)
            self._log_path = Path(base) / "memory_log.md"
        except (OSError, PermissionError):
            # Render ephemeral fallback
            fallback = "/tmp/history"
            os.makedirs(fallback, exist_ok=True)
            self._log_path = Path(fallback) / "memory_log.md"

        logger.debug(f"NiftyMemoryLog path: {self._log_path}")

        # Hermes-inspired SQLite FTS5 recall engine
        try:
            from memory_fts import get_memory_fts
            self._fts = get_memory_fts(str(self._log_path.parent))
        except Exception as fts_err:
            logger.warning(f"Memory: NiftyMemoryFTS init warning: {fts_err}")
            self._fts = None


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton accessor (lazy-init, cached per history_dir)
# ─────────────────────────────────────────────────────────────────────────────
_memory_log_instances: dict[str, NiftyMemoryLog] = {}
_mem_instances_lock = threading.Lock()


def get_memory_log(history_dir: str | None = None) -> NiftyMemoryLog:
    """Return the cached NiftyMemoryLog instance for the specified directory."""
    global _memory_log_instances
    with _mem_instances_lock:
        key = str(Path(history_dir).resolve()) if history_dir else "default"
        if key not in _memory_log_instances:
            _memory_log_instances[key] = NiftyMemoryLog(history_dir)
        return _memory_log_instances[key]


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile

    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

    with tempfile.TemporaryDirectory() as tmp:
        ml = NiftyMemoryLog(history_dir=tmp)

        # Phase A
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        ml.store_prediction(
            trade_date=today,
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=72,
            reasoning="GIFT Nifty +0.65%, FII net +₹1200Cr. Heavyweights positive.",
            fii_net=1200.0,
            gift_nifty_pct=0.65,
            india_vix=11.5,
        )

        # Phase D
        ctx = ml.load_past_context()
        print("Past context (empty on first run):", repr(ctx))

        # Stats
        stats = ml.get_stats()
        print("Stats:", json.dumps(stats, indent=2))

        print("\n✅ Smoke test passed.")
