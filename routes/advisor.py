"""
routes/advisor.py — Exit advisor and OCR screenshot extraction routes.
"""

import os
import json
import logging
import traceback
from datetime import datetime
import requests
from flask import jsonify, request
import debate_engine
from scraper import scrape_all_news
from fii_dii_scraper import fetch_fii_dii_data
from market_signals_scraper import fetch_all_market_signals
from .app import app, get_history_dir

logger = logging.getLogger(__name__)

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
        import sys
        _srv = sys.modules.get("server")
        _fn_sig = getattr(_srv, "fetch_all_market_signals", fetch_all_market_signals) if _srv else fetch_all_market_signals
        _fn_fii = getattr(_srv, "fetch_fii_dii_data", fetch_fii_dii_data) if _srv else fetch_fii_dii_data
        _fn_news = getattr(_srv, "scrape_all_news", scrape_all_news) if _srv else scrape_all_news

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            f_signals = executor.submit(_fn_sig)
            f_fii_dii = executor.submit(_fn_fii)
            f_news = executor.submit(_fn_news)

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
            "contrarian_warning": (result.get("social_sentiment") or {}).get("contrarian_warning", ""),
            "cognigraph_regime": result.get("cognigraph_regime_precedent", ""),
            "latency_ms": elapsed_ms
        })

        return jsonify({"status": "success", "data": result})
    except Exception as e:
        logger.error(f"Exit Advisor error: {e}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/exit-advisor/poll", methods=["POST"])
def poll_exit_advisor():
    """
    Polls an active trade session by session_id.
    Fetches live signals, updates MFE/MAE excursions, and re-evaluates exit conviction.
    """
    import time
    start_t = time.time()
    try:
        payload = request.get_json(force=True) or {}
        session_id = payload.get("session_id")
        from exit.session_manager import get_trade_session_manager
        sm = get_trade_session_manager()
        sess = sm.get_session(session_id) if session_id else None
        if not sess:
            return jsonify({"status": "error", "message": f"Session {session_id} not found or inactive"}), 404

        pos = dict(sess.get("position", {}))
        for k, v in payload.items():
            if k != "session_id" and v is not None:
                pos[k] = v
        pos["session_id"] = session_id

        market_signals = fetch_all_market_signals()
        fii_dii_data = fetch_fii_dii_data()

        from exit_analyzer import evaluate_exit_with_ai
        result = evaluate_exit_with_ai(pos, market_signals, [], fii_dii_data)
        elapsed_ms = round((time.time() - start_t) * 1000, 1)
        result["latency_ms"] = elapsed_ms
        result["timestamp_ist"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return jsonify({"status": "success", "data": result})
    except Exception as e:
        logger.error(f"Poll Exit Advisor error: {e}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/exit-advisor/close", methods=["POST"])
def close_exit_advisor():
    """
    Manually mark an active trade session as CLOSED ("Exit" button).
    Computes realized P&L and stops active tracking.
    """
    try:
        payload = request.get_json(force=True) or {}
        session_id = payload.get("session_id")
        exit_spot = payload.get("exit_spot")
        exit_premium = payload.get("exit_premium")
        reason = payload.get("reason", "MANUAL_EXIT")

        if not session_id:
            return jsonify({"status": "error", "message": "session_id is required"}), 400

        from exit.session_manager import get_trade_session_manager
        sm = get_trade_session_manager()
        closed_sess = sm.close_session(session_id, exit_spot=exit_spot, exit_premium=exit_premium, reason=reason)
        if not closed_sess:
            return jsonify({"status": "error", "message": f"Session {session_id} not found"}), 404

        return jsonify({"status": "success", "message": "Trade marked as exited", "session": closed_sess})
    except Exception as e:
        logger.error(f"Close Exit Advisor error: {e}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/exit-advisor/status", methods=["GET"])
def exit_advisor_status():
    """Returns all active trade sessions being tracked."""
    try:
        from exit.session_manager import get_trade_session_manager
        sm = get_trade_session_manager()
        active = sm.get_active_sessions()
        return jsonify({
            "status": "success",
            "active_count": len(active),
            "active_sessions": active,
        })
    except Exception as e:
        logger.error(f"Exit Advisor status error: {e}\n{traceback.format_exc()}")
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



