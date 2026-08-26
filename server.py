"""
server.py — Flask application for NIFTY Market Analysis Dashboard.
Serves the dashboard UI and provides the /api/analyze endpoint.
Includes Intraday predictions alongside BTST.
"""

import os
import json
import logging
import traceback
from datetime import datetime
from flask import Flask, render_template, jsonify, request

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

        # Phase 1 & 2: Concurrent Data Ingestion (News, FII/DII, Market Signals, Heavyweights)
        import concurrent.futures
        from exit_fast_path import fetch_heavyweight_stocks

        logger.info("Phase 1 & 2: Concurrently fetching news, FII/DII, market signals, and heavyweights...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            f_news = executor.submit(scrape_all_news)
            f_fii_dii = executor.submit(fetch_fii_dii_data)
            f_signals = executor.submit(fetch_all_market_signals)
            f_hw = executor.submit(fetch_heavyweight_stocks)

            done, _ = concurrent.futures.wait([f_news, f_fii_dii, f_signals, f_hw], timeout=9.0)

        news_items = f_news.result() if f_news in done else []
        fii_dii_data = f_fii_dii.result() if f_fii_dii in done else None
        market_signals = f_signals.result() if f_signals in done else {}
        heavyweights = f_hw.result() if f_hw in done else {}
        logger.info(f"Ingested {len(news_items)} news items, FII/DII: {bool(fii_dii_data)}, Signals: {bool(market_signals)}, Heavyweights: {len(heavyweights)}")

        # Phase 3: 6-Agent BTST Analysis & Arbiter
        logger.info("Phase 3: Running 6-Agent BTST Swarm analysis...")
        ai_result = analyze_with_ai_agents(news_items, market_signals, fii_dii_data, heavyweights)

        result = analyze_news(
            news_items=news_items,
            gift_nifty_change_pct=market_signals.get("gift_nifty_change_pct"),
            india_vix=market_signals.get("india_vix"),
            india_vix_change_pct=market_signals.get("india_vix_change_pct"),
            pcr=market_signals.get("pcr"),
            global_market_changes=market_signals.get("global_market_changes"),
        )

        # Directly override with 6-Agent Swarm predictions & reasonings
        result["prediction"] = ai_result.get("prediction", result["prediction"])
        result["confidence"] = ai_result.get("confidence", result["confidence"])
        result["btst_bias"] = ai_result.get("btst_bias", result["btst_bias"])
        result["news_sentiment"] = ai_result.get("news_sentiment", result["news_sentiment"])
        result["ai_agent_provider"] = ai_result.get("ai_agent_provider", "AI Agent")
        result["final_summary"] = ai_result.get("reasoning", result["final_summary"])
        result["nifty_heavyweight_impact"] = ai_result.get("nifty_heavyweight_impact", "")
        result["dimension_scores"] = ai_result.get("dimension_scores", {})
        result["weighted_confluence"] = ai_result.get("weighted_confluence", "")
        result["heavyweights"] = heavyweights
        if ai_result.get("bullish_factors"):
            result["bullish_factors"] = ai_result["bullish_factors"]
        if ai_result.get("bearish_factors"):
            result["bearish_factors"] = ai_result["bearish_factors"]

        logger.info(
            f"BTST Analysis ({result['ai_agent_provider']}) — Prediction: {result['prediction']}, "
            f"Bias: {result['btst_bias']}, Confidence: {result['confidence']}%"
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


def _log_exit_audit(entry: dict):
    """Append evaluation record to exit_evaluations.jsonl."""
    try:
        hdir = get_history_dir()
        log_file = os.path.join(hdir, "exit_evaluations.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"Audit log error: {e}")


@app.route("/api/exit-advisor", methods=["POST"])
def exit_advisor():
    """
    Evaluates live open positions (BTST / Intraday) with:
    - Fast-Path (0-10ms) — 7 deterministic safety rules
    - Multi-Perspective 6-Agent AI (single enriched Groq call) (≤1.5s)
    - Weighted conflict resolution + mathematical fallback
    """
    import time
    import concurrent.futures
    start_t = time.time()
    try:
        payload = request.get_json(force=True) or {}

        # 1. Fetch market signals + FII/DII data concurrently (no added latency)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            f_signals = executor.submit(fetch_all_market_signals)
            f_fii_dii = executor.submit(fetch_fii_dii_data)
            f_news = executor.submit(scrape_all_news)

            done, _ = concurrent.futures.wait(
                [f_signals, f_fii_dii, f_news], timeout=8.0
            )

        market_signals = f_signals.result() if f_signals in done else {}
        fii_dii_data = f_fii_dii.result() if f_fii_dii in done else None
        try:
            news_items = f_news.result() if f_news in done else []
        except Exception as e:
            logger.warning(f"News scrape failed for exit advisor: {e}")
            news_items = []

        # 2. Run evaluation (Fast-Path → Multi-Perspective AI → Deterministic Fallback)
        from exit_analyzer import evaluate_exit_with_ai
        result = evaluate_exit_with_ai(payload, market_signals, news_items, fii_dii_data)

        elapsed_ms = round((time.time() - start_t) * 1000, 1)
        result["latency_ms"] = elapsed_ms
        result["timestamp_ist"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 3. Audit Log
        _log_exit_audit({
            "timestamp": result["timestamp_ist"],
            "position": payload,
            "live_spot": market_signals.get("nifty_spot"),
            "verdict": result.get("verdict"),
            "engine": result.get("engine"),
            "latency_ms": elapsed_ms
        })

        return jsonify({"status": "success", "data": result})
    except Exception as e:
        logger.error(f"Exit Advisor error: {e}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/extract-screenshot", methods=["POST"])
def extract_screenshot():
    """
    Extracts open options/futures position parameters from an uploaded broker screenshot
    (Dhan, Zerodha Kite, Groww, Angel One, Upstox).
    Accepts multipart/form-data ('image' file) or JSON ({'image_b64': '...'}).
    """
    try:
        import base64
        from ocr_extractor import extract_position_from_image

        image_bytes = None
        if "image" in request.files:
            image_bytes = request.files["image"].read()
        elif request.is_json:
            data = request.get_json() or {}
            b64_str = data.get("image_b64", "")
            if "," in b64_str:
                b64_str = b64_str.split(",", 1)[1]
            if b64_str:
                image_bytes = base64.b64decode(b64_str)

        if not image_bytes:
            return jsonify({"status": "error", "message": "No image provided. Please upload or paste a screenshot."}), 400

        result = extract_position_from_image(image_bytes)
        if result.get("status") == "success":
            return jsonify(result)
        else:
            return jsonify(result), 422

    except Exception as e:
        logger.error(f"Screenshot extraction error: {e}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/extract-ocr-text", methods=["POST"])
def extract_ocr_text():
    """
    Parses raw OCR text extracted client-side (e.g. via Tesseract.js) into structured position JSON.
    """
    try:
        from ocr_extractor import parse_ocr_raw_text
        data = request.get_json(force=True) or {}
        raw_text = data.get("raw_text", "").strip()
        has_red = bool(data.get("has_red_badge", False))
        has_green = bool(data.get("has_green_badge", False))
        if not raw_text:
            return jsonify({"status": "error", "message": "Empty text provided."}), 400

        result = parse_ocr_raw_text(raw_text, has_red_badge=has_red, has_green_badge=has_green)
        if result.get("status") == "success":
            return jsonify(result)
        else:
            return jsonify(result), 422
    except Exception as e:
        logger.error(f"OCR text extraction error: {e}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500



if __name__ == "__main__":
    print("\n" + "━" * 60)
    print("  🚀 NIFTY Market Analysis Dashboard")
    print("  📊 BTST + Intraday Intelligence")
    print("  🌐 Open: http://localhost:5050")
    print("━" * 60 + "\n")

    app.run(debug=False, host="0.0.0.0", port=5050)
