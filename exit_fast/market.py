"""
exit_fast/market.py — Market calendar and heavyweight stock data fetchers.
"""

import logging
from datetime import datetime
from typing import Any
import yfinance as yf

from .constants import TIMEZONE, _safe_float, HEAVYWEIGHT_TICKERS
import yf_cache
import concurrent.futures

logger = logging.getLogger(__name__)

def is_expiry_day() -> bool:
    """Returns True if today is Tuesday (NIFTY 50 weekly expiry day in IST, effective Sep 2025)."""
    now_ist = datetime.now(TIMEZONE)
    return now_ist.weekday() == 1  # 0=Mon, 1=Tue


def fetch_heavyweight_stocks() -> dict[str, Any]:
    """
    Concurrently fetch live price and percent change for top 5 NIFTY heavyweights.
    Executes in ~200-350ms using yf_cache (shared retry + 5-min cache) with yfinance fallback.
    """
    stocks = {}

    def _fetch_single(ticker: str, meta: dict):
        # 1. yf_cache — cached, retried Yahoo Chart API (~0ms on hit, <300ms on miss)
        try:
            quote = yf_cache.fetch_quote(ticker, timeout=3.0)
            if quote:
                return ticker, {
                    "name": meta["name"],
                    "weight": meta["weight"],
                    "price": quote["price"],
                    "change_pct": quote["change_pct"],
                }
        except Exception as e:
            logger.debug(f"yf_cache failed for {ticker}: {e}")

        # 2. Fallback to yfinance library if cache also fails
        if yf:
            try:
                t = yf.Ticker(ticker)
                info = t.fast_info
                last_price = getattr(info, "last_price", None)
                prev_close = getattr(info, "previous_close", None)
                if last_price and prev_close and prev_close > 0:
                    pct = round(((last_price - prev_close) / prev_close) * 100, 2)
                    return ticker, {
                        "name": meta["name"],
                        "weight": meta["weight"],
                        "price": round(last_price, 2),
                        "change_pct": pct,
                    }
            except Exception as e:
                logger.debug(f"Error fetching {ticker} via yfinance: {e}")
        return ticker, None


    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(_fetch_single, sym, meta)
            for sym, meta in HEAVYWEIGHT_TICKERS.items()
        ]
        done, not_done = concurrent.futures.wait(futures, timeout=4.0)
        for f in not_done:
            f.cancel()

        for f in done:
            try:
                sym, data = f.result()
                if data:
                    stocks[sym] = data
            except Exception:
                pass

    return stocks



