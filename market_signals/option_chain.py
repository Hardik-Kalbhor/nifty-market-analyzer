"""
market_signals/option_chain.py — Option chain analytics, PCR, Max Pain, and OI walls scrapers.
"""

import logging
import requests
import time
from datetime import datetime
from typing import Any
from .constants import HEADERS

logger = logging.getLogger(__name__)

# Rolling snapshot cache: (strike, "CE"|"PE") -> list of (timestamp, oi)
_OI_SNAPSHOT_CACHE: dict[tuple[int, str], list[tuple[float, int]]] = {}
_OI_CACHE_WINDOW_SEC = 300  # 5 minutes target window
_OI_MAX_HISTORY_SEC = 900   # keep 15 minutes of history

def _compute_coi_velocity(strike: int, option_type: str, current_oi: int, now_ts: float | None = None) -> float:
    """
    Compute percentage change in OI over the ~5-minute window for a specific strike & option type.
    """
    if current_oi <= 0 or strike <= 0:
        return 0.0
    now = now_ts or time.time()
    key = (int(strike), str(option_type).upper())
    history = _OI_SNAPSHOT_CACHE.setdefault(key, [])

    # Prune old entries beyond 15 minutes
    cutoff = now - _OI_MAX_HISTORY_SEC
    _OI_SNAPSHOT_CACHE[key] = [item for item in history if item[0] >= cutoff]
    history = _OI_SNAPSHOT_CACHE[key]

    # Add current observation
    history.append((now, current_oi))

    # Find the best baseline entry: at least 20s old and closest to now - 300s
    baseline_entry = None
    target_ts = now - _OI_CACHE_WINDOW_SEC
    for ts, oi in history:
        if now - ts >= 20.0:
            if baseline_entry is None or abs(ts - target_ts) < abs(baseline_entry[0] - target_ts):
                baseline_entry = (ts, oi)

    if baseline_entry and baseline_entry[1] > 0:
        old_oi = baseline_entry[1]
        delta_pct = ((current_oi - old_oi) / old_oi) * 100.0
        return round(delta_pct, 1)

    return 0.0


def _build_option_chain_result(
    ce_oi_by_strike: dict[int, int],
    pe_oi_by_strike: dict[int, int],
    nifty_spot: float | None = None,
) -> dict[str, Any]:
    """Helper to compute PCR, Max Pain, Top OI walls, and ATM COI velocity."""
    tot_ce_oi = sum(ce_oi_by_strike.values())
    tot_pe_oi = sum(pe_oi_by_strike.values())
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

    # Determine ATM strike
    atm_strike = None
    if all_strikes:
        if nifty_spot and nifty_spot > 0:
            atm_strike = min(all_strikes, key=lambda s: abs(s - nifty_spot))
        else:
            atm_strike = all_strikes[len(all_strikes) // 2]

    atm_ce_oi = ce_oi_by_strike.get(atm_strike, 0) if atm_strike else 0
    atm_pe_oi = pe_oi_by_strike.get(atm_strike, 0) if atm_strike else 0

    coi_call = _compute_coi_velocity(atm_strike or 0, "CE", atm_ce_oi)
    coi_put = _compute_coi_velocity(atm_strike or 0, "PE", atm_pe_oi)
    snapshot_time = datetime.now().strftime("%H:%M:%S")

    return {
        "pcr": pcr,
        "max_pain": max_pain,
        "top_oi_call_strike": top_oi_call,
        "top_oi_put_strike": top_oi_put,
        "atm_strike": atm_strike,
        "coi_call_change_pct": coi_call,
        "coi_put_change_pct": coi_put,
        "coi_snapshot_time": snapshot_time,
    }


def _fetch_groww_option_chain_fallback(defaults: dict, nifty_spot: float | None = None) -> dict:
    """
    Secondary fallback for option chain and PCR data when NSE direct API is unavailable.
    Uses Groww's live derivative option chain API for NIFTY to compute exact:
    - PCR (Total PE OI / Total CE OI)
    - Max Pain strike
    - Top Call / Put OI strikes
    - ATM Strike COI Velocity
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

        ce_oi_by_strike = {}
        pe_oi_by_strike = {}

        for item in chains:
            call_opt = item.get("callOption") or {}
            put_opt = item.get("putOption") or {}
            strike_raw = call_opt.get("strikePrice") or put_opt.get("strikePrice") or item.get("strikePrice") or 0
            strike = int(strike_raw / 100) if strike_raw > 100000 else int(strike_raw)

            ce_oi = call_opt.get("openInterest") or 0
            pe_oi = put_opt.get("openInterest") or 0
            if ce_oi > 0:
                ce_oi_by_strike[strike] = ce_oi
            if pe_oi > 0:
                pe_oi_by_strike[strike] = pe_oi

        result = _build_option_chain_result(ce_oi_by_strike, pe_oi_by_strike, nifty_spot=nifty_spot)
        logger.info(f"Groww Option Chain (Fallback): PCR={result['pcr']}, Max Pain={result['max_pain']}, Top Call OI={result['top_oi_call_strike']}, Top Put OI={result['top_oi_put_strike']}")
        return result
    except Exception as e:
        logger.warning(f"Groww option chain fallback failed: {e}")
        return defaults


def _fetch_option_chain_data(nifty_spot: float | None = None) -> dict:
    """
    Scrape live NIFTY Option Chain for:
    - Put-Call Ratio (PCR = Total PE OI / Total CE OI)
    - Max Pain level (strike with minimum total option pain)
    - Top OI Call strike (resistance)
    - Top OI Put strike (support)
    - ATM Strike COI Velocity (5-min rolling change %)

    Strategy:
      1. Primary: Official NSE option-chain-v3 API (with session priming)
      2. Secondary Fallback: Groww live option chain service
      3. Last resort: Neutral defaults (PCR=1.0)
    """
    defaults = {
        "pcr": 1.0,
        "max_pain": None,
        "top_oi_call_strike": None,
        "top_oi_put_strike": None,
        "atm_strike": None,
        "coi_call_change_pct": 0.0,
        "coi_put_change_pct": 0.0,
        "coi_snapshot_time": datetime.now().strftime("%H:%M:%S"),
    }
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
                if not nifty_spot:
                    nifty_spot = oc_body.get("records", {}).get("underlyingValue")

        # If no records from NSE primary OC endpoint, try secondary fallback
        if not records:
            return _fetch_groww_option_chain_fallback(defaults, nifty_spot=nifty_spot)

        ce_oi_by_strike = {}
        pe_oi_by_strike = {}

        for row in records:
            strike = row.get("strikePrice", 0)
            ce_oi = row.get("CE", {}).get("openInterest", 0) if row.get("CE") else 0
            pe_oi = row.get("PE", {}).get("openInterest", 0) if row.get("PE") else 0
            if ce_oi > 0:
                ce_oi_by_strike[strike] = ce_oi
            if pe_oi > 0:
                pe_oi_by_strike[strike] = pe_oi

        result = _build_option_chain_result(ce_oi_by_strike, pe_oi_by_strike, nifty_spot=nifty_spot)
        logger.info(f"NSE Option Chain: PCR={result['pcr']}, Max Pain={result['max_pain']}, Top Call OI={result['top_oi_call_strike']}, Top Put OI={result['top_oi_put_strike']}")
        return result

    except Exception as e:
        logger.warning(f"Could not scrape option chain data from NSE: {e}")

    # Fallback to secondary source
    try:
        return _fetch_groww_option_chain_fallback(defaults, nifty_spot=nifty_spot)
    except Exception:
        pass
    return defaults


