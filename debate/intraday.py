"""
debate/intraday.py — Intraday 3-analyst debate runner.
"""

import concurrent.futures
import json
import logging
import os
import time
from typing import Any

from .constants import _get_engine_fn
from .api import _groq_call, _gemini_call
from .intraday_context import (
    INTRADAY_VERDICTS,
    _INTRADAY_MOMENTUM_SYSTEM,
    _INTRADAY_MEAN_REVERSION_SYSTEM,
    _INTRADAY_TACTICAL_SYSTEM,
    _INTRADAY_JUDGE_SYSTEM,
    _MOMENTUM_SCALPER_SYSTEM,
    _WALL_DEFENDER_SYSTEM,
    _TACTICAL_RISK_SYSTEM,
    _build_intraday_debate_context,
    _determine_intraday_consensus,
)

logger = logging.getLogger(__name__)

def _run_intraday_persona(
    persona_name: str,
    system_prompt: str,
    context: str,
    groq_key: str,
    live_spot: float,
) -> dict:
    """Execute a single intraday persona with resilient fallback."""
    t0 = time.time()
    call_groq = _get_engine_fn("_groq_call", _groq_call)
    result = call_groq(system_prompt, context, groq_key)
    elapsed = round(time.time() - t0, 2)

    if result and isinstance(result, dict) and result.get("verdict") in INTRADAY_VERDICTS:
        logger.info(f"[IntradayDebate] {persona_name}: {result.get('verdict')} ({result.get('confidence')}%) in {elapsed}s")
        return result

    logger.warning(f"[IntradayDebate] {persona_name} failed/invalid — using fallback.")
    return {
        "persona": persona_name,
        "verdict": "SCALP_DIPS_ONLY" if persona_name == "MOMENTUM" else "STRICT_WAIT_AND_WATCH",
        "confidence": 60,
        "trigger_level": round(live_spot, 1) if live_spot else 0,
        "key_wall": round(live_spot, 1) if live_spot else 0,
        "stop_loss": round(live_spot * 0.997, 1) if live_spot else 0,
        "rationale": f"{persona_name} agent offline — adopting prudent level-to-level wait-and-watch approach.",
        "_fallback": True,
    }




def run_intraday_debate(
    intraday_result: dict[str, Any],
    market_signals: dict[str, Any],
    heavyweights: dict[str, Any],
    news_sentiment: str,
    groq_key: str,
    gemini_key: str,
) -> dict[str, Any]:
    """
    Runs the 3-analyst Intraday Risk Debate committee:
    1. Momentum & Trend Scalper (Groq)
    2. Mean-Reversion & Wall Defender (Groq)
    3. Tactical Risk & Scalp Manager (Groq)
    4. Gemini Flash Intraday Synthesis Judge

    Enriches intraday_result with 'debate' breakdown, calibrated 'structure', and exact action plan.
    """
    if not groq_key:
        logger.warning("[IntradayDebate] GROQ_API_KEY not set — skipping intraday debate.")
        return intraday_result

    live_spot = float(market_signals.get("nifty_spot", 0))
    logger.info(f"[IntradayDebate] Starting 3-Analyst Intraday Debate (Spot: {live_spot})...")
    t_start = time.time()

    context = _build_intraday_debate_context(intraday_result, market_signals, heavyweights, news_sentiment)

    # Enrich with CogniGraph memory
    mom_context = context
    def_context = context
    tac_context = context
    try:
        from cognigraph import get_cognigraph
        cg = get_cognigraph()
        mom_mem = cg.get_agent_memory("MOMENTUM_SCALPER", market_signals)
        def_mem = cg.get_agent_memory("WALL_DEFENDER", market_signals)
        tac_mem = cg.get_agent_memory("TACTICAL_SCALPER", market_signals)
        if mom_mem:
            mom_context = f"{context}\n\n{mom_mem}"
        if def_mem:
            def_context = f"{context}\n\n{def_mem}"
        if tac_mem:
            tac_context = f"{context}\n\n{tac_mem}"
    except Exception as cg_err:
        logger.warning(f"[IntradayDebate] CogniGraph memory error: {cg_err}")

    call_intra = _get_engine_fn("_run_intraday_persona", _run_intraday_persona)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            fut_mom = executor.submit(call_intra, "MOMENTUM", _INTRADAY_MOMENTUM_SYSTEM, mom_context, groq_key, live_spot)
            fut_def = executor.submit(call_intra, "DEFENDER", _INTRADAY_MEAN_REVERSION_SYSTEM, def_context, groq_key, live_spot)
            fut_tac = executor.submit(call_intra, "TACTICAL", _INTRADAY_TACTICAL_SYSTEM, tac_context, groq_key, live_spot)

            mom_res = fut_mom.result(timeout=10)
            def_res = fut_def.result(timeout=10)
            tac_res = fut_tac.result(timeout=10)
    except Exception as e:
        logger.error(f"[IntradayDebate] Parallel execution failed: {e} — returning base result.")
        return intraday_result

    # If all 3 personas failed, return untouched
    if mom_res.get("_fallback") and def_res.get("_fallback") and tac_res.get("_fallback"):
        logger.warning("[IntradayDebate] All 3 personas failed — returning base intraday result.")
        return intraday_result

    t_personas = round(time.time() - t_start, 2)
    logger.info(f"[IntradayDebate] 3 personas finished in {t_personas}s")

    # ── Stage 2: Gemini Flash Intraday Judge ─────────────────────────────────
    judge_res = None
    if gemini_key:
        intraday_calib = ""
        try:
            from cognigraph import get_cognigraph
            cg = get_cognigraph()
            intraday_calib = cg.get_judge_calibration(market_signals)
        except Exception:
            intraday_calib = ""

        judge_context = f"""INTRADAY DEBATE SUBMISSIONS:

MOMENTUM & TREND SCALPER:
{json.dumps(mom_res, indent=2)}

MEAN-REVERSION & WALL DEFENDER:
{json.dumps(def_res, indent=2)}

TACTICAL RISK & SCALP MANAGER:
{json.dumps(tac_res, indent=2)}

MARKET CONTEXT:
- Live NIFTY Spot: {live_spot}
- Current Market Phase: {intraday_result.get('market_phase', {}).get('phase', 'MARKET HOURS')}
- Volatility Regime: {intraday_result.get('volatility', {}).get('level', 'MODERATE')}
- India VIX: {market_signals.get('india_vix', 12.0)} | PCR: {market_signals.get('pcr', 1.0)}

{intraday_calib}
"""
        call_gemini = _get_engine_fn("_gemini_call", _gemini_call)
        judge_raw = call_gemini(_INTRADAY_JUDGE_SYSTEM, judge_context, gemini_key)
        if judge_raw and isinstance(judge_raw, dict) and judge_raw.get("structure") in INTRADAY_VERDICTS:
            judge_res = judge_raw
            logger.info(f"[IntradayDebate] Gemini Judge: {judge_res.get('structure')} ({judge_res.get('debate_consensus')})")

    if judge_res:
        final_structure = judge_res.get("structure", "SCALP_DIPS_ONLY")
        final_action = judge_res.get("action_plan", "Trade with disciplined level-to-level risk management.")
        entry_zone = judge_res.get("entry_zone", f"{round(live_spot - 20, 1)} - {round(live_spot + 20, 1)}")
        target = judge_res.get("target") or round(live_spot + 50, 1)
        stop_loss = judge_res.get("stop_loss") or round(live_spot - 30, 1)
        consensus = judge_res.get("debate_consensus", "MAJORITY")
        conf_adj = int(judge_res.get("confidence_adjustment", 0))
        judge_rationale = judge_res.get("judge_rationale", "")
    else:
        fallback_struct, consensus, fallback_note = _determine_intraday_consensus(mom_res, def_res, tac_res)
        final_structure = fallback_struct
        final_action = f"Committee consensus: {fallback_struct}. Execute with strict stop loss."
        entry_zone = tac_res.get("entry_zone", f"{round(live_spot - 25, 1)} - {round(live_spot, 1)}")
        target = round(live_spot + 45, 1)
        stop_loss = tac_res.get("stop_loss") or round(live_spot - 30, 1)
        conf_adj = +5 if consensus == "UNANIMOUS" else (-10 if consensus == "SPLIT" else 0)
        judge_rationale = f"Gemini Judge offline — {fallback_note}"

    # Grounding Stop Loss & Target relative to spot
    if live_spot > 0:
        try:
            stop_loss = float(stop_loss)
            target = float(target)
            if "PUT" in final_structure or "BEAR" in final_structure:
                # Bearish trade: SL must be ABOVE spot, Target BELOW spot
                if stop_loss <= live_spot:
                    stop_loss = round(live_spot + 30, 1)
                if target >= live_spot:
                    target = round(live_spot - 50, 1)
            else:
                # Bullish trade: SL must be BELOW spot, Target ABOVE spot
                if stop_loss >= live_spot:
                    stop_loss = round(live_spot - 30, 1)
                if target <= live_spot:
                    target = round(live_spot + 50, 1)
        except Exception:
            stop_loss = round(live_spot - 30, 1)
            target = round(live_spot + 50, 1)

    base_bias = intraday_result.get("intraday_bias") or {}
    orig_conf = int(base_bias.get("confidence", 65))
    final_conf = max(10, min(95, orig_conf + conf_adj))

    enriched = dict(intraday_result)
    bias_copy = dict(base_bias)
    bias_copy["confidence"] = final_conf
    enriched["intraday_bias"] = bias_copy
    enriched["debate"] = {
        "momentum_scalper": {
            "verdict": mom_res.get("verdict"),
            "confidence": mom_res.get("confidence"),
            "trigger_level": mom_res.get("trigger_level"),
            "rationale": mom_res.get("rationale"),
        },
        "wall_defender": {
            "verdict": def_res.get("verdict"),
            "confidence": def_res.get("confidence"),
            "key_wall": def_res.get("key_wall"),
            "rationale": def_res.get("rationale"),
        },
        "tactical_scalper": {
            "verdict": tac_res.get("verdict"),
            "confidence": tac_res.get("confidence"),
            "entry_zone": tac_res.get("entry_zone"),
            "stop_loss": tac_res.get("stop_loss"),
            "rationale": tac_res.get("rationale"),
        },
        "structure": final_structure,
        "action_plan": final_action,
        "entry_zone": entry_zone,
        "target": target,
        "stop_loss": stop_loss,
        "consensus": consensus,
        "judge_rationale": judge_rationale,
    }

    t_total = round(time.time() - t_start, 2)
    logger.info(f"[IntradayDebate] Committee concluded: '{final_structure}' ({consensus}) in {t_total}s.")
    return enriched
