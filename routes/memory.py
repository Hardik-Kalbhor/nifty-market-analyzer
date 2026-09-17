"""
routes/memory.py — Health, memory log, cognigraph, and institutional radar routes.
"""

import logging
from flask import jsonify, request
import yf_cache
from memory_log import get_memory_log
from institutional_scraper import get_cached_institutional_radar
from .app import app, get_history_dir

logger = logging.getLogger(__name__)

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "NIFTY Market Analyzer (BTST + Intraday)"})


@app.route("/api/memory", methods=["GET"])
def get_memory():
    """
    Return prediction memory log stats and past lessons.

    Response:
      {
        "status": "ok",
        "data": {
          "total_predictions": int,
          "resolved": int,
          "pending": int,
          "correct": int,
          "partial": int,
          "wrong": int,
          "accuracy_pct": float,
          "past_context": str,   -- the exact text injected into LLM prompts
          "entries": [...]       -- last 20 entries, newest first
        }
      }
    """
    try:
        memory = get_memory_log()
        stats = memory.get_stats()
        stats["past_context"] = memory.load_past_context(n=5)
        stats["yf_cache"] = yf_cache.cache_stats()
        return jsonify({"status": "ok", "data": stats})
    except Exception as e:
        logger.error(f"/api/memory failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/cognigraph", methods=["GET"])
def get_cognigraph_data():
    """
    Expose CogniGraph hierarchical cognitive graph metrics, active causal triples,
    and persona-conditioned memories for the frontend UI.
    Query params:
      ?persona=CONSERVATIVE|AGGRESSIVE|NEUTRAL|JUDGE
    """
    try:
        from cognigraph import get_cognigraph
        cg = get_cognigraph()
        stats = cg.get_stats()

        persona = request.args.get("persona")
        persona_context = ""
        if persona:
            persona_context = cg.get_agent_memory(persona, {})

        return jsonify({
            "status": "ok",
            "data": {
                **stats,
                "requested_persona": persona,
                "persona_context": persona_context,
            }
        })
    except Exception as e:
        logger.error(f"/api/cognigraph failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500




@app.route("/api/institutional-radar", methods=["GET"])
def get_institutional_radar():
    """
    Serve cached Institutional BTST & Next-Day Prediction Radar.
    Data is written by auto_scheduler.py on its 5 daily runs.
    This endpoint reads from disk — zero scraping, zero latency.
    If cache is stale (>14h), returns stale data with is_stale=True flag
    so the UI can surface a warning and offer a manual refresh.
    """
    import time as _t
    from institutional.constants import _CACHE_TTL_HOURS
    try:
        history_dir = get_history_dir()
        radar = get_cached_institutional_radar(history_dir, force_refresh=False)
        # Determine staleness for UI display
        fetched_ts = radar.get("fetched_ts", 0) if radar else 0
        age_hours = (_t.time() - fetched_ts) / 3600 if fetched_ts else 999
        is_stale = age_hours > _CACHE_TTL_HOURS
        return jsonify({
            "status": "ok",
            "data": radar,
            "is_stale": is_stale,
            "cache_age_hours": round(age_hours, 1),
        })
    except Exception as e:
        logger.error(f"/api/institutional-radar failed: {e}")
        return jsonify({"status": "ok", "data": {}, "is_stale": True, "cache_age_hours": 999})


@app.route("/api/institutional-radar/refresh", methods=["POST"])
def refresh_institutional_radar():
    """
    Force a live re-scrape of the Institutional BTST Radar.
    Called by the 'Refresh Now' button in the UI when cache is stale.
    Returns fresh data immediately (scrape takes ~5-10s).
    """
    import time as _t
    from institutional_scraper import fetch_institutional_radar, save_institutional_radar_cache
    try:
        history_dir = get_history_dir()
        # Optionally accept nifty_spot from caller
        body = request.get_json(silent=True) or {}
        nifty_spot = body.get("nifty_spot")
        logger.info(f"🔄 Manual radar refresh triggered (nifty_spot={nifty_spot})")
        data = fetch_institutional_radar(nifty_spot=nifty_spot)
        if data and data.get("provider_calls"):
            save_institutional_radar_cache(data, history_dir)
            logger.info(f"✅ Manual radar refresh success: {data.get('consensus_bias')}")
            return jsonify({"status": "ok", "data": data, "is_stale": False, "cache_age_hours": 0})
        else:
            logger.warning("Manual radar refresh: no provider data returned")
            return jsonify({"status": "partial", "data": data or {}, "is_stale": True, "cache_age_hours": 999})
    except Exception as e:
        logger.error(f"/api/institutional-radar/refresh failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500



