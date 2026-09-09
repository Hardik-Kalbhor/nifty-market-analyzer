"""
market_signals/core.py — Concurrent orchestrator for all market microstructure signals.
"""

import logging
import concurrent.futures
from typing import Any

from .indices import _fetch_nse_indices
from .global_markets import _fetch_global_markets_and_gift
from .option_chain import _fetch_option_chain_data

logger = logging.getLogger(__name__)

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
