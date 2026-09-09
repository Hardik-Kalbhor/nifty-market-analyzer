"""
debate/exit.py — Exit Advisor debate runner.
"""

import concurrent.futures
import json
import logging
import os
import time
from typing import Any

from .api import _groq_call
from .exit_constants import (
    EXIT_VERDICTS,
    _EXIT_RUNNER_SYSTEM,
    _EXIT_GUARDIAN_SYSTEM,
    _EXIT_TACTICAL_SYSTEM,
)
from .exit_context import (
    _build_exit_debate_context,
    _determine_exit_consensus,
    build_tiered_scale_out_plan,
)

logger = logging.getLogger(__name__)

def _run_exit_persona(persona_name: str, system_prompt: str, context: str, groq_key: str, live_spot: float, is_bullish: bool = True) -> dict:
    """Execute a single exit persona agent with safe fallback."""
    t0 = time.time()
    result = _groq_call(system_prompt, context, groq_key)
    elapsed = round(time.time() - t0, 2)

    if result and isinstance(result, dict) and result.get("verdict") in EXIT_VERDICTS:
        logger.info(f"[ExitDebate] {persona_name}: {result.get('verdict')} (conf={result.get('confidence')}%) in {elapsed}s")
        return result

    logger.warning(f"[ExitDebate] {persona_name} failed or returned invalid verdict — using fallback.")
    fallback_sl = round(live_spot * 0.995, 1) if (is_bullish and live_spot) else (round(live_spot * 1.005, 1) if live_spot else 0)
    return {
        "persona": persona_name,
        "verdict": "PARTIAL_BOOK_50",
        "confidence": 60,
        "suggested_sl": fallback_sl,
        "rationale": f"{persona_name} agent unavailable — defaulting to prudent partial de-risking.",
        "_fallback": True,
    }




def run_exit_debate(
    stage1_result: dict[str, Any],
    position: dict[str, Any],
    live_signals: dict[str, Any],
    heavyweights: dict[str, Any],
    groq_key: str,
    gemini_key: str,
) -> dict[str, Any]:
    """
    Run the 3-analyst Exit Debate committee (Runner, Capital Guardian, Tactical Manager)
    plus the Gemini Flash Exit Judge.

    Bypasses debate on emergency exits or fast-path triggers.
    Enriches stage1_result with calibrated verdict, action plan, trailing SL, and debate breakdown.
    """
    verdict = stage1_result.get("verdict", "")
    if stage1_result.get("is_fast_path") or verdict in ("EMERGENCY_EXIT", "PRE_CLOSE_EXIT"):
        logger.info(f"[ExitDebate] Bypassing debate — Fast-Path/Emergency verdict: {verdict}")
        return stage1_result

    if not groq_key:
        logger.warning("[ExitDebate] GROQ_API_KEY not set — skipping exit debate.")
        return stage1_result

    side = position.get("position_side", "BUY_CE")
    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    risk_profile = position.get("risk_profile", "BALANCED").upper()
    live_spot = _safe_float(live_signals.get("nifty_spot"), default=0.0)

    logger.info(f"[ExitDebate] Commencing 3-analyst Exit Debate for {side} (Risk: {risk_profile})...")
    t_start = time.time()

    context = _build_exit_debate_context(stage1_result, position, live_signals, heavyweights)

    # ── Stage 1: 3 Groq Exit Personas in PARALLEL ───────────────────────────
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            fut_runner = executor.submit(_run_exit_persona, "RUNNER", _EXIT_RUNNER_SYSTEM, context, groq_key, live_spot, is_bullish)
            fut_guard  = executor.submit(_run_exit_persona, "GUARDIAN", _EXIT_GUARDIAN_SYSTEM, context, groq_key, live_spot, is_bullish)
            fut_tac    = executor.submit(_run_exit_persona, "TACTICAL", _EXIT_TACTICAL_SYSTEM, context, groq_key, live_spot, is_bullish)

            runner_res   = fut_runner.result(timeout=10)
            guardian_res = fut_guard.result(timeout=10)
            tactical_res = fut_tac.result(timeout=10)
    except Exception as e:
        logger.error(f"[ExitDebate] Parallel exit persona execution failed: {e} — returning Stage 1.")
        return stage1_result

    # If all 3 personas failed (Groq down/offline), safely return Stage 1 result
    if runner_res.get("_fallback") and guardian_res.get("_fallback") and tactical_res.get("_fallback"):
        logger.warning("[ExitDebate] All 3 personas failed — returning Stage 1 result unchanged.")
        return stage1_result

    t_personas = round(time.time() - t_start, 2)
    logger.info(f"[ExitDebate] 3 personas finished in {t_personas}s")

    # ── Stage 2: Gemini Flash Exit Judge ────────────────────────────────────
    judge_res = None
    if gemini_key:
        judge_context = f"""EXIT DEBATE SUBMISSIONS:

RUNNER ANALYST:
{json.dumps(runner_res, indent=2)}

CAPITAL GUARDIAN:
{json.dumps(guardian_res, indent=2)}

TACTICAL SCALE-OUT MANAGER:
{json.dumps(tactical_res, indent=2)}

POSITION CONTEXT:
- Trade: {position.get('position_side')} ({position.get('strike')})
- Live Spot: {live_spot}
- Trader Risk Profile: {risk_profile}
- Baseline Verdict: {stage1_result.get('verdict')}

Synthesize the 3 analyst submissions into a final calibrated exit recommendation."""

        try:
            t0 = time.time()
            judge_res = _gemini_call(_EXIT_JUDGE_SYSTEM, judge_context, gemini_key, timeout=10)
            logger.info(f"[ExitDebate] Judge completed in {round(time.time() - t0, 2)}s")
        except Exception as e:
            logger.warning(f"[ExitDebate] Gemini Exit Judge failed: {e} — using rule fallback.")

    # ── Stage 3: Merge and Finalize ─────────────────────────────────────────
    if judge_res and isinstance(judge_res, dict) and judge_res.get("verdict") in EXIT_VERDICTS:
        final_verdict    = judge_res["verdict"]
        final_action     = judge_res.get("action", stage1_result.get("action", ""))
        final_sl         = judge_res.get("trailing_sl", stage1_result.get("trailing_sl"))
        consensus        = judge_res.get("debate_consensus", "MAJORITY")
        conf_adj         = int(judge_res.get("confidence_adjustment", 0))
        judge_rationale  = judge_res.get("judge_rationale", "")
        scale_out_plan   = judge_res.get("scale_out_plan") if isinstance(judge_res.get("scale_out_plan"), dict) else None
    else:
        final_verdict, consensus, fallback_note = _determine_exit_consensus(
            runner_res, guardian_res, tactical_res, risk_profile
        )
        final_action = f"Execute {final_verdict.replace('_', ' ').title()}. Committee consensus: {consensus}."
        final_sl = tactical_res.get("suggested_sl") or stage1_result.get("trailing_sl") or live_spot
        conf_adj = +5 if consensus == "UNANIMOUS" else (-10 if consensus == "SPLIT" else 0)
        judge_rationale = f"Gemini Judge offline — {fallback_note}"
        scale_out_plan = None

    if not scale_out_plan or not isinstance(scale_out_plan, dict) or "tier_1" not in scale_out_plan:
        scale_out_plan = build_tiered_scale_out_plan(
            final_verdict,
            position=position,
            live_spot=live_spot,
            trailing_sl=final_sl or live_spot,
            consensus=consensus,
        )

    orig_conf = int(stage1_result.get("confidence", 75))
    final_conf = max(10, min(95, orig_conf + conf_adj))

    enriched = dict(stage1_result)
    enriched.update({
        "verdict": final_verdict,
        "action": final_action,
        "trailing_sl": final_sl,
        "confidence": final_conf,
        "debate_consensus": consensus,
        "scale_out_plan": scale_out_plan,
        "debate": {
            "runner_analyst": {
                "verdict": runner_res.get("verdict"),
                "confidence": runner_res.get("confidence"),
                "suggested_sl": runner_res.get("suggested_sl"),
                "rationale": runner_res.get("rationale"),
            },
            "capital_guardian": {
                "verdict": guardian_res.get("verdict"),
                "confidence": guardian_res.get("confidence"),
                "suggested_sl": guardian_res.get("suggested_sl"),
                "rationale": guardian_res.get("rationale"),
            },
            "tactical_manager": {
                "verdict": tactical_res.get("verdict"),
                "confidence": tactical_res.get("confidence"),
                "suggested_sl": tactical_res.get("suggested_sl"),
                "rationale": tactical_res.get("rationale"),
            },
            "judge_rationale": judge_rationale,
        },
        "engine": (
            str(enriched.get("engine", "AI Evaluator"))
            + " → Exit Committee (3×Groq + Gemini Judge)"
        ),
    })

    t_total = round(time.time() - t_start, 2)
    logger.info(f"[ExitDebate] Successfully calibrated exit to '{final_verdict}' ({consensus}) in {t_total}s.")
    return enriched


