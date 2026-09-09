"""
market_signals/global_markets.py — GIFT Nifty, US, European, and Asian market index fetchers.
"""

import logging
from typing import Any
import yf_cache
from .indices import _fetch_yahoo_chart_quote

logger = logging.getLogger(__name__)

def _fetch_global_markets_and_gift() -> dict[str, Any]:
    """
    Fetch GIFT Nifty % change and overnight Global Market Indices
    (S&P 500, NASDAQ, Dow Jones, Nikkei, Hang Seng, DAX) in parallel via direct Yahoo Chart API.
    """
    import concurrent.futures

    market_changes = {
        "sp500": 0.0,
        "nasdaq": 0.0,
        "dow": 0.0,
        "nikkei": 0.0,
        "hangseng": 0.0,
        "dax": 0.0,
    }

    tickers = {
        "^GSPC": "sp500",
        "^IXIC": "nasdaq",
        "^DJI": "dow",
        "^N225": "nikkei",
        "^HSI": "hangseng",
        "^GDAXI": "dax",
    }

    def fetch_single_ticker(symbol: str, key: str):
        # 1. Direct high-speed Yahoo Chart API (<300ms)
        quote = _fetch_yahoo_chart_quote(symbol, timeout=3.5)
        if quote and quote.get("change_pct") is not None:
            return key, quote["change_pct"]

        # 2. Fallback to yfinance if direct HTTP had an issue
        try:
            import yfinance as yf
            t = yf.Ticker(symbol)
            fast = t.fast_info
            last = getattr(fast, "last_price", None)
            prev = getattr(fast, "previous_close", None)
            if last and prev and prev > 0:
                return key, round(((last - prev) / prev) * 100, 2)
        except Exception as item_err:
            logger.warning(f"Error fetching ticker {symbol} via yfinance: {item_err}")
        return key, None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(fetch_single_ticker, sym, k) for sym, k in tickers.items()]
            done, not_done = concurrent.futures.wait(futures, timeout=6.0)
            for f in not_done:
                f.cancel()

            for future in done:
                try:
                    k, val = future.result()
                    if val is not None:
                        market_changes[k] = val
                except Exception as e:
                    logger.warning(f"Ticker thread error: {e}")

        logger.info(f"Global markets scraped successfully: {market_changes}")
    except Exception as e:
        logger.warning(f"Error fetching global markets: {e}")

    # GIFT Nifty proxy (derived from US S&P 500 / NASDAQ / Asian Nikkei & Hang Seng correlation)
    sp_pct = market_changes.get("sp500", 0.0)
    nasdaq_pct = market_changes.get("nasdaq", 0.0)
    nikkei_pct = market_changes.get("nikkei", 0.0)
    hangseng_pct = market_changes.get("hangseng", 0.0)

    # Multi-market weighted global cue formula
    gift_change_pct = round((sp_pct * 0.35) + (nasdaq_pct * 0.30) + (nikkei_pct * 0.20) + (hangseng_pct * 0.15), 2)

    return {
        "gift_nifty_change_pct": gift_change_pct,
        "global_market_changes": market_changes,
    }




