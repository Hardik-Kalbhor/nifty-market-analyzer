"""
exit_fast_path.py — Backward-compatibility shim.

The implementation has been decomposed into the exit_fast/ package.
"""

from exit_fast import (  # noqa: F401
    TIMEZONE,
    HEAVYWEIGHT_TICKERS,
    _safe_float,
    _get_now_ist,
    is_expiry_day,
    fetch_heavyweight_stocks,
    _build_scale_out_plan,
    _evaluate_fast_path_rules,
    evaluate_fast_path,
    evaluate_exit_fast_path,
    generate_rule_based_fallback,
)
