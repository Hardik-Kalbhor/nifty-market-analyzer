"""
institutional/radar.py — Confluence matrix synthesis and main fetch_institutional_radar orchestrator.
"""

import time
import logging
import concurrent.futures
from datetime import datetime
from typing import Optional

from .constants import IST, TACTICAL_PROVIDERS
from .providers import _build_provider_call, _build_consensus
from .brokerage import _fetch_brokerage_calls

logger = logging.getLogger(__name__)

def _build_confluence_matrix(
    provider_calls: dict,
    consensus: dict,
    nifty_spot: Optional[float],
) -> dict:
    providers_ordered = []
    all_providers = TACTICAL_PROVIDERS + [{"key": "consensus", "name": "Street Consensus", "analyst": "ET / MC"}]
    for p in all_providers:
        key = p["key"]
        call = consensus if key == "consensus" else provider_calls.get(key, {})
        providers_ordered.append({"key": key, "name": p["name"], "analyst": p["analyst"], "call": call})

    def _parse_low(zone_str) -> Optional[int]:
        if not zone_str:
            return None
        try:
            return int(str(zone_str).replace(",", "").split("—")[0].strip())
        except (ValueError, IndexError):
            return None

    upside_pts = downside_pts = rr_ratio = None
    cr1 = _parse_low(consensus.get("r1"))
    cs1 = _parse_low(consensus.get("s1"))
    if nifty_spot and cr1 and cs1:
        upside_pts = round(cr1 - nifty_spot)
        downside_pts = round(nifty_spot - cs1)
        if downside_pts and downside_pts > 0:
            rr_ratio = round(upside_pts / downside_pts, 2)

    return {
        "providers": providers_ordered,
        "nifty_spot": nifty_spot,
        "upside_pts": upside_pts,
        "downside_pts": downside_pts,
        "rr_ratio": rr_ratio,
        "consensus_bias": consensus.get("next_day_bias", "RANGEBOUND"),
        "bull_pct": consensus.get("bull_pct", 0),
        "bear_pct": consensus.get("bear_pct", 0),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Fetch & Cache
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_institutional_radar(nifty_spot: Optional[float] = None) -> dict:
    """
    Full scrape: ET Markets article body per provider → level extraction,
    then brokerage radar via RSS. Returns structured dict.
    """
    logger.info("🏛️ Institutional Radar: Starting per-provider ET scrape...")

    provider_calls: dict = {}
    for p in TACTICAL_PROVIDERS:
        logger.info(f"  → Fetching {p['name']} ({p['analyst']})...")
        call = _build_provider_call(p, nifty_spot=nifty_spot)
        if call:
            provider_calls[p["key"]] = call
            logger.info(
                f"  ✅ {p['name']}: bias={call['next_day_bias']}, "
                f"R1={call.get('r1')}, S1={call.get('s1')}, "
                f"levels_raw={call.get('raw_levels_found', [])[:6]}"
            )
        else:
            logger.warning(f"  ⚠️  {p['name']}: No data found")
        time.sleep(0.3)  # polite delay between providers


    consensus = _build_consensus(provider_calls) if provider_calls else {}
    matrix = _build_confluence_matrix(provider_calls, consensus, nifty_spot)

    logger.info("🏛️ Institutional Radar: Fetching brokerage radar...")
    brokerage_calls = _fetch_brokerage_calls()

    now_ist = datetime.now(IST)
    result = {
        "fetched_at_ist": now_ist.strftime("%d %b %Y, %I:%M %p IST"),
        "fetched_ts": now_ist.timestamp(),
        "nifty_spot": nifty_spot,
        "consensus_bias": consensus.get("next_day_bias", "RANGEBOUND"),
        "bull_pct": consensus.get("bull_pct", 0),
        "bear_pct": consensus.get("bear_pct", 0),
        "provider_calls": provider_calls,
        "consensus": consensus,
        "confluence_matrix": matrix,
        "brokerage_calls": brokerage_calls,
        "providers_fetched": len(provider_calls),
        "brokerage_fetched": len(brokerage_calls),
    }

    logger.info(
        f"✅ Institutional Radar done: {len(provider_calls)}/4 providers, "
        f"{len(brokerage_calls)} brokerage calls. "
        f"Consensus: {consensus.get('next_day_bias')}"
    )
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Cache Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

