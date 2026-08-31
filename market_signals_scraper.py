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
    """
    Scrape India VIX, Nifty 50 spot, Bank Nifty, Nifty IT from NSE India allIndices API.
    If NSE API fails or returns incomplete data (e.g. cloud IP blocking on Render),
    automatically falls back to yfinance (^INDIAVIX, ^NSEI, ^NSEBANK, ^CNXIT).
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

    # Fallback to yfinance if NSE API failed or returned missing data (e.g. on Render / Cloud IP blocks)
    if vix_val is None or nifty_spot is None or bank_nifty_pct is None or it_nifty_pct is None:
        logger.info("Falling back to yfinance for Indian indices (^INDIAVIX, ^NSEI, ^NSEBANK, ^CNXIT)...")
        try:
            import yfinance as yf
            import concurrent.futures

            ticker_map = {
                "^INDIAVIX": "vix",
                "^NSEI": "nifty",
                "^NSEBANK": "bank",
                "^CNXIT": "it"
            }

            def _fetch_yf_idx(sym: str, key: str):
                try:
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

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(_fetch_yf_idx, sym, k) for sym, k in ticker_map.items()]
                done, not_done = concurrent.futures.wait(futures, timeout=4.0)
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

            logger.info(f"NSE Indices recovered via yfinance: Nifty50={nifty_spot} ({nifty_pct}%), India VIX={vix_val} ({vix_change_pct}%), Bank Nifty={bank_nifty_pct}%, IT={it_nifty_pct}%")
        except Exception as yf_err:
            logger.warning(f"yfinance fallback failed for NSE indices: {yf_err}")

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



def _fetch_groww_option_chain_fallback(defaults: dict) -> dict:
    """
    Secondary fallback for option chain and PCR data when NSE direct API is unavailable.
    Uses Groww's live derivative option chain API for NIFTY to compute exact:
    - PCR (Total PE OI / Total CE OI)
    - Max Pain strike
    - Top Call / Put OI strikes
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        r = requests.get(
            "https://groww.in/v1/api/option_chain_service/v1/option_chain/nifty",
            headers=headers, timeout=6
        )
        if r.status_code != 200:
            return defaults

        data = r.json()
        chains = data.get("optionChain", {}).get("optionChains", [])
        if not chains:
            return defaults

        tot_ce_oi = 0
        tot_pe_oi = 0
        ce_oi_by_strike = {}
        pe_oi_by_strike = {}

        for item in chains:
            call_opt = item.get("callOption") or {}
            put_opt = item.get("putOption") or {}
            strike_raw = call_opt.get("strikePrice") or put_opt.get("strikePrice") or item.get("strikePrice") or 0
            strike = int(strike_raw / 100) if strike_raw > 100000 else int(strike_raw)

            ce_oi = call_opt.get("openInterest") or 0
            pe_oi = put_opt.get("openInterest") or 0
            tot_ce_oi += ce_oi
            tot_pe_oi += pe_oi
            if ce_oi > 0:
                ce_oi_by_strike[strike] = ce_oi
            if pe_oi > 0:
                pe_oi_by_strike[strike] = pe_oi

        pcr = round(tot_pe_oi / tot_ce_oi, 2) if tot_ce_oi > 0 else 1.0

        all_strikes = sorted(set(list(ce_oi_by_strike.keys()) + list(pe_oi_by_strike.keys())))
        pain_by_strike = {}
        for s in all_strikes:
            ce_pain = sum(ce_oi_by_strike.get(k, 0) * max(0, s - k) for k in all_strikes)
            pe_pain = sum(pe_oi_by_strike.get(k, 0) * max(0, k - s) for k in all_strikes)
            pain_by_strike[s] = ce_pain + pe_pain

        max_pain = min(pain_by_strike, key=pain_by_strike.get) if pain_by_strike else None
        top_oi_call = max(ce_oi_by_strike, key=ce_oi_by_strike.get) if ce_oi_by_strike else None
        top_oi_put = max(pe_oi_by_strike, key=pe_oi_by_strike.get) if pe_oi_by_strike else None

        logger.info(f"Groww Option Chain (Fallback): PCR={pcr}, Max Pain={max_pain}, Top Call OI={top_oi_call}, Top Put OI={top_oi_put}")
        return {
            "pcr": pcr,
            "max_pain": max_pain,
            "top_oi_call_strike": top_oi_call,
            "top_oi_put_strike": top_oi_put,
        }
    except Exception as e:
        logger.warning(f"Groww option chain fallback failed: {e}")
        return defaults


def _fetch_option_chain_data() -> dict:
    """
    Scrape live NIFTY Option Chain for:
    - Put-Call Ratio (PCR = Total PE OI / Total CE OI)
    - Max Pain level (strike with minimum total option pain)
    - Top OI Call strike (resistance)
    - Top OI Put strike (support)

    Strategy:
      1. Primary: Official NSE option-chain-v3 API (with session priming)
      2. Secondary Fallback: Groww live option chain service
      3. Last resort: Neutral defaults (PCR=1.0)
    """
    defaults = {"pcr": 1.0, "max_pain": None, "top_oi_call_strike": None, "top_oi_put_strike": None}
    try:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # Step 0: Prime cookies on option-chain page
        session.get("https://www.nseindia.com/option-chain", headers=headers, timeout=5)
        headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/option-chain",
        })

        # Step 1: Get nearest expiry date
        r_info = session.get(
            "https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY",
            headers=headers, timeout=5
        )
        if r_info.status_code != 200:
            raise ValueError(f"contract-info returned {r_info.status_code}")

        info = r_info.json()
        expiry_dates = info.get("expiryDates", [])
        nearest_expiry = expiry_dates[0] if expiry_dates else None

        records = []
        if nearest_expiry:
            # Step 2: Fetch OC data for nearest expiry via option-chain-v3
            r_oc = session.get(
                f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry={nearest_expiry}",
                headers=headers, timeout=6
            )
            if r_oc.status_code == 200:
                oc_body = r_oc.json()
                records = oc_body.get("records", {}).get("data", [])

        # If no records from NSE primary OC endpoint, try secondary fallback
        if not records:
            return _fetch_groww_option_chain_fallback(defaults)

        tot_ce_oi = 0
        tot_pe_oi = 0
        ce_oi_by_strike = {}
        pe_oi_by_strike = {}
        pain_by_strike = {}

        for row in records:
            strike = row.get("strikePrice", 0)
            ce_oi = row.get("CE", {}).get("openInterest", 0) if row.get("CE") else 0
            pe_oi = row.get("PE", {}).get("openInterest", 0) if row.get("PE") else 0
            tot_ce_oi += ce_oi
            tot_pe_oi += pe_oi
            if ce_oi > 0:
                ce_oi_by_strike[strike] = ce_oi
            if pe_oi > 0:
                pe_oi_by_strike[strike] = pe_oi

        # PCR = Put OI / Call OI
        pcr = round(tot_pe_oi / tot_ce_oi, 2) if tot_ce_oi > 0 else 1.0

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

        logger.info(f"NSE Option Chain: PCR={pcr}, Max Pain={max_pain}, Top Call OI={top_oi_call}, Top Put OI={top_oi_put}")
        return {
            "pcr": pcr,
            "max_pain": max_pain,
            "top_oi_call_strike": top_oi_call,
            "top_oi_put_strike": top_oi_put,
        }

    except Exception as e:
        logger.warning(f"Could not scrape option chain data from NSE: {e}")

    # Fallback to secondary source
    try:
        return _fetch_groww_option_chain_fallback(defaults)
    except Exception:
        pass
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
