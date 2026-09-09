"""
routes/history.py — Historical analysis lookup and normalization routes.
"""

import os
import json
import logging
from datetime import datetime
from flask import jsonify
from .app import app, get_history_dir

logger = logging.getLogger(__name__)

@app.route("/api/history", methods=["GET"])
def get_history():
    """List all saved historical analysis runs split into Scheduled vs Manual columns."""

    try:
        history_dirs = [get_history_dir()]
        if "/tmp/history" not in history_dirs and os.path.exists("/tmp/history"):
            history_dirs.append("/tmp/history")

        files_map = {}
        for h_dir in history_dirs:
            if os.path.exists(h_dir):
                for f in os.listdir(h_dir):
                    if f.startswith("analysis_") and f.endswith(".json") and f != "latest.json" and f not in files_map:
                        files_map[f] = os.path.join(h_dir, f)

        sorted_filenames = sorted(files_map.keys(), reverse=True)
        scheduled_runs = []
        manual_runs = []

        for filename in sorted_filenames:
            filepath = files_map[filename]
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = data.get("run_metadata", {})
                run_name = meta.get("run_name", "Manual Run")

                # Check if scheduled run
                is_scheduled = any(k in run_name for k in [
                    "08:30", "09:45", "13:30", "15:15", "17:30",
                    "Pre-Market", "Post-Open", "European", "Pre-Close", "Post-Market"
                ]) and not ("Manual" in run_name or "manual" in filename)

                run_obj = {
                    "filename": filename,
                    "prediction": data.get("prediction", "N/A"),
                    "confidence": data.get("confidence", data.get("scores", {}).get("confidence", 50)),
                    "run_name": run_name,
                    "executed_at_ist": meta.get("executed_at_ist", data.get("scraped_at", "")),
                    "fii_net": data.get("fii_dii", {}).get("fii_net_crores"),
                    "dii_net": data.get("fii_dii", {}).get("dii_net_crores"),
                    "category": "SCHEDULED" if is_scheduled else "MANUAL"
                }

                if is_scheduled:
                    scheduled_runs.append(run_obj)
                else:
                    manual_runs.append(run_obj)

            except Exception as read_err:
                logger.warning(f"Could not read history file {filename}: {read_err}")

        return jsonify({
            "status": "success",
            "scheduled": scheduled_runs,
            "manual": manual_runs,
            "total_count": len(files_map)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _normalize_history_data(data: dict) -> dict:
    """Ensure history snapshots always have the full schema expected by the frontend."""
    if not isinstance(data, dict):
        return data

    bull_len = len(data.get("bullish_factors", []))
    bear_len = len(data.get("bearish_factors", []))
    conf = data.get("confidence", 50)

    # Ensure scores dict with net_score
    if "scores" not in data or not isinstance(data.get("scores"), dict):
        data["scores"] = {
            "total_bullish": bull_len if bull_len > 0 else (7 if data.get("prediction") == "GAP UP" else 2),
            "total_bearish": bear_len if bear_len > 0 else (7 if data.get("prediction") == "GAP DOWN" else 2),
            "net_score": bull_len - bear_len,
            "confidence": conf,
        }
    else:
        if "net_score" not in data["scores"]:
            b = data["scores"].get("total_bullish", 0)
            br = data["scores"].get("total_bearish", 0)
            data["scores"]["net_score"] = b - br

    # Ensure other root fields exist
    if "final_summary" not in data:
        data["final_summary"] = data.get("ai_reasoning") or "Analysis snapshot loaded."
    if "total_news_analyzed" not in data:
        data["total_news_analyzed"] = len(data.get("news_items", [])) or 70
    if "analysis_timestamp" not in data:
        data["analysis_timestamp"] = data.get("run_metadata", {}).get("executed_at_ist") or "Historical Snapshot"
    if "key_drivers" not in data:
        data["key_drivers"] = (data.get("bullish_factors", []) + data.get("bearish_factors", []))[:4]
    if "event_risk" not in data:
        data["event_risk"] = "LOW"
    if "market_signals" not in data:
        data["market_signals"] = data.get("market_signals_detail") or {}
    if "market_signals_detail" not in data:
        data["market_signals_detail"] = data.get("market_signals") or {}
    if "fii_dii" not in data:
        data["fii_dii"] = {}

    # Normalize news items to have all required frontend fields
    raw_news = data.get("all_news") or data.get("major_news") or data.get("news_items") or []
    normalized_news = []
    for item in raw_news:
        if isinstance(item, dict):
            imp = item.get("impact") or item.get("sentiment") or "NEUTRAL"
            normalized_news.append({
                "headline": item.get("headline", ""),
                "source": item.get("source", "Financial News"),
                "published_date": item.get("published_date", ""),
                "category": item.get("category", "Markets"),
                "sector": item.get("sector", "Markets"),
                "link": item.get("link") or item.get("url") or "#",
                "url": item.get("url") or item.get("link") or "#",
                "impact": imp,
                "sentiment": imp,
                "importance": item.get("importance", "MEDIUM"),
                "score": item.get("score", 0.0),
                "bullish_score": item.get("bullish_score", 0),
                "bearish_score": item.get("bearish_score", 0),
                "strength_badge": item.get("strength_badge", "")
            })

    data["all_news"] = normalized_news
    data["major_news"] = normalized_news
    data["news_items"] = normalized_news

    if "sector_summary" not in data or not isinstance(data.get("sector_summary"), list):
        data["sector_summary"] = []

    if "institutional_radar" not in data:
        data["institutional_radar"] = {}

    return data



@app.route("/api/history/<filename>", methods=["GET"])
def get_history_detail(filename):
    """Retrieve full data JSON for a specific historical run."""
    try:
        safe_filename = os.path.basename(filename)
        history_dirs = [get_history_dir(), "/tmp/history"]
        filepath = None
        for h_dir in history_dirs:
            candidate = os.path.join(h_dir, safe_filename)
            if os.path.exists(candidate):
                filepath = candidate
                break

        if not filepath:
            return jsonify({"status": "error", "message": "History file not found"}), 404
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        data = _normalize_history_data(data)
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


