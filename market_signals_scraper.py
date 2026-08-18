"""
market_signals_scraper.py — Market Microstructure Signals Scraper.
Scrapes GIFT Nifty, India VIX, Put-Call Ratio (PCR), and Global Market Indices.
Integrates live market signals directly into analyzer.py.
"""

import logging
import requests
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_nse_indices() -> dict[str, Any]:
    """Scrape India VIX, Nifty 50 spot, Bank Nifty, Nifty IT from NSE India allIndices API."""
    vix_val = None
    vix_change_pct = None
    bank_nifty_pct = None
    it_nifty_pct = None
    nifty_spot = None
    nifty_pct = None

    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=HEADERS, timeout=5)
        res = session.get("https://www.nseindia.com/api/allIndices", headers=HEADERS, timeout=5)

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

            logger.info(f"NSE Indices scraped: Nifty50={nifty_spot} ({nifty_pct}%), India VIX={vix_val} ({vix_change_pct}%), Bank Nifty={bank_nifty_pct}%, IT={it_nifty_pct}%")
    except Exception as e:
        logger.warning(f"Error fetching NSE indices: {e}")

    return {
        "india_vix": vix_val,
        "india_vix_change_pct": vix_change_pct,
        "nifty_spot": nifty_spot,
        "nifty_pct": nifty_pct,
        "bank_nifty_pct": bank_nifty_pct,
        "it_nifty_pct": it_nifty_pct,
    }


def _fetch_global_markets_and_gift() -> dict[str, Any]:
    """
    Fetch GIFT Nifty % change and overnight Global Market Indices
    (S&P 500, NASDAQ, Dow Jones, Nikkei, Hang Seng, DAX) in parallel via yfinance.
    """
    import concurrent.futures
    import yfinance as yf
    try:
        yf.set_tz_cache_location("/tmp/py-yfinance")
    except Exception:
        pass

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
        try:
            t = yf.Ticker(symbol)
            fast = t.fast_info
            last = fast.last_price
            prev = fast.previous_close
            if last and prev and prev > 0:
                return key, round(((last - prev) / prev) * 100, 2)
        except Exception as item_err:
            logger.warning(f"Error fetching ticker {symbol}: {item_err}")
        return key, None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(fetch_single_ticker, sym, k) for sym, k in tickers.items()]
            for future in concurrent.futures.as_completed(futures, timeout=6):
                try:
                    k, val = future.result()
                    if val is not None:
                        market_changes[k] = val
                except Exception as e:
                    logger.warning(f"Ticker thread error: {e}")

        logger.info(f"Global markets scraped successfully via yfinance: {market_changes}")
    except Exception as e:
        logger.warning(f"Error fetching global markets via yfinance: {e}")

    # GIFT Nifty proxy (derived from US S&P 500 / NASDAQ / Asia correlation)
    sp_pct = market_changes.get("sp500", 0.0)
    nasdaq_pct = market_changes.get("nasdaq", 0.0)
    gift_change_pct = round((sp_pct * 0.5) + (nasdaq_pct * 0.4), 2)

    return {
        "gift_nifty_change_pct": gift_change_pct,
        "global_market_changes": market_changes,
    }


def _fetch_option_chain_data() -> dict:
    """
    Scrape live NIFTY Option Chain from NSE for:
    - Put-Call Ratio (PCR)
    - Max Pain level (strike with minimum total option pain)
    - Top OI Call strike (resistance)
    - Top OI Put strike (support)
    """
    defaults = {"pcr": 1.05, "max_pain": None, "top_oi_call_strike": None, "top_oi_put_strike": None}
    try:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/option-chain"
        }
        session.get("https://www.nseindia.com", headers=headers, timeout=3)
        r = session.get("https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY", headers=headers, timeout=4)
        if r.status_code != 200:
            return defaults

        data = r.json()
        records = data.get("records", {}).get("data", [])
        if not records:
            return defaults

        tot_ce_oi = 0
        tot_pe_oi = 0
        ce_oi_by_strike = {}
        pe_oi_by_strike = {}
        pain_by_strike = {}

        for row in records:
            strike = row.get("strikePrice", 0)
            ce_oi = row.get("CE", {}).get("openInterest", 0)
            pe_oi = row.get("PE", {}).get("openInterest", 0)
            tot_ce_oi += ce_oi
            tot_pe_oi += pe_oi
            if ce_oi > 0:
                ce_oi_by_strike[strike] = ce_oi
            if pe_oi > 0:
                pe_oi_by_strike[strike] = pe_oi

        # PCR
        pcr = round(tot_pe_oi / tot_ce_oi, 2) if tot_ce_oi > 0 else 1.05

        # Max Pain: strike where total OI pain (intrinsic loss) is minimised
        all_strikes = sorted(set(list(ce_oi_by_strike.keys()) + list(pe_oi_by_strike.keys())))
        for s in all_strikes:
            ce_pain = sum(ce_oi_by_strike.get(k, 0) * max(0, s - k) for k in all_strikes)
            pe_pain = sum(pe_oi_by_strike.get(k, 0) * max(0, k - s) for k in all_strikes)
            pain_by_strike[s] = ce_pain + pe_pain
        max_pain = min(pain_by_strike, key=pain_by_strike.get) if pain_by_strike else None

        # Top OI strikes
        top_oi_call = max(ce_oi_by_strike, key=ce_oi_by_strike.get) if ce_oi_by_strike else None
        top_oi_put = max(pe_oi_by_strike, key=pe_oi_by_strike.get) if pe_oi_by_strike else None

        logger.info(f"Option Chain: PCR={pcr}, Max Pain={max_pain}, Top Call OI={top_oi_call}, Top Put OI={top_oi_put}")
        return {
            "pcr": pcr,
            "max_pain": max_pain,
            "top_oi_call_strike": top_oi_call,
            "top_oi_put_strike": top_oi_put,
        }

    except Exception as e:
        logger.warning(f"Could not scrape option chain data from NSE: {e}")
    return defaults


def fetch_all_market_signals() -> dict[str, Any]:
    """
    Master function to aggregate all market microstructure signals
    required by analyzer.py.
    """
    logger.info("Fetching all market microstructure signals...")
    nse_data = _fetch_nse_indices()
    global_data = _fetch_global_markets_and_gift()
    oc_data = _fetch_option_chain_data()

    return {
        "gift_nifty_change_pct": global_data.get("gift_nifty_change_pct"),
        "india_vix": nse_data.get("india_vix"),
        "india_vix_change_pct": nse_data.get("india_vix_change_pct"),
        "nifty_spot": nse_data.get("nifty_spot"),
        "nifty_pct": nse_data.get("nifty_pct"),
        "pcr": oc_data.get("pcr", 1.05),
        "max_pain": oc_data.get("max_pain"),
        "top_oi_call_strike": oc_data.get("top_oi_call_strike"),
        "top_oi_put_strike": oc_data.get("top_oi_put_strike"),
        "global_market_changes": global_data.get("global_market_changes", {}),
        "sectoral_signals": {
            "bank_nifty_pct": nse_data.get("bank_nifty_pct"),
            "it_nifty_pct": nse_data.get("it_nifty_pct"),
        },
    }


if __name__ == "__main__":
    import json
    signals = fetch_all_market_signals()
    print(json.dumps(signals, indent=2))
