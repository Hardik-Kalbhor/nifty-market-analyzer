"""
market_signals/indices.py — NSE indices, India VIX, NIFTY 50, Bank NIFTY, and IT fetchers.
"""

import logging
import requests
from typing import Any
import yf_cache
from .constants import HEADERS

logger = logging.getLogger(__name__)

def _fetch_yahoo_chart_quote(symbol: str, timeout: float = 3.5) -> dict[str, Any] | None:
    """
    Fetch a live quote from Yahoo Finance — backed by yf_cache.
    Results are cached for 5 minutes and retried with exponential backoff.
    Returns {"price": float, "change_pct": float} or None.
    """
    return yf_cache.fetch_quote(symbol, timeout=timeout)



def _fetch_nse_indices() -> dict[str, Any]:
    """
    Scrape India VIX, Nifty 50 spot, Bank Nifty, Nifty IT from NSE India allIndices API.
    If NSE API fails or returns incomplete data (e.g. cloud IP blocking on Render),
    automatically falls back to direct Yahoo Chart API and then yfinance (^INDIAVIX, ^NSEI, ^NSEBANK, ^CNXIT).
    """
    vix_val = None
    vix_change_pct = None
    bank_nifty_pct = None
    it_nifty_pct = None
    nifty_spot = None
    nifty_pct = None

    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=HEADERS, timeout=4)
        res = session.get("https://www.nseindia.com/api/allIndices", headers=HEADERS, timeout=4)

        if res.status_code == 200:
            indices = res.json().get("data", [])
            for idx in indices:
                name = idx.get("index", "")
                if name == "INDIA VIX":
                    vix_val = float(idx.get("last", 13.5))
                    vix_change_pct = float(idx.get("percentChange", 0.0))
                elif name == "NIFTY 50":
                    nifty_spot = float(idx.get("last", 0.0))
                    nifty_pct = float(idx.get("percentChange", 0.0))
                elif name == "NIFTY BANK":
                    bank_nifty_pct = float(idx.get("percentChange", 0.0))
                elif name == "NIFTY IT":
                    it_nifty_pct = float(idx.get("percentChange", 0.0))

            if vix_val is not None and nifty_spot is not None:
                logger.info(f"NSE Indices scraped from official API: Nifty50={nifty_spot} ({nifty_pct}%), India VIX={vix_val} ({vix_change_pct}%), Bank Nifty={bank_nifty_pct}%, IT={it_nifty_pct}%")
    except Exception as e:
        logger.warning(f"Error fetching NSE indices from official API: {e}")

    # Fallback to direct Yahoo Finance Chart API if NSE API failed or returned missing data
    if vix_val is None or nifty_spot is None or bank_nifty_pct is None or it_nifty_pct is None:
        logger.info("Falling back to Yahoo Finance for Indian indices (^INDIAVIX, ^NSEI, ^NSEBANK, ^CNXIT)...")
        import concurrent.futures

        ticker_map = {
            "^INDIAVIX": "vix",
            "^NSEI": "nifty",
            "^NSEBANK": "bank",
            "^CNXIT": "it"
        }

        def _fetch_idx(sym: str, key: str):
            quote = _fetch_yahoo_chart_quote(sym, timeout=3.5)
            if quote:
                return key, quote["price"], quote["change_pct"]
            # Fallback to yfinance if direct chart API missed
            try:
                import yfinance as yf
                t = yf.Ticker(sym)
                fast = t.fast_info
                last = getattr(fast, "last_price", None)
                prev = getattr(fast, "previous_close", None)
                if last is not None:
                    pct = round(((last - prev) / prev) * 100, 2) if (prev is not None and prev > 0) else 0.0
                    return key, last, pct
            except Exception as ex:
                logger.debug(f"yfinance failed for {sym}: {ex}")
            return key, None, None

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(_fetch_idx, sym, k) for sym, k in ticker_map.items()]
                done, not_done = concurrent.futures.wait(futures, timeout=5.0)
                for f in not_done:
                    f.cancel()
                for f in done:
                    try:
                        k, last, pct = f.result()
                        if k == "vix" and vix_val is None and last is not None:
                            vix_val = round(last, 2)
                            vix_change_pct = pct
                        elif k == "nifty" and nifty_spot is None and last is not None:
                            nifty_spot = round(last, 2)
                            nifty_pct = pct
                        elif k == "bank" and bank_nifty_pct is None and pct is not None:
                            bank_nifty_pct = pct
                        elif k == "it" and it_nifty_pct is None and pct is not None:
                            it_nifty_pct = pct
                    except Exception:
                        pass

            logger.info(f"NSE Indices recovered via Yahoo Finance: Nifty50={nifty_spot} ({nifty_pct}%), India VIX={vix_val} ({vix_change_pct}%), Bank Nifty={bank_nifty_pct}%, IT={it_nifty_pct}%")
        except Exception as yf_err:
            logger.warning(f"Yahoo Finance fallback failed for NSE indices: {yf_err}")

    return {
        "india_vix": vix_val,
        "india_vix_change_pct": vix_change_pct,
        "nifty_spot": nifty_spot,
        "nifty_pct": nifty_pct,
        "bank_nifty_pct": bank_nifty_pct,
        "it_nifty_pct": it_nifty_pct,
    }


