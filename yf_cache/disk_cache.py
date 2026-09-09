"""
yf_cache/disk_cache.py — Persistent disk caching for historical daily bars.
"""

import json
import logging
import os
import time
from pathlib import Path

from .constants import _BARS_TTL_SECONDS

logger = logging.getLogger(__name__)


def _disk_cache_dir() -> Path:
    base = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "history" / ".yf_cache"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except (OSError, PermissionError):
        fallback = Path("/tmp/history/.yf_cache")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _disk_key(symbol: str, date_str: str) -> Path:
    safe = symbol.replace("^", "").replace(".", "_")
    return _disk_cache_dir() / f"{safe}_{date_str}.json"


def _disk_read(symbol: str, date_str: str) -> list[dict] | None:
    path = _disk_key(symbol, date_str)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < _BARS_TTL_SECONDS:
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
    return None


def _disk_write(symbol: str, date_str: str, bars: list[dict]) -> None:
    try:
        _disk_key(symbol, date_str).write_text(json.dumps(bars))
    except Exception as e:
        logger.debug(f"YFCache disk write failed: {e}")
