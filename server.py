"""
server.py — Flask application for NIFTY Market Analysis Dashboard.
Serves the dashboard UI and provides the /api/analyze endpoint.
Includes Intraday predictions alongside BTST.
"""

import os
import json
import logging
import traceback
from flask import Flask, render_template, jsonify

from scraper import scrape_all_news
from analyzer import analyze_news
from intraday_analyzer import generate_intraday_prediction
from fii_dii_scraper import fetch_fii_dii_data
from market_signals_scraper import fetch_all_market_signals
from llm_analyzer import analyze_with_ai_agents, GeminiQuotaError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Start AutoScheduler at module load time so it works under both
# `python server.py` (development) and Gunicorn (production on Render).
try:
    from auto_scheduler import init_scheduler
    import os
    # Avoid double-starting in Gunicorn pre-fork model by using an env flag
    if not os.environ.get("SCHEDULER_STARTED"):
        os.environ["SCHEDULER_STARTED"] = "1"
        init_scheduler()
except Exception as _sched_err:
    import logging as _log
    _log.getLogger(__name__).warning(f"AutoScheduler could not start: {_sched_err}")


@app.after_request
def add_cors_headers(response):
    """Add CORS and cache headers for smooth cross-device / mobile browser support."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST", "GET"])
def analyze():
    """
    Trigger full news scraping + sentiment analysis + market signals
    + FII/DII flows + intraday prediction. Supports Gemini & Grok AI Agents.
    """
    try:
        logger.info("━━━ Starting market analysis ━━━")

        # Phase 1: Scrape news
        logger.info("Phase 1: Scraping news from all sources...")
        news_items = scrape_all_news()
        logger.info(f"Scraped {len(news_items)} news items.")

        # Phase 2: Scrape FII/DII flows & Market Microstructure Signals
        logger.info("Phase 2: Fetching FII/DII flows and market microstructure signals...")
        fii_dii_data = fetch_fii_dii_data()
        market_signals = fetch_all_market_signals()

        # Phase 3: AI Agent Analysis (No rule-based fallback)
        logger.info("Phase 3: Running AI Agent analysis (BTST)...")
        ai_result = analyze_with_ai_agents(news_items, market_signals)
        
        result = analyze_news(
            news_items=news_items,
            gift_nifty_change_pct=market_signals.get("gift_nifty_change_pct"),
            india_vix=market_signals.get("india_vix"),
            india_vix_change_pct=market_signals.get("india_vix_change_pct"),
            pcr=market_signals.get("pcr"),
            global_market_changes=market_signals.get("global_market_changes"),
        )
        
        # Directly override with AI Agent predictions & reasonings
        result["prediction"] = ai_result.get("prediction", result["prediction"])
        result["confidence"] = ai_result.get("confidence", result["confidence"])
        result["btst_bias"] = ai_result.get("btst_bias", result["btst_bias"])
        result["news_sentiment"] = ai_result.get("news_sentiment", result["news_sentiment"])
        result["ai_agent_provider"] = ai_result.get("ai_agent_provider", "AI Agent")
        result["final_summary"] = ai_result.get("reasoning", result["final_summary"])
        result["nifty_heavyweight_impact"] = ai_result.get("nifty_heavyweight_impact", "")
        if ai_result.get("bullish_factors"):
            result["bullish_factors"] = ai_result["bullish_factors"]
        if ai_result.get("bearish_factors"):
            result["bearish_factors"] = ai_result["bearish_factors"]

        logger.info(
            f"BTST Analysis ({result['ai_agent_provider']}) — Prediction: {result['prediction']}, "
            f"Confidence: {result['confidence']}%"
        )

        # Phase 4: Generate intraday prediction
        logger.info("Phase 4: Generating intraday prediction...")
        intraday = generate_intraday_prediction(
            news_sentiment=result["news_sentiment"],
            gap_prediction=result["prediction"],
            event_risk=result["event_risk"],
            scores=result["scores"],
            bullish_factors=result["bullish_factors"],
            bearish_factors=result["bearish_factors"],
            sector_summary=result["sector_summary"],
        )
        logger.info(
            f"Intraday — Bias: {intraday['intraday_bias']['bias']}, "
            f"Pattern: {intraday['intraday_pattern']['pattern']}, "
            f"Volatility: {intraday['volatility']['level']}"
        )

        # Merge FII/DII and intraday results into the output payload
        result["intraday"] = intraday
        result["fii_dii"] = fii_dii_data
        result["market_signals_detail"] = market_signals

        # Save manual run to history directory
        try:
            import pytz
            from datetime import datetime
            ist_now = datetime.now(pytz.timezone("Asia/Kolkata"))
            timestamp_str = ist_now.strftime("%Y-%m-%d_%H%M%S")
            result["run_metadata"] = {
                "run_name": "Manual User Run (Gemini AI)",
                "executed_at_ist": ist_now.strftime("%Y-%m-%d %H:%M:%S IST"),
            }
            history_dir = get_history_dir()
            filepath = os.path.join(history_dir, f"analysis_manual_{timestamp_str}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
        except Exception as save_err:
            logger.warning(f"Could not save manual run history: {save_err}")

        return jsonify({"status": "success", "data": result})

    except GeminiQuotaError as q_err:
        logger.warning(f"Gemini API Quota reached: {q_err}")
        return jsonify({
            "status": "error",
            "message": str(q_err),
            "retry_after": q_err.retry_after
        }), 429
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": f"Analysis failed: {str(e)}",
        }), 500


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "NIFTY Market Analyzer (BTST + Intraday)"})


@app.route("/api/trigger-schedule", methods=["POST", "GET"])
def trigger_schedule():
    """Manually trigger an automated scheduler run for testing."""
    try:
        from auto_scheduler import run_automated_analysis
        result = run_automated_analysis(run_name="Manual Test Trigger via API")
        if result:
            return jsonify({"status": "success", "message": "Automated schedule run executed successfully!", "data": result})
        return jsonify({"status": "error", "message": "Scheduler run returned no result"}), 500
    except Exception as e:
        logger.error(f"Manual trigger failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def get_history_dir():
    base_dir = os.path.join(os.path.dirname(__file__), "history")
    try:
        os.makedirs(base_dir, exist_ok=True)
        return base_dir
    except (OSError, PermissionError):
        tmp_dir = "/tmp/history"
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir


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
                    if f.endswith(".json") and f != "latest.json" and f not in files_map:
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
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    print("\n" + "━" * 60)
    print("  🚀 NIFTY Market Analysis Dashboard")
    print("  📊 BTST + Intraday Intelligence")
    print("  🌐 Open: http://localhost:5050")
    print("━" * 60 + "\n")

    app.run(debug=False, host="0.0.0.0", port=5050)
