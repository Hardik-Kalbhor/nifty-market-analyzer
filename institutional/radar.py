"""
institutional/radar.py — Confluence matrix synthesis and main fetch_institutional_radar orchestrator.
"""

import time
import logging
import concurrent.futures
from datetime import datetime
from typing import Optional

from .constants import IST, TACTICAL_PROVIDERS
from .providers import (
    _fetch_provider_raw,
    _build_provider_call_from_raw,
    _build_provider_call,
    _build_consensus,
)
from .agent import _run_institutional_synthesis_agent
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
    Unified Institutional Radar:
    1. Gathers latest articles across all tactical desks (ET Markets + Google News RSS + canonical bodies).
    2. Sends all desk notes in a single context to the Unified Institutional Synthesis Agent (Groq / Gemini)
       to extract desk-specific S/R calls and synthesize a high-conviction Street Consensus verdict.
    3. Falls back seamlessly to deterministic extraction if AI models are offline/unavailable.
    4. Fetches heavyweight brokerage equity calls.
    5. Returns structured confluence matrix and radar result.
    """
    logger.info("🏛️ Institutional Radar: Starting multi-desk report gathering...")

    raw_providers: dict = {}
    for p in TACTICAL_PROVIDERS:
        logger.info(f"  → Scraping {p['name']} ({p['analyst']})...")
        raw = _fetch_provider_raw(p)
        if raw:
            raw_providers[p["key"]] = raw
            logger.info(f"  ✅ {p['name']}: retrieved {len(raw['matching_texts'])} article source(s)")
        else:
            logger.warning(f"  ⚠️  {p['name']}: No data found")
        time.sleep(0.2)

    provider_calls: dict = {}
    consensus: dict = {}

    if raw_providers:
        logger.info("🏛️ Institutional Radar: Invoking Unified Institutional Synthesis Agent...")
        agent_output = _run_institutional_synthesis_agent(raw_providers, nifty_spot=nifty_spot)

        if agent_output and agent_output.get("provider_calls"):
            provider_calls = agent_output["provider_calls"]
            consensus = agent_output.get("consensus", {})

            # Attach provenance (headline, link, extraction engine)
            for key, call in provider_calls.items():
                raw = raw_providers.get(key, {})
                call["source_headline"] = raw.get("best_title", "")
                call["source_link"] = raw.get("best_link", "#")
                call.setdefault("raw_levels_found", call.get("raw_levels", []))
                call["extraction_engine"] = "Institutional Agent"

            # In case any desk with raw articles was omitted by the agent, fill via deterministic fallback
            for key, raw in raw_providers.items():
                if key not in provider_calls:
                    provider_calls[key] = _build_provider_call_from_raw(raw, nifty_spot=nifty_spot)

            consensus.setdefault("source_headline", "Aggregated across institutional desk reports")
            consensus.setdefault("source_link", "#")
            logger.info(
                f"✅ Unified Institutional Agent complete: "
                f"Consensus={consensus.get('next_day_bias')} "
                f"({consensus.get('bull_pct')}% Bull / {consensus.get('bear_pct')}% Bear)"
            )
        else:
            logger.warning("⚠️ Institutional Agent unavailable — falling back to deterministic extraction")
            for key, raw in raw_providers.items():
                provider_calls[key] = _build_provider_call_from_raw(raw, nifty_spot=nifty_spot)
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

