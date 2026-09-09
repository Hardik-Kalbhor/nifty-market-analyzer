"""
scheduler/pipeline.py — End-to-end automated analysis pipeline execution and artifact persistence.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from llm_analyzer import analyze_with_ai_agents
from intraday_analyzer import generate_intraday_prediction
from institutional_scraper import save_institutional_radar_cache, fetch_institutional_radar
from memory_log import get_memory_log, build_reflect_fn_from_env
import debate_engine

from .constants import TIMEZONE, HISTORY_DIR, _cleanup_old_history
from .inputs import gather_scheduled_inputs

logger = logging.getLogger("AutoScheduler")


def run_automated_analysis(run_name: str = "Scheduled Run") -> dict[str, Any] | None:
    """
    Executes the full automated analysis pipeline and saves timestamped report history.
    Strictly requires AI agent response — no rule-based fallback.

    Memory Loop integration:
    - Phase B+C: If this is the 08:30 Pre-Market run, resolve yesterday's pending prediction
                 (fetch actual Nifty open, generate LLM reflection).
    - Phase D:   Every run loads past lessons and injects them into the LLM prompt.
    - Phase A:   If this is the 15:15 Pre-Close BTST run, store today's prediction as pending.
    """
    now_ist = datetime.now(TIMEZONE)
    timestamp_str = now_ist.strftime("%Y-%m-%d_%H%M")
    logger.info(f"🚀 Running Automated Schedule [{run_name}] at {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}")

    memory = get_memory_log(HISTORY_DIR)
    is_btst_run = "15:15" in run_name or "Pre-Close" in run_name
    is_premarket_run = "08:30" in run_name or "Pre-Market" in run_name

    try:
        # ── Phase B+C: Resolve yesterday's pending prediction ────────────────────
        if is_premarket_run:
            logger.info("🧠 Memory Phase B+C: Resolving pending predictions from previous session...")
            try:
                reflect_fn = build_reflect_fn_from_env()
                resolved = memory.resolve_pending_entries(llm_reflect_fn=reflect_fn)
                if resolved:
                    for r in resolved:
                        logger.info(
                            f"  ✅ Resolved {r['date']} → {r['prediction']} | Actual: {r['actual_gap_pct']:+.2f}% | {r['outcome']}"
                        )
                else:
                    logger.info("  ℹ️ No pending entries needed resolution.")
            except Exception as mem_err:
                logger.warning(f"Memory Phase B+C failed (non-critical): {mem_err}")

        # ── Phase D: Load past lessons for context injection ─────────────────────
        past_context = ""
        try:
            past_context = memory.load_past_context(n=5)
            if past_context:
                logger.info(f"🧠 Memory Phase D: Loaded past lessons for LLM injection ({len(past_context.splitlines())} lines).")
        except Exception as ctx_err:
            logger.warning(f"Memory Phase D (load_past_context) failed (non-critical): {ctx_err}")

        # Phase 1 & 2: Concurrent Data Ingestion
        news_items, fii_dii_data, market_signals, heavyweights = gather_scheduled_inputs()

        # Phase 3: 6-Agent BTST Analysis & Arbiter (with Phase D past_context)
        ai_result = analyze_with_ai_agents(
            news_items, market_signals, fii_dii_data, heavyweights,
            past_context=past_context,
            run_debate=is_btst_run,
        )
        if not ai_result:
            raise RuntimeError("AI Agent returned no result. All providers failed or quota exceeded.")

        bull_len = len(ai_result.get("bullish_factors", []))
        bear_len = len(ai_result.get("bearish_factors", []))
        conf_val = ai_result.get("confidence", 50)

        result = {
            "prediction": ai_result.get("prediction", "FLAT"),
            "confidence": conf_val,
            "btst_bias": ai_result.get("btst_bias", "NO TRADE"),
            "news_sentiment": ai_result.get("news_sentiment", "MIXED"),
            "dimension_scores": ai_result.get("dimension_scores", {}),
            "weighted_confluence": ai_result.get("weighted_confluence", ""),
            "heavyweights": heavyweights,
            "bullish_factors": ai_result.get("bullish_factors", []),
            "bearish_factors": ai_result.get("bearish_factors", []),
            "key_drivers": (ai_result.get("bullish_factors", []) + ai_result.get("bearish_factors", []))[:4],
            "nifty_heavyweight_impact": ai_result.get("nifty_heavyweight_impact", ""),
            "ai_reasoning": ai_result.get("reasoning", ""),
            "final_summary": ai_result.get("reasoning", "Automated scheduled market intelligence run completed."),
            "ai_agent_provider": ai_result.get("ai_agent_provider"),
            "total_news_analyzed": len(news_items),
            "analysis_timestamp": now_ist.strftime("%d %b %Y, %I:%M %p IST"),
            "btst_structure":   ai_result.get("btst_structure"),
            "trade_instruction": ai_result.get("trade_instruction"),
            "debate_consensus":  ai_result.get("debate_consensus"),
            "debate":            ai_result.get("debate"),
            "scores": {
                "total_bullish": bull_len if bull_len > 0 else (7 if ai_result.get("prediction") == "GAP UP" else 2),
                "total_bearish": bear_len if bear_len > 0 else (7 if ai_result.get("prediction") == "GAP DOWN" else 2),
                "net_score": bull_len - bear_len,
                "confidence": conf_val,
            },
            "news_items": [
                {
                    "headline": it.get("headline", ""),
                    "source": it.get("source", "Financial News"),
                    "published_date": it.get("published_date", ""),
                    "category": it.get("category", "Markets"),
                    "sector": it.get("sector", "Markets"),
                    "url": it.get("url") or it.get("link") or "#",
                    "link": it.get("link") or it.get("url") or "#",
                    "impact": "NEUTRAL",
                    "sentiment": "NEUTRAL",
                    "importance": "MEDIUM",
                    "score": 0.0,
                    "bullish_score": 0,
                    "bearish_score": 0,
                    "confidence": conf_val
                }
                for it in news_items[:15]
            ]
        }

        # Phase 4: Intraday Prediction
        intraday = generate_intraday_prediction(
            news_sentiment=result.get("news_sentiment", "NEUTRAL"),
            gap_prediction=result.get("prediction", "FLAT"),
            event_risk="LOW",
            scores=result["scores"],
            bullish_factors=result.get("bullish_factors", []),
            bearish_factors=result.get("bearish_factors", []),
            sector_summary=[],
        )

        # Phase 4B: 3-Analyst Intraday Debate Committee
        try:
            groq_key = os.environ.get("GROQ_API_KEY", "")
            gemini_key = os.environ.get("GEMINI_API_KEY", "")
            intraday = debate_engine.run_intraday_debate(
                intraday_result=intraday,
                market_signals=market_signals,
                heavyweights=heavyweights,
                news_sentiment=result.get("news_sentiment", "NEUTRAL"),
                groq_key=groq_key,
                gemini_key=gemini_key,
            )
        except Exception as deb_err:
            logger.warning(f"Scheduled Intraday Debate Committee error: {deb_err} — proceeding with baseline.")

        result["intraday"] = intraday
        result["fii_dii"] = fii_dii_data
        result["market_signals_detail"] = market_signals
        result["market_signals"] = market_signals
        result["run_metadata"] = {
            "run_name": run_name,
            "executed_at_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        }

        # Phase 5: Refresh Institutional BTST Radar (scheduled cache)
        nifty_spot = market_signals.get("nifty_spot") if market_signals else None
        try:
            logger.info("🏛️ Phase 5: Refreshing Institutional BTST Radar cache...")
            inst_radar = fetch_institutional_radar(nifty_spot=nifty_spot)
            save_institutional_radar_cache(inst_radar, HISTORY_DIR)
            result["institutional_radar"] = inst_radar
            logger.info(f"✅ Institutional Radar cached: {inst_radar.get('consensus_bias')} consensus")
        except Exception as inst_err:
            logger.warning(f"Institutional Radar refresh failed (non-critical): {inst_err}")
            result["institutional_radar"] = {}

        # ── Phase A: Store prediction in memory (15:15 BTST run only) ────────────
        if is_btst_run:
            logger.info("🧠 Memory Phase A: Storing today's BTST prediction...")
            try:
                trade_date = now_ist.strftime("%Y-%m-%d")
                memory.store_prediction(
                    trade_date=trade_date,
                    prediction=result["prediction"],
                    btst_bias=result["btst_bias"],
                    confidence=result["confidence"],
                    reasoning=result.get("ai_reasoning", result.get("final_summary", "")),
                    dimension_scores=result.get("dimension_scores"),
                    fii_net=fii_dii_data.get("fii_net_crores") if isinstance(fii_dii_data, dict) else None,
                    gift_nifty_pct=market_signals.get("gift_nifty_change_pct"),
                    india_vix=market_signals.get("india_vix"),
                    ai_provider=result.get("ai_agent_provider"),
                    btst_structure=result.get("btst_structure"),
                    debate_consensus=result.get("debate_consensus"),
                    dte=market_signals.get("dte") if isinstance(market_signals, dict) else None,
                    fo_expiry_context=result.get("fo_expiry_context"),
                )
                result["memory_stored"] = True
                logger.info(f"  ✅ Phase A complete: [{trade_date}] {result['prediction']} / {result['btst_bias']} stored.")
            except Exception as mem_a_err:
                logger.warning(f"Memory Phase A failed (non-critical): {mem_a_err}")
                result["memory_stored"] = False

        # Save to history directory
        filepath = os.path.join(HISTORY_DIR, f"analysis_{timestamp_str}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        latest_filepath = os.path.join(HISTORY_DIR, "latest.json")
        with open(latest_filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        conf = result.get("confidence", 50)
        logger.info(f"✅ Automated Run [{run_name}] Completed! Prediction: {result['prediction']} ({conf}%). History saved to {filepath}")

        # Cleanup files older than 2 days
        _cleanup_old_history(max_days=2)

        return result

    except Exception as e:
        logger.error(f"❌ Automated Run [{run_name}] failed: {e}")
        return None
