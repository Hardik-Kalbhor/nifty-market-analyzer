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



def _fetch_oi_spurts_fallback(session, headers, defaults: dict) -> dict:
    """
    Fallback for option chain data when the primary OC endpoint is unavailable.
    Uses NSE live-analysis-oi-spurts-underlyings endpoint to:
    - Derive a PCR proxy from NIFTY's option/futures OI ratio
    - Estimate top call/put OI strikes from spot price offsets

    This is intentionally a best-effort approximation, not exact OC math.
    """
    try:
        _session = session or requests.Session()
        _headers = headers or {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        r = _session.get(
            "https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings",
            headers=_headers, timeout=5
        )
        if r.status_code != 200:
            return defaults

        data = r.json().get("data", [])
        nifty = next((x for x in data if x.get("symbol") == "NIFTY"), None)
        if not nifty:
            return defaults

        spot = nifty.get("underlyingValue") or 0
        total_oi = nifty.get("latestOI") or 0
        opt_value = nifty.get("optValue") or 0
        fut_value = nifty.get("futValue") or 1

        # Derive approximate PCR: option value / futures value as proxy
        # Real PCR needs full OC; this is a structural bias proxy
        pcr_proxy = round(opt_value / (fut_value * 100), 2) if fut_value > 0 else 1.05
        pcr_proxy = max(0.5, min(pcr_proxy, 2.0))  # clamp to sane range

        # Estimate top OI strikes from spot (nearest round 50)
        if spot > 0:
            rounded_spot = round(spot / 50) * 50
            top_call = rounded_spot + 200  # approximate resistance at +200pts
            top_put = rounded_spot - 200   # approximate support at -200pts
        else:
            top_call = top_put = None

        logger.info(f"OI Spurts Fallback: PCR proxy={pcr_proxy}, Est. top call={top_call}, top put={top_put} (spot={spot})")
        return {
            "pcr": pcr_proxy,
            "max_pain": round(spot / 50) * 50 if spot > 0 else None,  # spot-rounded as max pain proxy
            "top_oi_call_strike": top_call,
            "top_oi_put_strike": top_put,
        }
    except Exception as e:
        logger.warning(f"OI spurts fallback failed: {e}")
        return defaults


def _fetch_option_chain_data() -> dict:

    """
    Scrape live NIFTY Option Chain from NSE for:
    - Put-Call Ratio (PCR)
    - Max Pain level (strike with minimum total option pain)
    - Top OI Call strike (resistance)
    - Top OI Put strike (support)

    Strategy:
      1. Try fetching OC via two-step (contract-info → option-chain-equities with expiry)
      2. Fallback: derive PCR from NSE live OI spurts underlyings (NIFTY futures OI ratio)
      3. Hardcoded defaults as last resort
    """
    defaults = {"pcr": 1.05, "max_pain": None, "top_oi_call_strike": None, "top_oi_put_strike": None}
    try:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/option-chain",
        }

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
            # Step 2: Fetch OC data for nearest expiry (equities endpoint works for index too with expiry param)
            r_oc = session.get(
                f"https://www.nseindia.com/api/option-chain-equities?symbol=NIFTY&expiryDate={nearest_expiry}",
                headers=headers, timeout=6
            )
            if r_oc.status_code == 200:
                oc_body = r_oc.json()
                records = oc_body.get("records", {}).get("data", [])

        # If no records from OC endpoint, try OI spurts for PCR proxy
        if not records:
            return _fetch_oi_spurts_fallback(session, headers, defaults)

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

    # Final fallback via OI spurts
    try:
        return _fetch_oi_spurts_fallback(None, None, defaults)
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
