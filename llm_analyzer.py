"""
llm_analyzer.py — Backward-compatibility shim.

The implementation has been decomposed into the llm/ package.
"""

from llm import (  # noqa: F401
    NIFTY_50_WEIGHTS,
    SYSTEM_PROMPT,
    GeminiQuotaError,
    extract_gemini_retry_delay,
    _get_fo_expiry_context,
    _build_user_content,
    _resolve_btst_conflict,
    analyze_with_gemini,
    analyze_with_grok,
    analyze_with_groq,
    analyze_with_openai,
    analyze_with_ai_agents,
)
