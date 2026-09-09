"""
yf_cache/constants.py — Constants, host configs, headers, and sentinels for Yahoo Finance Cache.
"""

# Cache TTLs
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

_MISS = object()  # sentinel for cache miss
