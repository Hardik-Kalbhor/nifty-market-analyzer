"""
market_signals/core.py — Concurrent orchestrator for all market microstructure signals.
"""

import logging
import concurrent.futures
from typing import Any

from .indices import _fetch_nse_indices
from .global_markets import _fetch_global_markets_and_gift
from .option_chain import _fetch_option_chain_data
from yf_cache import fetch_1min_bars

logger = logging.getLogger(__name__)


def compute_atr_from_bars(bars: list[dict], period: int = 14) -> float:
    """Compute 14-period True Range ATR from 1-min bars with safe default 18.0."""
    if not bars or len(bars) < 2:
        return 18.0
    true_ranges = []
    for i in range(1, len(bars)):
        h = bars[i].get("high") or bars[i].get("close")
        l = bars[i].get("low") or bars[i].get("close")
        pc = bars[i-1].get("close")
        if h is not None and l is not None and pc is not None:
            tr = max(h - l, abs(h - pc), abs(l - pc))
            true_ranges.append(tr)
    if not true_ranges:
        return 18.0
    effective = min(period, len(true_ranges))
    return round(float(sum(true_ranges[-effective:]) / effective), 2)


def compute_cvd_from_bars(bars: list[dict], lookback: int = 5) -> str:
    """Compute CVD (Cumulative Volume Delta) direction proxy from recent 1-min bars."""
    if not bars or len(bars) < 2:
        return "NEUTRAL"
    recent = bars[-lookback:]
    buy_vol = 0
    sell_vol = 0
    for b in recent:
        o = b.get("open") or 0.0
        c = b.get("close") or 0.0
        v = b.get("volume") or 0
        if c > o:
            buy_vol += v
        elif c < o:
            sell_vol += v
    if buy_vol > sell_vol * 1.15:
        return "POSITIVE"
    elif sell_vol > buy_vol * 1.15:
        return "NEGATIVE"
    return "NEUTRAL"


def compute_open_1min_low_from_bars(bars: list[dict], fallback_spot: float = 0.0) -> float:
    """Find the opening 1-minute low of the day, fallback to spot - 25pts."""
    if bars and len(bars) > 0:
        first_bar = bars[0]
        low = first_bar.get("low") or first_bar.get("open")
        if low and low > 0:
            return round(float(low), 1)
    return round(fallback_spot - 25.0 if fallback_spot > 0 else 0.0, 1)


def fetch_all_market_signals() -> dict[str, Any]:
    """
    Master function to aggregate all market microstructure signals
    required by analyzer.py and exit advisor.
    """
    logger.info("Fetching all market microstructure signals...")
    nse_data = _fetch_nse_indices()
    nifty_spot = nse_data.get("nifty_spot") or 0.0

    global_data = _fetch_global_markets_and_gift()
    oc_data = _fetch_option_chain_data(nifty_spot=nifty_spot if nifty_spot > 0 else None)

    # 1-minute bars for ATR, CVD proxy, and opening low
    bars_1m = []
    try:
        bars_1m = fetch_1min_bars("^NSEI", timeout=3.5)
    except Exception as e:
        logger.debug(f"Failed to fetch 1m bars for ATR/CVD: {e}")

    atr_val = compute_atr_from_bars(bars_1m, period=14)
    cvd_dir = compute_cvd_from_bars(bars_1m, lookback=5)
    open_low = compute_open_1min_low_from_bars(bars_1m, fallback_spot=nifty_spot)

    # GIFT Nifty indicative price
    gift_pct = global_data.get("gift_nifty_change_pct", 0.0) or 0.0
    gift_indicative = round(nifty_spot * (1 + gift_pct / 100), 1) if nifty_spot > 0 else 0.0

    return {
        "gift_nifty_change_pct": gift_pct,
        "gift_nifty_indicative": gift_indicative,
        "india_vix": nse_data.get("india_vix"),
        "india_vix_change_pct": nse_data.get("india_vix_change_pct"),
        "nifty_spot": nifty_spot,
        "nifty_pct": nse_data.get("nifty_pct"),
        "pcr": oc_data.get("pcr", 1.05),
        "max_pain": oc_data.get("max_pain"),
        "top_oi_call_strike": oc_data.get("top_oi_call_strike"),
        "top_oi_put_strike": oc_data.get("top_oi_put_strike"),
        "atm_strike": oc_data.get("atm_strike"),
        "coi_call_change_pct": oc_data.get("coi_call_change_pct", 0.0),
        "coi_put_change_pct": oc_data.get("coi_put_change_pct", 0.0),
        "coi_snapshot_time": oc_data.get("coi_snapshot_time", ""),
        "atr_14_1min": atr_val,
        "cvd_divergence": cvd_dir,
        "open_1min_low": open_low,
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
