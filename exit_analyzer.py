"""
exit_analyzer.py — Backward-compatibility shim.

The implementation has been decomposed into the exit/ package.
"""

from exit import (  # noqa: F401
    TIMEZONE,
    EXIT_ADVISOR_SYSTEM_PROMPT,
    EXIT_SYSTEM_PROMPT,
    _validate_and_ground_output,
    format_moneyness,
    format_dte,
    format_social_and_cognigraph,
    build_exit_prompt_context,
    generate_tiered_scale_out_plan,
    _VERDICT_SEVERITY,
    _AGENT_WEIGHTS,
    _resolve_dimension_conflict,
    evaluate_exit_with_ai,
)
