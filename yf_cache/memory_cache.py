"""
yf_cache/memory_cache.py — In-memory TTL cache and metrics tracking.
"""

import logging
import math
import threading
import time
from typing import Any

from .constants import _QUOTE_TTL_SECONDS, _MISS

logger = logging.getLogger(__name__)

# In-memory cache (process-level singleton)
_cache: dict[str, dict] = {}       # key → {"data": Any, "expires_at": float}
_cache_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0, "errors": 0, "retries": 0}


def _cache_key(*parts) -> str:
    return "|".join(str(p) for p in parts)


def _quote_bucket() -> int:
    """5-minute time bucket for live quote TTL keying."""
    return math.floor(time.time() / _QUOTE_TTL_SECONDS)


def _get(key: str) -> Any:
    """Return cached value or _MISS sentinel."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() < entry["expires_at"]:
            _stats["hits"] += 1
            return entry["data"]
        if entry:
            del _cache[key]  # evict stale entry
    return _MISS


def _set(key: str, data: Any, ttl: float) -> None:
    with _cache_lock:
        _cache[key] = {"data": data, "expires_at": time.time() + ttl}


def invalidate(symbol: str | None = None) -> int:
    """
    Evict cached entries.
    If symbol is given, evict only that symbol's entries.
    If None, clear the entire in-memory cache.
    Returns number of evicted entries.
    """
    with _cache_lock:
        if symbol is None:
            count = len(_cache)
            _cache.clear()
            logger.info(f"YFCache: Full cache invalidated ({count} entries).")
            return count
        keys_to_drop = [
            k for k in _cache
            if k.startswith(f"quote|{symbol}|") or k.startswith(f"bars|{symbol}|")
        ]
        for k in keys_to_drop:
            del _cache[k]
        logger.info(f"YFCache: Invalidated {len(keys_to_drop)} entries for {symbol}.")
        return len(keys_to_drop)


def cache_stats() -> dict:
    """Return cache performance metrics (hits, misses, hit-rate, errors, retries, size)."""
    with _cache_lock:
        total = _stats["hits"] + _stats["misses"]
        hit_rate = round(_stats["hits"] / total * 100, 1) if total > 0 else 0.0
        live_entries = sum(1 for v in _cache.values() if time.time() < v["expires_at"])
    return {
        "hits":        _stats["hits"],
        "misses":      _stats["misses"],
        "errors":      _stats["errors"],
        "retries":     _stats["retries"],
        "hit_rate_pct": hit_rate,
        "live_entries": live_entries,
    }
