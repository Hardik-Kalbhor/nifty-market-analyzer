"""
debate package — Multi-Persona Risk Debate Engine.
"""

from .constants import (
    _safe_float,
    _GROQ_URL,
    _GEMINI_URL,
    _GROQ_MODELS,
    _GEMINI_MODELS,
    TRADE_STRUCTURES,
    _AGGRESSIVE_SYSTEM,
    _CONSERVATIVE_SYSTEM,
    _NEUTRAL_SYSTEM,
    _JUDGE_SYSTEM,
)
from .context import (
    _format_retail_score,
    _build_debate_context,
    _determine_consensus,
)
from .api import (
    _groq_call,
    _gemini_call,
    _run_persona,
    _run_judge,
)
from .btst import run_debate
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
from .exit import (
    _run_exit_persona,
    run_exit_debate,
)
from .intraday_context import (
    INTRADAY_VERDICTS,
    _MOMENTUM_SCALPER_SYSTEM,
    _WALL_DEFENDER_SYSTEM,
    _TACTICAL_RISK_SYSTEM,
    _build_intraday_debate_context,
    _determine_intraday_consensus,
)
from .intraday import (
    _run_intraday_persona,
    run_intraday_debate,
)

__all__ = [
    "_safe_float",
    "_GROQ_URL",
    "_GEMINI_URL",
    "_GROQ_MODELS",
    "_GEMINI_MODELS",
    "TRADE_STRUCTURES",
    "_AGGRESSIVE_SYSTEM",
    "_CONSERVATIVE_SYSTEM",
    "_NEUTRAL_SYSTEM",
    "_JUDGE_SYSTEM",
    "_format_retail_score",
    "_build_debate_context",
    "_determine_consensus",
    "_groq_call",
    "_gemini_call",
    "_run_persona",
    "_run_judge",
    "run_debate",
    "EXIT_VERDICTS",
    "_EXIT_RUNNER_SYSTEM",
    "_EXIT_GUARDIAN_SYSTEM",
    "_EXIT_TACTICAL_SYSTEM",
    "_build_exit_debate_context",
    "_determine_exit_consensus",
    "build_tiered_scale_out_plan",
    "_run_exit_persona",
    "run_exit_debate",
    "INTRADAY_VERDICTS",
    "_MOMENTUM_SCALPER_SYSTEM",
    "_WALL_DEFENDER_SYSTEM",
    "_TACTICAL_RISK_SYSTEM",
    "_build_intraday_debate_context",
    "_determine_intraday_consensus",
    "_run_intraday_persona",
    "run_intraday_debate",
]
