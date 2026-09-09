"""
debate/btst.py — BTST multi-persona debate runner.
"""

import concurrent.futures
import logging
import os
import time
from typing import Any

from .constants import (
    TRADE_STRUCTURES,
    _AGGRESSIVE_SYSTEM,
    _CONSERVATIVE_SYSTEM,
    _NEUTRAL_SYSTEM,
    _get_engine_fn,
)
from .context import _build_debate_context, _determine_consensus
from .api import _run_persona, _run_judge

logger = logging.getLogger(__name__)


def run_debate(
    stage1_result: dict[str, Any],
    market_signals: dict[str, Any],
    groq_key: str = "",
    gemini_key: str = "",
    news_items: list[dict[str, Any]] | None = None,
    heavyweights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run the 3-agent debate + dynamic catalyst specialists + synthesis judge and merge results into stage1_result.

    Returns an enriched copy of stage1_result with these additional fields:
      btst_structure   — "FULL_BTST" | "HALF_QUANTITY" | "HEDGED_SPREAD" | "STRICT_NO_TRADE"
      trade_instruction — specific 1-2 sentence actionable trade instruction
      debate_consensus — "UNANIMOUS" | "MAJORITY" | "SPLIT"
      debate           — { aggressive, conservative, neutral, dynamic_subagents, judge_rationale }
      ai_agent_provider — updated to reflect debate layer and active specialists

    On any unhandled failure, returns stage1_result UNCHANGED (safe fallback).
    Only runs when btst_bias is BUY CE or BUY PE (no point debating a confirmed NO TRADE).
    """
    btst_bias = str(stage1_result.get("btst_bias", "NO TRADE")).upper()
    if btst_bias == "NO TRADE":
        logger.info("[Debate] Skipping debate — Stage 1 already resolved to NO TRADE.")
        return stage1_result

    if not groq_key and not gemini_key:
        logger.warning("[Debate] Neither GROQ_API_KEY nor GEMINI_API_KEY set — skipping debate.")
        return stage1_result

    logger.info(f"[Debate] Starting 3-agent debate for {btst_bias}...")
    t_start = time.time()

    # Build shared base context
    context = _build_debate_context(stage1_result, market_signals)

    # Hermes FTS5 historical analog recall
    try:
        from memory_fts import get_memory_fts
        fts = get_memory_fts()
        analogs = fts.find_analogs(signals=market_signals, stage1_result=stage1_result, limit=2)
        if analogs:
            fts_analogs_str = fts.format_analogs_prompt(analogs)
            if fts_analogs_str:
                context = f"{context}\n\n{fts_analogs_str}"
    except Exception as fts_err:
        logger.debug(f"[Debate] FTS analog retrieval skipped: {fts_err}")

    # Hermes AgentSkills procedural playbooks
    try:
        from skills_engine import get_skills_engine
        se = get_skills_engine()
        matched_skills = se.match_skills(signals=market_signals, stage1_result=stage1_result)
        if matched_skills:
            skills_prompt_str = se.format_skills_prompt(matched_skills)
            if skills_prompt_str:
                context = f"{context}\n\n{skills_prompt_str}"
    except Exception as se_err:
        logger.debug(f"[Debate] Skills matching skipped in run_debate: {se_err}")

    # Dynamic Catalyst Specialists (Hermes-inspired adaptive task delegation)
    specialist_names: list[str] = []
    try:
        from dynamic_subagents import match_dynamic_subagents, evaluate_dynamic_subagents
        specialist_names = match_dynamic_subagents(
            market_signals=market_signals,
            news_items=news_items or [],
            stage1_result=stage1_result,
            heavyweights=heavyweights,
        )
        if specialist_names:
            logger.info(f"[Debate] Spawning dynamic specialist subagents: {specialist_names}")
    except Exception as match_err:
        logger.debug(f"[Debate] Dynamic subagent matching skipped: {match_err}")

    # Fetch persona-conditioned CogniGraph memory
    agg_context = context
    cons_context = context
    neut_context = context
    try:
        from cognigraph import get_cognigraph
        cg = get_cognigraph()
        agg_mem = cg.get_agent_memory("AGGRESSIVE", market_signals, stage1_result)
        cons_mem = cg.get_agent_memory("CONSERVATIVE", market_signals, stage1_result)
        neut_mem = cg.get_agent_memory("NEUTRAL", market_signals, stage1_result)
        if agg_mem:
            agg_context = f"{context}\n\n{agg_mem}"
        if cons_mem:
            cons_context = f"{context}\n\n{cons_mem}"
        if neut_mem:
            neut_context = f"{context}\n\n{neut_mem}"
    except Exception as cg_err:
        logger.warning(f"[Debate] CogniGraph memory retrieval error: {cg_err}")

    # ── Stage 2a: 3 agents + dynamic specialists in PARALLEL ────────────────
    specialist_verdicts: list[dict[str, Any]] = []
    call_persona = _get_engine_fn("_run_persona", _run_persona)
    call_judge = _get_engine_fn("_run_judge", _run_judge)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            fut_agg  = executor.submit(call_persona, "AGGRESSIVE",  _AGGRESSIVE_SYSTEM,  agg_context, groq_key, gemini_key)
            fut_cons = executor.submit(call_persona, "CONSERVATIVE", _CONSERVATIVE_SYSTEM, cons_context, groq_key, gemini_key)
            fut_neut = executor.submit(call_persona, "NEUTRAL",      _NEUTRAL_SYSTEM,      neut_context, groq_key, gemini_key)
            fut_spec = None
            if specialist_names:
                fut_spec = executor.submit(
                    evaluate_dynamic_subagents,
                    specialist_names,
                    market_signals,
                    news_items or [],
                    stage1_result,
                    gemini_key,
                    groq_key,
                )

            aggressive  = fut_agg.result(timeout=12)
            conservative = fut_cons.result(timeout=12)
            neutral     = fut_neut.result(timeout=12)
            if fut_spec:
                try:
                    specialist_verdicts = fut_spec.result(timeout=10) or []
                except Exception as s_err:
                    logger.warning(f"[Debate] Specialist execution error: {s_err}")
    except Exception as e:
        logger.error(f"[Debate] Parallel agent execution failed: {e} — returning Stage 1 unchanged.")
        return stage1_result

    t_debate = round(time.time() - t_start, 2)
    logger.info(f"[Debate] Agents & specialists completed in {t_debate}s")

    # ── Stage 2b: Gemini synthesis judge ───────────────────────────────────
    judge_result = None
    if gemini_key:
        try:
            judge_result = call_judge(
                aggressive,
                conservative,
                neutral,
                stage1_result,
                market_signals,
                gemini_key,
                specialist_verdicts=specialist_verdicts,
            )
        except Exception as e:
            logger.warning(f"[Debate] Judge failed: {e} — using vote-based fallback.")

    # ── Determine final structure ───────────────────────────────────────────
    if judge_result:
        btst_structure     = judge_result.get("btst_structure", "HALF_QUANTITY")
        trade_instruction  = judge_result.get("trade_instruction", "Proceed with reduced size.")
        debate_consensus   = judge_result.get("debate_consensus", "MAJORITY")
        conf_adj           = int(judge_result.get("confidence_adjustment", 0))
        judge_rationale    = judge_result.get("judge_rationale", "")
    else:
        # Vote-based fallback when Gemini is unavailable
        btst_structure, debate_consensus = _determine_consensus(aggressive, conservative, neutral)
        trade_instruction  = f"Take {btst_structure.replace('_', ' ').title()} position. Debate consensus: {debate_consensus}."
        conf_adj           = +5 if debate_consensus == "UNANIMOUS" else (-10 if debate_consensus == "SPLIT" else 0)
        judge_rationale    = "Gemini judge unavailable — majority vote applied."

    # Clamp confidence between 10 and 90
    orig_confidence = int(stage1_result.get("confidence", 60))
    new_confidence  = max(10, min(90, orig_confidence + conf_adj))

    t_total = round(time.time() - t_start, 2)
    logger.info(f"[Debate] Complete in {t_total}s — {btst_structure} ({debate_consensus}), "
                f"confidence {orig_confidence}% → {new_confidence}%")

    # ── Merge debate results into Stage 1 result ───────────────────────────
    enriched = dict(stage1_result)
    enriched.update({
        "btst_structure":    btst_structure,
        "trade_instruction": trade_instruction,
        "debate_consensus":  debate_consensus,
        "confidence":        new_confidence,
        "debate": {
            "aggressive":  {
                "verdict":   aggressive.get("verdict"),
                "confidence": aggressive.get("confidence"),
                "rationale":  aggressive.get("rationale"),
            },
            "conservative": {
                "verdict":   conservative.get("verdict"),
                "confidence": conservative.get("confidence"),
                "rationale":  conservative.get("rationale"),
            },
            "neutral": {
                "verdict":   neutral.get("verdict"),
                "confidence": neutral.get("confidence"),
                "rationale":  neutral.get("rationale"),
            },
            "dynamic_subagents": specialist_verdicts,
            "judge_rationale": judge_rationale,
        },
        "ai_agent_provider": (
            enriched.get("ai_agent_provider", "Groq")
            + " → Debate (3×Committee + Gemini Judge"
            + (f" + {len(specialist_verdicts)} Specialists" if specialist_verdicts else "")
            + ")"
        ),
    })

    return enriched


