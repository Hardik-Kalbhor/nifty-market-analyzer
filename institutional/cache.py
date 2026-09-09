"""
institutional/cache.py — Disk caching and live spot patching for institutional radar data.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional

from .constants import IST, _CACHE_FILENAME, _CACHE_TTL_HOURS
from .radar import fetch_institutional_radar

logger = logging.getLogger(__name__)

def get_cache_path(history_dir: str) -> str:
    return os.path.join(history_dir, _CACHE_FILENAME)


def save_institutional_radar_cache(data: dict, history_dir: str) -> None:
    try:
        os.makedirs(history_dir, exist_ok=True)
        path = get_cache_path(history_dir)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Institutional Radar cached → {path}")
    except Exception as e:
        logger.warning(f"Cache save failed: {e}")


def load_institutional_radar_cache(history_dir: str) -> Optional[dict]:
    import time as _t
    try:
        path = get_cache_path(history_dir)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        age_hours = (_t.time() - data.get("fetched_ts", 0)) / 3600
        if age_hours > _CACHE_TTL_HOURS:
            logger.info(f"Institutional Radar cache stale ({age_hours:.1f}h). Needs refresh.")
            return None
        return data
    except Exception as e:
        logger.warning(f"Cache load failed: {e}")
        return None


def get_cached_institutional_radar(
    history_dir: str,
    nifty_spot: Optional[float] = None,
    force_refresh: bool = False,
) -> dict:
    """
    Primary entry point.
    Returns cached data if fresh; otherwise fetches, caches, and returns.
    When nifty_spot is provided, always patches the spot-derived fields
    (rr_ratio, upside_pts, downside_pts, nifty_spot) from the live price
    so the matrix R:R row is always current — even when article data is cached.
    Called by auto_scheduler.py (scheduled) and server.py (/api/analyze).
    """
    if not force_refresh:
        cached = load_institutional_radar_cache(history_dir)
        if cached:
            # Patch live spot into cached result if provided
            if nifty_spot:
                cached = _patch_spot_derived_fields(cached, nifty_spot)
            return cached

    data = fetch_institutional_radar(nifty_spot=nifty_spot)
    save_institutional_radar_cache(data, history_dir)
    return data


def _patch_spot_derived_fields(radar: dict, nifty_spot: float) -> dict:
    """
    Patch the nifty_spot-dependent fields into a cached radar result.
    This avoids a full re-scrape while keeping the matrix R:R row live.
    """
    try:
        import copy
        radar = copy.deepcopy(radar)
        radar["nifty_spot"] = nifty_spot

        # Re-derive confluence_matrix R:R fields from current spot
        matrix = radar.get("confluence_matrix", {})
        consensus = radar.get("consensus", {})

        def _parse_level(val) -> Optional[float]:
            if val is None:
                return None
            try:
                return float(str(val).replace(",", "").split("—")[0].strip())
            except Exception:
                return None

        cr1 = _parse_level(consensus.get("r1"))
        cs1 = _parse_level(consensus.get("s1"))
        upside_pts = downside_pts = rr_ratio = None
        if nifty_spot and cr1 and cs1:
            upside_pts = round(cr1 - nifty_spot)
            downside_pts = round(nifty_spot - cs1)
            if downside_pts and downside_pts > 0:
                rr_ratio = round(upside_pts / downside_pts, 2)

        matrix["nifty_spot"] = nifty_spot
        matrix["upside_pts"] = upside_pts
        matrix["downside_pts"] = downside_pts
        matrix["rr_ratio"] = rr_ratio
        radar["confluence_matrix"] = matrix
    except Exception:
        pass
    return radar

