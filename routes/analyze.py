"""
routes/analyze.py — Core market analysis endpoint (/api/analyze).
"""

import os
import json
import logging
import traceback
from datetime import datetime
from flask import jsonify, request

from scraper import scrape_all_news
from analyzer import analyze_news
from intraday_analyzer import generate_intraday_prediction
from fii_dii_scraper import fetch_fii_dii_data
from market_signals_scraper import fetch_all_market_signals
from llm_analyzer import analyze_with_ai_agents, GeminiQuotaError
from memory_log import get_memory_log
import yf_cache
import debate_engine
from institutional_scraper import get_cached_institutional_radar

from .app import app, get_history_dir

logger = logging.getLogger(__name__)

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

            done, _ = concurrent.futures.wait([f_news, f_fii_dii, f_signals, f_hw], timeout=25.0)

        news_items = f_news.result() if f_news in done else []
        fii_dii_data = f_fii_dii.result() if f_fii_dii in done else None
        market_signals = f_signals.result() if f_signals in done else {}
        heavyweights = f_hw.result() if f_hw in done else {}
        logger.info(f"Ingested {len(news_items)} news items, FII/DII: {bool(fii_dii_data)}, Signals: {bool(market_signals)}, Heavyweights: {len(heavyweights)}")

        # Phase 3: 6-Agent BTST Analysis & Arbiter (with Phase D memory injection)
        logger.info("Phase 3: Running 6-Agent BTST Swarm analysis...")

        # Phase D: Load past lessons from memory log (non-blocking, best-effort)
        past_context = ""
        try:
            memory = get_memory_log()
            past_context = memory.load_past_context(n=5)
            if past_context:
                logger.info(f"Memory Phase D: Injecting {len(past_context.splitlines())} lines of past lessons into LLM prompt.")
        except Exception as mem_err:
            logger.debug(f"Memory Phase D skipped (non-critical): {mem_err}")

        # Check if debate mode is requested (default True)
        run_debate = request.args.get("debate", "true").lower() == "true"
        if run_debate:
            logger.info("Debate mode active — running 3-agent BTST risk committee after Stage 1.")

        ai_result = analyze_with_ai_agents(
            news_items, market_signals, fii_dii_data, heavyweights,
            past_context=past_context,
            run_debate=run_debate,
        )

        result = analyze_news(
            news_items=news_items,
            gift_nifty_change_pct=market_signals.get("gift_nifty_change_pct"),
            india_vix=market_signals.get("india_vix"),
            india_vix_change_pct=market_signals.get("india_vix_change_pct"),
            pcr=market_signals.get("pcr"),
            global_market_changes=market_signals.get("global_market_changes"),
            fii_net_cr=fii_dii_data.get("fii_net_crores") if isinstance(fii_dii_data, dict) else None,
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

        # Debate fields (present only when ?debate=true and btst_bias != NO TRADE)
        if ai_result.get("btst_structure"):
            result["btst_structure"]    = ai_result["btst_structure"]
            result["trade_instruction"] = ai_result.get("trade_instruction")
            result["debate_consensus"]  = ai_result.get("debate_consensus")
            result["debate"]            = ai_result.get("debate")

        logger.info(
            f"BTST Analysis ({result['ai_agent_provider']}) — Prediction: {result['prediction']}, "
            f"Bias: {result['btst_bias']}, Confidence: {result['confidence']}%"
            + (f", Structure: {result.get('btst_structure')}" if result.get('btst_structure') else "")
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

        # Phase 4B: 3-Analyst Intraday Debate Committee
        try:
            groq_key = os.environ.get("GROQ_API_KEY", "")
            gemini_key = os.environ.get("GEMINI_API_KEY", "")
            intraday = debate_engine.run_intraday_debate(
                intraday_result=intraday,
                market_signals=market_signals,
                heavyweights=heavyweights,
                news_sentiment=result.get("news_sentiment", "MIXED"),
                groq_key=groq_key,
                gemini_key=gemini_key,
            )
        except Exception as deb_err:
            logger.warning(f"Intraday Debate Committee error: {deb_err} — proceeding with baseline intraday.")

        # Merge FII/DII and intraday results into the output payload
        result["intraday"] = intraday
        result["fii_dii"] = fii_dii_data
        result["market_signals_detail"] = market_signals
        result["market_signals"] = market_signals
        result["heavyweights"] = heavyweights

        # Attach cached institutional radar, passing live spot for R:R computation
        try:
            live_spot = market_signals.get("nifty_spot") if market_signals else None
            result["institutional_radar"] = get_cached_institutional_radar(
                get_history_dir(), nifty_spot=live_spot, force_refresh=False
            )
        except Exception as inst_err:
            logger.warning(f"Failed to attach institutional radar: {inst_err}")
            result["institutional_radar"] = {}

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


