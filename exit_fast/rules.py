"""
exit_fast/rules.py — Unified fast-path rule evaluation engine.
"""

from datetime import datetime
from typing import Any, Optional

from .rules_critical import evaluate_critical_rules
from .rules_market import evaluate_market_rules


def _evaluate_fast_path_rules(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    current_time: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """Evaluate 9 deterministic safety rules in order of priority."""
    # 1. Critical stops & emergency conditions
    critical_result = evaluate_critical_rules(position, live_signals, current_time)
    if critical_result is not None:
        return critical_result

    # 2. Market structure, OI walls, theta, and contrarian traps
    return evaluate_market_rules(position, live_signals, current_time)
