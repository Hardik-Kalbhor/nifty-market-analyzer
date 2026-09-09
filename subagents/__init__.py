"""
subagents package — Dynamic Subagent Spawning & Specialist Delegation Engine.
"""

from .constants import (
    _GROQ_URL,
    _GEMINI_URL,
    _GEMINI_MODELS,
    _GROQ_MODELS,
    SPECIALIST_SPECS,
)
from .matcher import (
    _clean_numeric,
    match_dynamic_subagents,
)
from .fallback import _generate_fallback_verdict
from .evaluator import (
    evaluate_single_specialist,
    evaluate_dynamic_subagents,
    format_specialists_prompt,
)

__all__ = [
    "_GROQ_URL",
    "_GEMINI_URL",
    "_GEMINI_MODELS",
    "_GROQ_MODELS",
    "SPECIALIST_SPECS",
    "_clean_numeric",
    "match_dynamic_subagents",
    "_generate_fallback_verdict",
    "evaluate_single_specialist",
    "evaluate_dynamic_subagents",
    "format_specialists_prompt",
]
