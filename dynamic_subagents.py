"""
dynamic_subagents.py — Backward-compatibility shim.

The implementation has been decomposed into the subagents/ package.
"""

from subagents import (  # noqa: F401
    _GROQ_URL,
    _GEMINI_URL,
    _GEMINI_MODELS,
    _GROQ_MODELS,
    SPECIALIST_SPECS,
    _clean_numeric,
    match_dynamic_subagents,
    _generate_fallback_verdict,
    evaluate_single_specialist,
    evaluate_dynamic_subagents,
    format_specialists_prompt,
)
