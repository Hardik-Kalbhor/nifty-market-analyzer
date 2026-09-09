"""
scheduler/constants.py — Environment constants, paths, and history cleanup.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

logger = logging.getLogger("AutoScheduler")

try:
    import pytz
    TIMEZONE = pytz.timezone("Asia/Kolkata")
except ImportError:
    from zoneinfo import ZoneInfo
    TIMEZONE = ZoneInfo("Asia/Kolkata")

try:
    HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history")
    os.makedirs(HISTORY_DIR, exist_ok=True)
except (OSError, PermissionError):
    HISTORY_DIR = "/tmp/history"
    os.makedirs(HISTORY_DIR, exist_ok=True)


def _cleanup_old_history(max_days: int = 2) -> None:
    """Delete analysis JSON files older than max_days from the history directory."""
    now = datetime.now(TIMEZONE)
    try:
        for fname in os.listdir(HISTORY_DIR):
            if not fname.startswith("analysis_") or not fname.endswith(".json"):
                continue
            fpath = os.path.join(HISTORY_DIR, fname)
            age_days = (now.timestamp() - os.path.getmtime(fpath)) / 86400
            if age_days > max_days:
                os.remove(fpath)
                logger.info(f"🗑️ Removed old history file: {fname} (age: {age_days:.1f} days)")
    except Exception as e:
        logger.warning(f"History cleanup error: {e}")
