"""
yf_cache/client.py — Yahoo Finance HTTP client with backoff retries, quote fetching, and daily bar fetching.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Any

import requests

from .constants import (
    _QUOTE_TTL_SECONDS,
    _BARS_TTL_SECONDS,
    _RETRY_DELAYS,
    _JITTER,
    _RATE_LIMIT_PAUSE,
    _YF_HOSTS,
    _YF_HEADERS,
    _MISS,
)
from .memory_cache import (
    _cache_key,
    _quote_bucket,
    _get,
    _set,
    _stats,
)
from .disk_cache import (
    _disk_read,
    _disk_write,
)

logger = logging.getLogger(__name__)


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


def fetch_quote(symbol: str, timeout: float = 4.0) -> dict[str, float] | None:
    """
    Fetch a live quote for `symbol` from Yahoo Finance.
    Returns {"price": float, "change_pct": float} or None on failure.

    Results are cached for 5 minutes (shared across all callers in the process).
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
    """
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
