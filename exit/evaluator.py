from __future__ import annotations
import os
import json
import logging
import requests
from typing import Any
import debate_engine

from exit_fast_path import (
    evaluate_fast_path,
    evaluate_exit_fast_path,
    fetch_heavyweight_stocks,
    generate_rule_based_fallback,
    _safe_float,
)
from .constants import EXIT_ADVISOR_SYSTEM_PROMPT, EXIT_SYSTEM_PROMPT
from .validation import _validate_and_ground_output
from .context import build_exit_prompt_context
from .scale_out import generate_tiered_scale_out_plan
from .resolution import _resolve_dimension_conflict
from .enricher import enrich_position
from .eci_scorer import compute_eci_score
from .session_manager import get_trade_session_manager

logger = logging.getLogger(__name__)


def _finalize_exit_result(
    result: dict[str, Any],
    position: dict[str, Any],
    live_signals: dict[str, Any],
    session_mgr: Any = None,
) -> dict[str, Any]:
    """Attach numeric ECI score, breakdown, urgency, and quantitative tracking attributes."""
    final_res = dict(result)
    eci_score, eci_breakdown, urgency = compute_eci_score(final_res, position, live_signals)
    final_res["eci_score"] = eci_score
    final_res["eci_breakdown"] = eci_breakdown
    final_res["urgency"] = urgency

    # Quantitative telemetry fields
    final_res["session_id"] = position.get("session_id")
    final_res["mfe_pct"] = position.get("mfe_pct", 0.0)
    final_res["mae_pct"] = position.get("mae_pct", 0.0)
    final_res["mfe_r"] = position.get("mfe_r", 0.0)
    final_res["current_r"] = position.get("current_r", 0.0)
    final_res["mfe_locked"] = position.get("mfe_locked", False)
    final_res["elapsed_minutes"] = position.get("elapsed_minutes", 0.0)
    final_res["atr_trail_level"] = position.get("atr_trail_level")
    final_res["coi_alert"] = final_res.get("coi_alert") or position.get("coi_alert") or live_signals.get("coi_alert")
    final_res["coi_call_change_pct"] = live_signals.get("coi_call_change_pct", 0.0)
    final_res["coi_put_change_pct"] = live_signals.get("coi_put_change_pct", 0.0)
    final_res["cvd_divergence"] = live_signals.get("cvd_divergence", "NEUTRAL")

    # Stateful session poll update
    if session_mgr and final_res.get("session_id"):
        live_spot = float(live_signals.get("nifty_spot") or position.get("entry_spot") or 0.0)
        session_mgr.record_poll(
            final_res["session_id"],
            live_spot,
            final_res.get("verdict", "HOLD"),
            eci_score=eci_score,
        )

    return final_res


def evaluate_exit_with_ai(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    news_items: list[dict],
    fii_dii_data: dict[str, Any] | None = None,
    social_sentiment: dict[str, Any] | None = None,
    cognigraph_context: str | None = None,
) -> dict[str, Any]:
    """
    Main evaluation pipeline:
    0. Stage 0: Quantitative Position & Session Enrichment (MFE/MAE/ATR/Elapsed)
    1. Stage 1: Deterministic Fast-Path (0-10ms) — 14 safety rules (including Contrarian Traps)
    2. Stage 2: Heavyweight & Context Aggregation (≤350ms)
    3. Stage 3: Enriched multi-perspective AI call (Groq → Gemini fallback) (≤1200ms)
    4. Stage 4: Multi-Persona Exit Debate Committee & Weighted Conflict Resolution
    5. Stage 5: Rule-Based Fallback Engine
    6. Stage 6: Exit Conviction Index (ECI 0-100) Quantitative Scoring
    """
    session_mgr = get_trade_session_manager()

    # --- STAGE 0: Enrich Position with MFE/MAE/ATR & Session State ---
    position = enrich_position(position, live_signals, session_mgr=session_mgr)

    # Ingest Social Sentiment and Contrarian Signals
    if social_sentiment is None:
        try:
            from analyzer import _compute_social_sentiment
            fii_val = fii_dii_data.get("fii_net_crores") if fii_dii_data else None
            social_sentiment = _compute_social_sentiment(news_items, fii_net_cr=fii_val)
        except Exception:
            social_sentiment = {}

    contrarian_warning = social_sentiment.get("contrarian_warning", "")
    live_signals["social_sentiment"] = social_sentiment
    if contrarian_warning:
        live_signals["contrarian_warning"] = contrarian_warning

    # Ingest CogniGraph Regime Memory (compute before fast path for universal context)
    cognigraph_summary = ""
    try:
        from cognigraph import get_cognigraph
        cg = get_cognigraph()
        regime = cg.classify_regime(live_signals)
        traps = cg.get_top_traps(regime)
        cognigraph_summary = f"Regime: {regime}"
        if traps:
            cognigraph_summary += f" | Known Trap: {traps[0].get('setup')} -> {traps[0].get('cause')}"
    except Exception as e:
        cognigraph_summary = "Regime: Normal"

    # --- STAGE 1: Fast-Path Deterministic Check ---
    fast_result = evaluate_fast_path(position, live_signals)
    if fast_result:
        fast_result["social_sentiment"] = social_sentiment
        fast_result["cognigraph_regime_precedent"] = cognigraph_summary or "Regime: Fast-Path Safety Intercept"
        if "dimension_scores" not in fast_result:
            fast_result["dimension_scores"] = {
                "greeks_decay": {"verdict": fast_result.get("verdict", "EXIT"), "note": "Fast-path safety rule triggered"},
                "oi_pcr": {"verdict": fast_result.get("verdict", "EXIT"), "note": "Hard circuit breaker triggered"},
                "heavyweights": {"verdict": fast_result.get("verdict", "EXIT"), "note": "Pre-empts heavyweight evaluation"},
                "price_action": {"verdict": fast_result.get("verdict", "EXIT"), "note": fast_result.get("reasoning", "")},
                "vix_regime": {"verdict": fast_result.get("verdict", "EXIT"), "note": "Risk control"},
                "macro_global": {"verdict": fast_result.get("verdict", "EXIT"), "note": "Deterministic safety rule"},
                "social_contrarian": {"verdict": fast_result.get("verdict", "EXIT"), "note": fast_result.get("contrarian_alert", "Neutral")},
                "mfe_mae": {"verdict": fast_result.get("verdict", "EXIT"), "note": f"MFE R: {position.get('mfe_r', 0)}R"},
                "order_flow": {"verdict": fast_result.get("verdict", "EXIT"), "note": fast_result.get("coi_alert", "Microstructure checked")},
            }
        logger.info(f"⚡ Fast-Path Triggered: {fast_result['verdict']}")
        return _finalize_exit_result(fast_result, position, live_signals, session_mgr=session_mgr)

    # --- STAGE 2: Heavyweight Constituent Scrape ---
    heavyweights = fetch_heavyweight_stocks()
    live_spot = _safe_float(live_signals.get("nifty_spot"), default=0.0)
    entry_spot = _safe_float(position.get("entry_spot") or position.get("entry_price"), default=live_spot)

    user_prompt = build_exit_prompt_context(
        position, live_signals, heavyweights, news_items, fii_dii_data,
        social_sentiment=social_sentiment, cognigraph_context=cognigraph_context
    )

    # --- STAGE 3: AI Inference (Groq Primary → Gemini Fallback) ---
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    ai_candidate = None

    # Try Groq Cloud (ultra-fast ~800ms)
    if groq_key:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }
            for model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": EXIT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }
                res = requests.post(url, headers=headers, json=payload, timeout=6.0)
                if res.status_code == 200:
                    raw_text = res.json()["choices"][0]["message"]["content"]
                    parsed = json.loads(raw_text)
                    grounded = _validate_and_ground_output(
                        parsed, live_spot, entry_spot, position=position, contrarian_warning=contrarian_warning
                    )
                    grounded = _resolve_dimension_conflict(grounded, position=position, live_spot=live_spot)
                    grounded["engine"] = f"Groq AI ({model}) — Multi-Perspective 7-Agent"
                    grounded["heavyweights"] = heavyweights
                    grounded["social_sentiment"] = social_sentiment
                    grounded["cognigraph_regime_precedent"] = cognigraph_summary
                    grounded["is_fast_path"] = False
                    grounded["is_fallback"] = False
                    logger.info(f"✅ Groq Exit Advisor Baseline: {grounded['verdict']} ({grounded['confidence']}%)")
                    ai_candidate = grounded
                    break
        except Exception as groq_err:
            logger.warning(f"Groq Exit Advisor error: {groq_err}")

    # Fallback to Google Gemini
    if not ai_candidate and gemini_key:
        try:
            for model in ["gemini-2.5-flash", "gemini-flash-latest"]:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [
                        {"role": "user", "parts": [{"text": EXIT_SYSTEM_PROMPT + "\n\n" + user_prompt}]}
                    ],
                    "generationConfig": {"response_mime_type": "application/json"}
                }
                res = requests.post(url, headers=headers, json=payload, timeout=7.0)
                if res.status_code == 200:
                    raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(raw_text)
                    grounded = _validate_and_ground_output(
                        parsed, live_spot, entry_spot, position=position, contrarian_warning=contrarian_warning
                    )
                    grounded = _resolve_dimension_conflict(grounded, position=position, live_spot=live_spot)
                    grounded["engine"] = f"Google Gemini ({model}) — Multi-Perspective 7-Agent"
                    grounded["heavyweights"] = heavyweights
                    grounded["social_sentiment"] = social_sentiment
                    grounded["cognigraph_regime_precedent"] = cognigraph_summary
                    grounded["is_fast_path"] = False
                    grounded["is_fallback"] = False
                    logger.info(f"✅ Gemini Exit Advisor Baseline: {grounded['verdict']} ({grounded['confidence']}%)")
                    ai_candidate = grounded
                    break
        except Exception as gemini_err:
            logger.warning(f"Gemini Exit Advisor error: {gemini_err}")

    # --- STAGE 4: Multi-Persona Exit Debate Committee (Runner, Guardian, Tactical, Judge) ---
    if ai_candidate:
        try:
            debated = debate_engine.run_exit_debate(
                stage1_result=ai_candidate,
                position=position,
                live_signals=live_signals,
                heavyweights=heavyweights,
                groq_key=groq_key or "",
                gemini_key=gemini_key or "",
            )
            final_res = _validate_and_ground_output(
                debated, live_spot, entry_spot, position=position, contrarian_warning=contrarian_warning
            )
            final_res["social_sentiment"] = social_sentiment
            final_res["cognigraph_regime_precedent"] = cognigraph_summary
            logger.info(f"🎯 Final Exit Advisor Decision: {final_res['verdict']} ({final_res['confidence']}%)")
            return _finalize_exit_result(final_res, position, live_signals, session_mgr=session_mgr)
        except Exception as deb_err:
            logger.warning(f"Exit Debate Committee error: {deb_err} — using baseline AI candidate.")
            return _finalize_exit_result(ai_candidate, position, live_signals, session_mgr=session_mgr)

    # --- STAGE 5: Deterministic Mathematical Fallback ---
    logger.warning("All AI models offline/timed out. Engaging Rule-Based Fallback Advisor.")
    fallback = generate_rule_based_fallback(position, live_signals, heavyweights)
    fallback["heavyweights"] = heavyweights
    fallback["social_sentiment"] = social_sentiment
    fallback["cognigraph_regime_precedent"] = cognigraph_summary or "Regime: Fallback Safe Mode"
    if "dimension_scores" not in fallback:
        fallback["dimension_scores"] = {
            "greeks_decay": {"verdict": fallback.get("verdict", "HOLD"), "note": "Deterministic rule evaluation"},
            "oi_pcr": {"verdict": fallback.get("verdict", "HOLD"), "note": "Support/resistance proximity"},
            "heavyweights": {"verdict": fallback.get("verdict", "HOLD"), "note": fallback.get("heavyweight_alignment", "Neutral")},
            "price_action": {"verdict": fallback.get("verdict", "HOLD"), "note": f"Favorable move: {fallback.get('favorable_move_pct', 0)}%"},
            "vix_regime": {"verdict": fallback.get("verdict", "HOLD"), "note": "Range-bound control"},
            "macro_global": {"verdict": fallback.get("verdict", "HOLD"), "note": "Rule fallback"},
            "social_contrarian": {"verdict": fallback.get("verdict", "HOLD"), "note": "Contrarian guardrail checked"},
            "mfe_mae": {"verdict": fallback.get("verdict", "HOLD"), "note": f"Current R: {position.get('current_r', 0)}R"},
            "order_flow": {"verdict": fallback.get("verdict", "HOLD"), "note": f"CVD: {live_signals.get('cvd_divergence', 'NEUTRAL')}"},
        }
    return _finalize_exit_result(fallback, position, live_signals, session_mgr=session_mgr)

