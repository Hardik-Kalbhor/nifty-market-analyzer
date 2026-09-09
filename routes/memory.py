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
    """
    try:
        history_dir = get_history_dir()
        radar = get_cached_institutional_radar(history_dir, force_refresh=False)
        return jsonify({"status": "ok", "data": radar})
    except Exception as e:
        logger.error(f"/api/institutional-radar failed: {e}")
        return jsonify({"status": "ok", "data": {}})


