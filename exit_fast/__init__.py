"""
exit_fast package — Sub-10ms Deterministic Fast-Path Exit Engine & Fallback Generator.
"""

from .constants import (
    TIMEZONE,
    HEAVYWEIGHT_TICKERS,
    _safe_float,
    _get_now_ist,
)
from .market import (
    is_expiry_day,
    fetch_heavyweight_stocks,
)
from .scale_out import _build_scale_out_plan
from .rules import _evaluate_fast_path_rules
from .core import evaluate_fast_path
from .fallback import generate_rule_based_fallback

# Backward-compatibility alias
evaluate_exit_fast_path = evaluate_fast_path

__all__ = [
    "TIMEZONE",
    "HEAVYWEIGHT_TICKERS",
    "_safe_float",
    "_get_now_ist",
    "is_expiry_day",
    "fetch_heavyweight_stocks",
    "_build_scale_out_plan",
    "_evaluate_fast_path_rules",
    "evaluate_fast_path",
    "evaluate_exit_fast_path",
    "generate_rule_based_fallback",
]
