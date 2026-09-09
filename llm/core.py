"""
llm/core.py — Multi-agent AI analysis orchestrator and debate runner.
"""

import os
import logging
from typing import Any, Optional

import debate_engine
from .constants import GeminiQuotaError
from .context import _build_user_content
from .resolution import _resolve_btst_conflict
from .providers import (
    analyze_with_gemini,
    analyze_with_grok,
    analyze_with_groq,
    analyze_with_openai,
)

logger = logging.getLogger(__name__)

def analyze_with_ai_agents(
    news_items: list[dict],
    market_signals: dict,
    fii_dii_data: dict | None = None,
    heavyweights: dict | None = None,
    past_context: str = "",
    run_debate: bool = False,
) -> dict[str, Any]:
    """
    6-Agent BTST Execution Engine:
    1. Primary: Groq Cloud (Ultra-Fast ~1s, Free, No Quota Blocks)
    2. Secondary: Google Gemini (gemini-2.5-flash)

    run_debate: If True, runs the 3-agent debate committee (Stage 2) after Stage 1.
                Adds btst_structure, trade_instruction, debate_consensus, and debate
                fields to the response. Defaults to False for backward compatibility.
                Automatically skipped if btst_bias == "NO TRADE".

    past_context: Phase D memory lessons from NiftyMemoryLog.load_past_context().
                  Pass "" (empty string) on first run (no memory yet).
    """
    if past_context:
        logger.info(f"Memory Phase D: Injecting {len(past_context.splitlines())} lines of past lessons into LLM prompt.")

    groq_key   = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    res = None

    if groq_key:
        logger.info("Running 6-Agent BTST Analysis via Groq Cloud...")
        res = analyze_with_groq(news_items, market_signals, groq_key, fii_dii_data, heavyweights, past_context)

    if not res and gemini_key:
        logger.info("Running 6-Agent BTST Analysis via Google Gemini API...")
        res = analyze_with_gemini(news_items, market_signals, gemini_key, fii_dii_data, heavyweights, past_context)

    if not res:
        raise ValueError("Neither GROQ_API_KEY nor GEMINI_API_KEY is configured in environment variables. Please add GROQ_API_KEY in Render Settings.")

    # ── Stage 2: Multi-Persona Debate (optional) ───────────────────────────
    if run_debate:
        logger.info("[Debate] Stage 2 triggered — running 3-agent risk committee...")
        try:
            res = debate_engine.run_debate(
                stage1_result=res,
                market_signals=market_signals,
                groq_key=groq_key or "",
                gemini_key=gemini_key or "",
                news_items=news_items,
                heavyweights=heavyweights,
            )
        except Exception as e:
            logger.error(f"[Debate] Debate stage failed unexpectedly: {e} — returning Stage 1 result.")

    return res




if __name__ == "__main__":
    sample_news = [{"headline": "HDFC Bank Q1 profit surges 25% beating estimates", "sector": "Banking & Finance"}]
    sample_signals = {"india_vix": 11.3, "pcr": 1.05, "gift_nifty_change_pct": 0.4}
    try:
        output = analyze_with_ai_agents(sample_news, sample_signals)
        print("AI Agent Output:", output)
    except Exception as e:
        print("AI Agent Error:", e)

