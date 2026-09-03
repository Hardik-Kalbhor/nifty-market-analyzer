"""
yf_cache.py — Shared Yahoo Finance Cache & Retry Layer.

Provides thread-safe, TTL-based in-memory + optional disk caching for all
Yahoo Finance chart API calls across the project:

    market_signals_scraper.py  → fetch_quote()
    exit_fast_path.py          → fetch_quote()
    memory_log.py (Phase B)    → fetch_daily_bars()

Cache strategy
--------------
  Live quotes   : 5-minute TTL in-memory keyed by (symbol, 5-min bucket)
  Daily bars    : 24-hour TTL in-memory; also written to disk for cross-
                  restart reuse (history/.yf_cache/<symbol>_<date>.json)

Retry strategy
--------------
  3 attempts, exponential backoff: 1s → 2s → 4s (±200ms jitter).
  On HTTP 429 (rate limit): immediate 30s back-off before next attempt.
  Alternates between query1 and query2 hosts on each attempt to spread load.

Thread safety
-------------
  A module-level threading.Lock guards the in-memory dict so concurrent
  ThreadPoolExecutor fetches in market_signals_scraper / exit_fast_path
  never race to populate the same cache slot.

No new dependencies — only `requests` (already in requirements.txt) + stdlib.
"""

import json
import logging
import math
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_QUOTE_TTL_SECONDS = 5 * 60          # 5 minutes for live quotes
_BARS_TTL_SECONDS  = 24 * 3600       # 24 hours for historical daily bars
_RETRY_DELAYS      = [1.0, 2.0, 4.0] # exponential back-off seconds
_JITTER            = 0.2             # ± seconds of random jitter
_RATE_LIMIT_PAUSE  = 30.0            # seconds to wait after HTTP 429

_YF_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]

_YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

# ─────────────────────────────────────────────────────────────────────────────
# In-memory cache (process-level singleton)
# ─────────────────────────────────────────────────────────────────────────────

_cache: dict[str, dict] = {}       # key → {"data": Any, "expires_at": float}
_cache_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0, "errors": 0, "retries": 0}


def _cache_key(*parts) -> str:
    return "|".join(str(p) for p in parts)


def _quote_bucket() -> int:
    """5-minute time bucket for live quote TTL keying."""
    return math.floor(time.time() / _QUOTE_TTL_SECONDS)


_MISS = object()  # sentinel for cache miss — defined before _get()/_set() use it


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



# ─────────────────────────────────────────────────────────────────────────────
# Optional disk cache for daily bars
# ─────────────────────────────────────────────────────────────────────────────

def _disk_cache_dir() -> Path:
    base = Path(os.path.dirname(__file__)) / "history" / ".yf_cache"
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


# ─────────────────────────────────────────────────────────────────────────────
# Core HTTP fetch with retry
# ─────────────────────────────────────────────────────────────────────────────

def _http_get_with_retry(url_template: str, timeout: float) -> dict | None:
    """
    Attempt a GET request with exponential backoff retry.
    url_template must contain {host} which alternates between YF hosts.
    Returns parsed JSON dict or None on complete failure.
    """
    for attempt, delay in enumerate(_RETRY_DELAYS):
        host = _YF_HOSTS[attempt % len(_YF_HOSTS)]
        url = url_template.format(host=host)
        try:
            r = requests.get(url, headers=_YF_HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                logger.warning(f"YFCache: Rate limit hit (attempt {attempt+1}). Backing off {_RATE_LIMIT_PAUSE}s.")
                _stats["retries"] += 1
                time.sleep(_RATE_LIMIT_PAUSE)
                continue
            if r.status_code in (401, 403):
                logger.debug(f"YFCache: Auth error {r.status_code} for {url} — giving up.")
                return None
            logger.debug(f"YFCache: HTTP {r.status_code} on attempt {attempt+1} for {url}")
        except requests.exceptions.Timeout:
            logger.debug(f"YFCache: Timeout on attempt {attempt+1}")
        except Exception as e:
            logger.debug(f"YFCache: Request error on attempt {attempt+1}: {e}")

        _stats["retries"] += 1
        jitter = random.uniform(-_JITTER, _JITTER)
        sleep_time = delay + jitter
        if attempt < len(_RETRY_DELAYS) - 1:
            logger.debug(f"YFCache: Retrying in {sleep_time:.1f}s...")
            time.sleep(sleep_time)

    _stats["errors"] += 1
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_quote(symbol: str, timeout: float = 4.0) -> dict[str, float] | None:
    """
    Fetch a live quote for `symbol` from Yahoo Finance.
    Returns {"price": float, "change_pct": float} or None on failure.

    Results are cached for 5 minutes (shared across all callers in the process).
    Replaces the inline _fetch_yahoo_chart_quote() in market_signals_scraper.py
    and the direct HTTP block in exit_fast_path.py.
    """
    key = _cache_key("quote", symbol, _quote_bucket())
    cached = _get(key)
    if cached is not _MISS:
        logger.debug(f"YFCache HIT  quote:{symbol}")
        return cached

    _stats["misses"] += 1
    logger.debug(f"YFCache MISS quote:{symbol} → fetching")

    url_tpl = (
        f"https://{{host}}/v8/finance/chart/{symbol}"
        f"?interval=1d&range=5d"
    )
    data = _http_get_with_retry(url_tpl, timeout)
    if not data:
        return None

    try:
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        meta = result[0].get("meta", {})
        last = meta.get("regularMarketPrice")
        chg_pct = meta.get("regularMarketChangePercent")
        if chg_pct is None:
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if last is not None and prev is not None and prev > 0:
                chg_pct = ((last - prev) / prev) * 100
        if last is None:
            return None
        quote = {
            "price": round(float(last), 2),
            "change_pct": round(float(chg_pct), 2) if chg_pct is not None else 0.0,
        }
        _set(key, quote, _QUOTE_TTL_SECONDS)
        return quote
    except Exception as e:
        logger.debug(f"YFCache: Failed to parse quote for {symbol}: {e}")
        _stats["errors"] += 1
        return None


def fetch_daily_bars(
    symbol: str,
    period1_ts: int,
    period2_ts: int,
    timeout: float = 8.0,
) -> list[dict[str, Any]]:
    """
    Fetch daily OHLCV bars for `symbol` between period1_ts and period2_ts (Unix timestamps).
    Returns list of {"date": "YYYY-MM-DD", "open": float, "high": float,
                      "low": float, "close": float, "volume": int}.

    Results are cached for 24 hours in memory AND on disk so Phase B outcome
    resolution doesn't re-fetch the same historical open price after a server restart.

    Replaces the inline HTTP logic in memory_log._fetch_nifty_actual_gap().
    """
    # Disk cache key uses the resolution date (period2 date) so it's stable
    p2_date = datetime.utcfromtimestamp(period2_ts).strftime("%Y-%m-%d")
    disk_data = _disk_read(symbol, p2_date)
    if disk_data is not None:
        logger.debug(f"YFCache DISK-HIT bars:{symbol}/{p2_date}")
        _stats["hits"] += 1
        return disk_data

    mem_key = _cache_key("bars", symbol, p2_date)
    cached = _get(mem_key)
    if cached is not _MISS:
        logger.debug(f"YFCache HIT  bars:{symbol}/{p2_date}")
        return cached

    _stats["misses"] += 1
    logger.debug(f"YFCache MISS bars:{symbol}/{p2_date} → fetching")

    url_tpl = (
        f"https://{{host}}/v8/finance/chart/{symbol}"
        f"?interval=1d&period1={period1_ts}&period2={period2_ts}&events=history"
    )
    data = _http_get_with_retry(url_tpl, timeout)
    if not data:
        return []

    try:
        result = data.get("chart", {}).get("result", [])
        if not result:
            return []
        chart = result[0]
        timestamps = chart.get("timestamp", [])
        ohlcv = chart.get("indicators", {}).get("quote", [{}])[0]
        opens  = ohlcv.get("open",   [])
        highs  = ohlcv.get("high",   [])
        lows   = ohlcv.get("low",    [])
        closes = ohlcv.get("close",  [])
        vols   = ohlcv.get("volume", [])

        bars = []
        for i, ts in enumerate(timestamps):
            date_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            open_px  = opens[i]  if i < len(opens)  else None
            close_px = closes[i] if i < len(closes) else None
            if open_px is None or close_px is None:
                continue
            bars.append({
                "date":   date_str,
                "open":   round(float(open_px), 2),
                "high":   round(float(highs[i]), 2)  if i < len(highs)  and highs[i]  else None,
                "low":    round(float(lows[i]), 2)   if i < len(lows)   and lows[i]   else None,
                "close":  round(float(close_px), 2),
                "volume": int(vols[i]) if i < len(vols) and vols[i] else 0,
            })

        _set(mem_key, bars, _BARS_TTL_SECONDS)
        _disk_write(symbol, p2_date, bars)
        return bars

    except Exception as e:
        logger.debug(f"YFCache: Failed to parse bars for {symbol}: {e}")
        _stats["errors"] += 1
        return []


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


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

    print("=== yf_cache smoke test ===")

    # Test fetch_quote (requires network)
    print("\n1. fetch_quote('^INDIAVIX') — live test (needs internet):")
    q = fetch_quote("^INDIAVIX", timeout=6.0)
    if q:
        print(f"   VIX: {q['price']} ({q['change_pct']:+.2f}%)")
    else:
        print("   ⚠️  No data (market may be closed or network unavailable)")

    # Test caching — second call should be a HIT
    print("\n2. fetch_quote('^INDIAVIX') second call — should be CACHE HIT:")
    q2 = fetch_quote("^INDIAVIX", timeout=6.0)
    stats = cache_stats()
    print(f"   hits={stats['hits']}, misses={stats['misses']}, hit_rate={stats['hit_rate_pct']}%")
    assert stats["hits"] >= 1, "Expected at least one cache hit on second call"
    print("   ✅ Cache hit confirmed")

    # Test invalidate
    print("\n3. invalidate('^INDIAVIX'):")
    n = invalidate("^INDIAVIX")
    print(f"   Evicted {n} entries.")

    print("\n✅ Smoke test complete.")
